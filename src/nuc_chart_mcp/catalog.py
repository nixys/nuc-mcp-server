from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit
import yaml

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional at import time
    jsonschema = None


MISSING = object()

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
RESOURCE_URI_RE = re.compile(r"^chart://([^/]+)(?:/(.*))?$")
WHITESPACE_RE = re.compile(r"\s+")

_SCHEMA_MAX_DEPTH = 24


class CatalogError(RuntimeError):
    """Base catalog error."""


class ChartNotFoundError(CatalogError):
    """Raised when a chart name cannot be resolved."""


class ResourceNotFoundError(CatalogError):
    """Raised when a chart resource URI cannot be resolved."""


class ToolExecutionError(CatalogError):
    """Raised for user-facing tool errors."""


@dataclass(frozen=True)
class ResolvedChartLocation:
    path: Optional[Path]
    source: str
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ChartDependency:
    name: str
    version: str = ""
    repository: str = ""
    condition: str = ""
    local_path: Optional[Path] = None
    local_version: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "repository": self.repository,
            "condition": self.condition,
            "localPath": str(self.local_path) if self.local_path else None,
            "localVersion": self.local_version or None,
            "source": self.source or None,
        }


@dataclass(frozen=True)
class ValueEntry:
    path: str
    types: Tuple[str, ...] = ()
    description: str = ""
    default: Any = MISSING
    enum: Tuple[Any, ...] = ()
    examples: Tuple[Any, ...] = ()
    required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": self.path,
            "types": list(self.types),
            "description": self.description,
            "enum": list(self.enum),
            "examples": list(self.examples),
            "required": self.required,
        }
        if self.default is not MISSING:
            payload["default"] = self.default
        return payload


@dataclass(frozen=True)
class TextAsset:
    chart_name: str
    kind: str
    path: Path
    relative_path: str
    mime_type: str
    content: str  # empty string for template assets — loaded on demand in score_asset

    @property
    def resource_uri(self) -> str:
        if self.kind == "doc":
            return f"chart://{self.chart_name}/docs/{self.relative_path}"
        return f"chart://{self.chart_name}/{self.relative_path}"

    @property
    def title(self) -> str:
        return self.relative_path


@dataclass
class SearchHit:
    chart_name: str
    relative_path: str
    kind: str
    score: int
    line_number: int
    snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart": self.chart_name,
            "path": self.relative_path,
            "kind": self.kind,
            "score": self.score,
            "lineNumber": self.line_number,
            "snippet": self.snippet,
        }


@dataclass
class ChartRecord:
    name: str
    relationship: str
    path: Optional[Path]
    available: bool
    chart_yaml: Dict[str, Any]
    description: str
    chart_type: str
    version: str
    app_version: str
    dependency: Optional[ChartDependency]
    declared_dependencies: Tuple[ChartDependency, ...] = ()
    assets: Tuple[TextAsset, ...] = ()
    readme_text: str = ""
    values_text: str = ""
    schema_text: str = ""
    values: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    supported_resources: Tuple[str, ...] = ()
    values_model: Tuple[str, ...] = ()
    value_entries: Tuple[ValueEntry, ...] = ()
    notes: Tuple[str, ...] = ()

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "relationship": self.relationship,
            "available": self.available,
            "path": str(self.path) if self.path else None,
            "description": self.description,
            "type": self.chart_type,
            "version": self.version,
            "appVersion": self.app_version,
            "dependency": self.dependency.to_dict() if self.dependency else None,
            "supportedResources": list(self.supported_resources),
            "valuesModel": list(self.values_model),
            "notes": list(self.notes),
        }


class ChartCatalog:
    """Indexes the root chart and dependency charts declared in Chart.yaml."""

    def __init__(
        self,
        root_chart_name: str,
        root_chart_dir: Path,
        search_roots: Sequence[Path],
        charts: Dict[str, ChartRecord],
        root_dependency_names: Sequence[str],
    ) -> None:
        self.root_chart_name = root_chart_name
        self.root_chart_dir = root_chart_dir
        self.search_roots = tuple(search_roots)
        self._charts = charts
        self._chart_order = [root_chart_name, *root_dependency_names]

    @classmethod
    def discover(
        cls,
        root_chart_dir: Optional[Path] = None,
        search_roots: Optional[Sequence[Path]] = None,
        root_chart_git_url: Optional[str] = None,
        root_chart_git_ref: Optional[str] = None,
        root_chart_subdir: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ) -> "ChartCatalog":
        cache_root = cls.resolve_cache_dir(cache_dir)
        root_location = cls.resolve_root_chart_dir(
            explicit_path=root_chart_dir,
            root_chart_git_url=root_chart_git_url,
            root_chart_git_ref=root_chart_git_ref,
            root_chart_subdir=root_chart_subdir,
            cache_dir=cache_root,
        )
        if root_location.path is None:
            raise CatalogError("Root chart could not be resolved.")
        root_dir = root_location.path
        normalized_roots = cls.resolve_search_roots(root_dir, search_roots)
        root_yaml = load_yaml_file(root_dir / "Chart.yaml") or {}
        root_name = root_yaml.get("name", root_dir.name)
        parsed_dependencies = tuple(cls.parse_dependencies(root_yaml))
        charts: Dict[str, ChartRecord] = {}

        dependency_names: List[str] = []
        resolved_root_dependencies: List[ChartDependency] = []

        def _resolve_one(dep: ChartDependency) -> Tuple[ChartDependency, ChartRecord]:
            resolved_location = cls.resolve_dependency_path(
                root_chart_dir=root_dir,
                search_roots=normalized_roots,
                dependency=dep,
                cache_dir=cache_root,
            )
            local_path = resolved_location.path
            resolved_dep = ChartDependency(
                name=dep.name,
                version=dep.version,
                repository=dep.repository,
                condition=dep.condition,
                local_path=local_path,
                local_version=read_chart_version(local_path) if local_path else "",
                source=resolved_location.source,
            )
            dep_notes: List[str] = list(resolved_location.notes)
            if local_path is None:
                if not dep_notes:
                    dep_notes.append(
                        "Dependency source was not resolved; only declared metadata is available."
                    )
            elif (
                resolved_dep.local_version
                and dep.version
                and resolved_dep.local_version != dep.version
            ):
                dep_notes.append(
                    "Declared dependency version does not match the resolved local chart version "
                    f"({dep.version} != {resolved_dep.local_version})."
                )
            record = cls.load_chart_record(
                name=dep.name,
                path=local_path,
                relationship="dependency",
                dependency=resolved_dep,
                declared_dependencies=tuple(),
                notes=tuple(dep_notes),
            )
            return resolved_dep, record

        _max_workers = min(8, len(parsed_dependencies)) if parsed_dependencies else 1
        with ThreadPoolExecutor(max_workers=_max_workers) as _pool:
            _ordered_futures = [
                (dep, _pool.submit(_resolve_one, dep)) for dep in parsed_dependencies
            ]
        # All futures complete after executor shutdown(wait=True)
        for dep, fut in _ordered_futures:
            dependency_names.append(dep.name)
            resolved_dep, record = fut.result()
            resolved_root_dependencies.append(resolved_dep)
            charts[dep.name] = record

        root_record = cls.load_chart_record(
            name=root_name,
            path=root_dir,
            relationship="root",
            dependency=None,
            declared_dependencies=tuple(resolved_root_dependencies),
            notes=root_location.notes,
        )
        charts[root_name] = root_record
        return cls(
            root_chart_name=root_name,
            root_chart_dir=root_dir,
            search_roots=normalized_roots,
            charts=charts,
            root_dependency_names=dependency_names,
        )

    @staticmethod
    def resolve_root_chart_dir(
        explicit_path: Optional[Path] = None,
        root_chart_git_url: Optional[str] = None,
        root_chart_git_ref: Optional[str] = None,
        root_chart_subdir: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ) -> ResolvedChartLocation:
        candidates: List[Path] = []
        if explicit_path:
            candidates.append(Path(explicit_path).expanduser())
        configured = os.environ.get("NUC_ROOT_CHART_DIR")
        if configured:
            candidates.append(Path(configured).expanduser())
        for candidate in candidates:
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="local-path",
                    notes=(),
                )

        resolved_cache = cache_dir or ChartCatalog.resolve_cache_dir(None)

        oci_ref = os.environ.get("NUC_ROOT_CHART_OCI_REF", "").strip()
        if oci_ref.startswith("oci://"):
            oci_version = os.environ.get("NUC_ROOT_CHART_OCI_VERSION", "").strip()
            chart_path = pull_oci_chart(
                ref=oci_ref,
                version=oci_version,
                cache_dir=resolved_cache,
            )
            subdir = root_chart_subdir or os.environ.get("NUC_ROOT_CHART_SUBDIR", "")
            candidate = chart_path / subdir if subdir else chart_path
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="oci",
                    notes=(
                        f"Resolved from OCI registry `{oci_ref}` version `{oci_version or 'latest'}`.",
                    ),
                )
            raise CatalogError(
                f"OCI source `{oci_ref}` was pulled, but Chart.yaml was not found in `{candidate}`."
            )

        git_url = root_chart_git_url or os.environ.get("NUC_ROOT_CHART_GIT_URL", "")
        if git_url:
            git_ref = root_chart_git_ref or os.environ.get(
                "NUC_ROOT_CHART_GIT_REF", "main"
            )
            subdir = root_chart_subdir or os.environ.get("NUC_ROOT_CHART_SUBDIR", "")
            repo_dir = clone_git_repository(
                repository_url=git_url,
                revision=git_ref,
                cache_dir=resolved_cache,
            )
            candidate = repo_dir / subdir if subdir else repo_dir
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="git",
                    notes=(
                        f"Resolved from git repository `{git_url}` at ref `{git_ref}`.",
                    ),
                )
            raise CatalogError(
                f"Git source `{git_url}` was cloned, but Chart.yaml was not found in `{candidate}`."
            )

        candidates.extend(
            [
                Path("/tmp/nxs-universal-chart"),  # nosec B108 — read-only discovery probe
                Path.cwd().parent / "nxs-universal-chart",
                Path.cwd() / "nxs-universal-chart",
            ]
        )
        for candidate in candidates:
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="local-default",
                    notes=(),
                )
        searched = "\n".join(f"- {candidate}" for candidate in candidates)
        raise CatalogError(
            "Unable to locate nxs-universal-chart. "
            "Set NUC_ROOT_CHART_DIR, NUC_ROOT_CHART_OCI_REF, NUC_ROOT_CHART_GIT_URL, "
            "or provide --root-chart-dir.\n"
            f"Searched:\n{searched}"
        )

    @staticmethod
    def resolve_cache_dir(explicit_path: Optional[Path]) -> Path:
        configured = explicit_path or (
            Path(os.environ["NUC_REMOTE_CACHE_DIR"])
            if os.environ.get("NUC_REMOTE_CACHE_DIR")
            else None
        )
        cache_dir = (
            (configured or Path(tempfile.gettempdir()) / "nuc-chart-mcp-cache")
            .expanduser()
            .resolve()
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def resolve_search_roots(
        root_chart_dir: Path, explicit_roots: Optional[Sequence[Path]]
    ) -> Tuple[Path, ...]:
        roots: List[Path] = []
        env_roots = os.environ.get("NUC_CHART_SEARCH_ROOTS")
        if env_roots:
            roots.extend(
                Path(item).expanduser() for item in env_roots.split(os.pathsep) if item
            )
        if explicit_roots:
            roots.extend(Path(item).expanduser() for item in explicit_roots)
        roots.append(root_chart_dir.parent)
        normalized: List[Path] = []
        seen: set[Path] = set()
        for root in roots:
            resolved = root.resolve()
            if resolved not in seen and resolved.exists():
                seen.add(resolved)
                normalized.append(resolved)
        return tuple(normalized)

    @staticmethod
    def parse_dependencies(chart_yaml: Dict[str, Any]) -> Iterator[ChartDependency]:
        for item in chart_yaml.get("dependencies", []) or []:
            if not isinstance(item, dict):
                continue
            yield ChartDependency(
                name=str(item.get("name", "")),
                version=str(item.get("version", "")),
                repository=str(item.get("repository", "")),
                condition=str(item.get("condition", "")),
            )

    @staticmethod
    def resolve_dependency_path(
        root_chart_dir: Path,
        search_roots: Sequence[Path],
        dependency: ChartDependency,
        cache_dir: Path,
    ) -> ResolvedChartLocation:
        repository = dependency.repository or ""
        if repository.startswith("file://"):
            candidate = Path(repository[7:]).expanduser()
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="file",
                    notes=(f"Resolved from file repository `{repository}`.",),
                )

        vendored_dir = root_chart_dir / "charts" / dependency.name
        if (vendored_dir / "Chart.yaml").exists():
            return ResolvedChartLocation(
                path=vendored_dir.resolve(),
                source="vendored",
                notes=("Resolved from the root chart `charts/` directory.",),
            )

        for root in search_roots:
            candidate = root / dependency.name
            if (candidate / "Chart.yaml").exists():
                return ResolvedChartLocation(
                    path=candidate.resolve(),
                    source="search-root",
                    notes=(f"Resolved from local search root `{root}`.",),
                )

        pulled_location = pull_dependency_chart(
            dependency=dependency, cache_dir=cache_dir
        )
        if pulled_location.path is not None:
            return pulled_location
        return ResolvedChartLocation(
            path=None,
            source="declared-only",
            notes=pulled_location.notes,
        )

    @classmethod
    def load_chart_record(
        cls,
        name: str,
        path: Optional[Path],
        relationship: str,
        dependency: Optional[ChartDependency],
        declared_dependencies: Tuple[ChartDependency, ...],
        notes: Tuple[str, ...],
    ) -> ChartRecord:
        if path is None:
            chart_yaml = {
                "name": name,
                "version": dependency.version if dependency else "",
                "description": "Local chart source not available.",
            }
            return ChartRecord(
                name=name,
                relationship=relationship,
                path=None,
                available=False,
                chart_yaml=chart_yaml,
                description=str(chart_yaml.get("description", "")),
                chart_type=str(chart_yaml.get("type", "")),
                version=str(chart_yaml.get("version", "")),
                app_version=str(chart_yaml.get("appVersion", "")),
                dependency=dependency,
                declared_dependencies=declared_dependencies,
                notes=notes,
            )

        chart_yaml = load_yaml_file(path / "Chart.yaml") or {}
        values_text = read_text_if_exists(path / "values.yaml")
        schema_text = read_text_if_exists(path / "values.schema.json")
        readme_text = read_text_if_exists(path / "README.md")
        values = _load_values_yaml(values_text)
        schema = json.loads(schema_text) if schema_text.strip() else {}
        assets = tuple(cls.collect_assets(name, path))
        supported_resources = tuple(extract_supported_resources(readme_text))
        values_model = tuple(extract_values_model(readme_text, schema))
        value_entries = tuple(SchemaIndexer(schema).build()) if schema else tuple()

        return ChartRecord(
            name=name,
            relationship=relationship,
            path=path,
            available=True,
            chart_yaml=chart_yaml,
            description=str(chart_yaml.get("description", "")),
            chart_type=str(chart_yaml.get("type", "")),
            version=str(chart_yaml.get("version", "")),
            app_version=str(chart_yaml.get("appVersion", "")),
            dependency=dependency,
            declared_dependencies=declared_dependencies,
            assets=assets,
            readme_text=readme_text,
            values_text=values_text,
            schema_text=schema_text,
            values=values if isinstance(values, dict) else {},
            schema=schema if isinstance(schema, dict) else {},
            supported_resources=supported_resources,
            values_model=values_model,
            value_entries=value_entries,
            notes=notes,
        )

    @staticmethod
    def collect_assets(chart_name: str, chart_dir: Path) -> Iterator[TextAsset]:
        candidate_files = [
            ("chart", chart_dir / "Chart.yaml", "Chart.yaml"),
            ("values", chart_dir / "values.yaml", "values.yaml"),
            ("schema", chart_dir / "values.schema.json", "values.schema.json"),
            ("readme", chart_dir / "README.md", "README.md"),
        ]
        for kind, path, relative_path in candidate_files:
            if path.exists():
                yield TextAsset(
                    chart_name=chart_name,
                    kind=kind,
                    path=path,
                    relative_path=relative_path,
                    mime_type=guess_mime_type(path),
                    content=path.read_text(encoding="utf-8"),
                )

        docs_dir = chart_dir / "docs"
        if docs_dir.exists():
            for path in sorted(
                item
                for item in docs_dir.rglob("*")
                if item.is_file() and item.suffix.lower() == ".md"
            ):
                relative = path.relative_to(docs_dir).as_posix()
                yield TextAsset(
                    chart_name=chart_name,
                    kind="doc",
                    path=path,
                    relative_path=relative,
                    mime_type="text/markdown",
                    content=path.read_text(encoding="utf-8"),
                )

        templates_dir = chart_dir / "templates"
        if templates_dir.exists():
            for path in sorted(
                item
                for item in templates_dir.rglob("*")
                if item.is_file()
                and item.suffix.lower() in {".yaml", ".yml", ".tpl", ".txt"}
            ):
                relative = f"templates/{path.relative_to(templates_dir).as_posix()}"
                yield TextAsset(
                    chart_name=chart_name,
                    kind="template",
                    path=path,
                    relative_path=relative,
                    mime_type=guess_mime_type(path),
                    content="",  # lazy-loaded on first search hit to avoid loading large template dirs upfront
                )

    def chart_names(self) -> List[str]:
        return [name for name in self._chart_order if name in self._charts]

    def list_charts(self) -> List[ChartRecord]:
        return [self._charts[name] for name in self.chart_names()]

    def get_chart(self, name: Optional[str]) -> ChartRecord:
        chart_name = self.root_chart_name if not name else name
        if chart_name not in self._charts:
            raise ChartNotFoundError(f"Unknown chart: {chart_name}")
        return self._charts[chart_name]

    def declared_dependency_names(self) -> List[str]:
        root = self.get_chart(self.root_chart_name)
        return [item.name for item in root.declared_dependencies]

    def schema_only_dependency_toggles(self) -> List[str]:
        root = self.get_chart(self.root_chart_name)
        schema_props = {
            key for key in root.schema.get("properties", {}) if key.startswith("nuc-")
        }
        declared = set(self.declared_dependency_names())
        return sorted(schema_props - declared)

    def build_catalog_summary(self) -> Dict[str, Any]:
        return {
            "rootChart": self.root_chart_name,
            "rootChartDir": str(self.root_chart_dir),
            "searchRoots": [str(item) for item in self.search_roots],
            "charts": [item.to_summary_dict() for item in self.list_charts()],
            "schemaOnlyDependencyToggles": self.schema_only_dependency_toggles(),
        }

    def format_chart_list(self) -> str:
        lines = [
            f"Root chart: {self.root_chart_name}",
            f"Resolved root path: {self.root_chart_dir}",
            "",
            "Charts:",
        ]
        for chart in self.list_charts():
            availability = "available" if chart.available else "metadata only"
            location = str(chart.path) if chart.path else "not found locally"
            extra = ""
            if chart.dependency and chart.dependency.condition:
                extra = f" | enabled by `{chart.dependency.condition}`"
            lines.append(
                f"- {chart.name} ({chart.relationship}, {chart.chart_type or 'unknown'}, "
                f"version {chart.version or 'n/a'}, {availability}){extra}"
            )
            lines.append(f"  path: {location}")
        return "\n".join(lines)

    def format_chart_overview(self, chart_name: Optional[str] = None) -> str:
        chart = self.get_chart(chart_name)
        lines = [f"# {chart.name}", ""]
        lines.append(f"- relationship: {chart.relationship}")
        lines.append(f"- source available: {'yes' if chart.available else 'no'}")
        if chart.path:
            lines.append(f"- resolved path: {chart.path}")
        lines.append(f"- type: {chart.chart_type or 'unknown'}")
        if chart.version:
            lines.append(f"- version: {chart.version}")
        if chart.app_version:
            lines.append(f"- appVersion: {chart.app_version}")
        if chart.description:
            lines.append(f"- description: {chart.description}")
        if chart.dependency:
            if chart.dependency.condition:
                lines.append(
                    f"- enabled by root values path: `{chart.dependency.condition}`"
                )
            if chart.dependency.repository:
                lines.append(f"- declared repository: {chart.dependency.repository}")
            if chart.dependency.local_version:
                lines.append(
                    f"- resolved local version: {chart.dependency.local_version}"
                )
            if chart.dependency.source:
                lines.append(f"- resolved source: {chart.dependency.source}")
        if chart.supported_resources:
            lines.append("")
            lines.append("Supported resources:")
            for item in chart.supported_resources:
                lines.append(f"- {item}")
        if chart.values_model:
            lines.append("")
            lines.append("Values model:")
            for item in chart.values_model[:25]:
                lines.append(f"- {item}")
        if chart.relationship == "root" and chart.declared_dependencies:
            lines.append("")
            lines.append("Declared dependencies:")
            for dependency in chart.declared_dependencies:
                condition = (
                    f" | condition `{dependency.condition}`"
                    if dependency.condition
                    else ""
                )
                lines.append(
                    f"- {dependency.name} {dependency.version or 'n/a'} | repo {dependency.repository or 'n/a'}{condition}"
                )
            schema_only = self.schema_only_dependency_toggles()
            if schema_only:
                lines.append("")
                lines.append(
                    "Schema-only dependency toggles (present in values schema, missing from Chart.yaml):"
                )
                for item in schema_only:
                    lines.append(f"- {item}")
        if chart.notes:
            lines.append("")
            lines.append("Notes:")
            for item in chart.notes:
                lines.append(f"- {item}")
        if chart.assets:
            lines.append("")
            lines.append("Indexed files:")
            for asset in chart.assets:
                if asset.kind in {"chart", "values", "schema", "readme", "doc"}:
                    lines.append(f"- {asset.relative_path}")
        return "\n".join(lines)

    def search_docs(
        self, query: str, chart_name: Optional[str] = None, limit: int = 8
    ) -> List[SearchHit]:
        query = query.strip()
        if not query:
            raise ToolExecutionError("`query` must not be empty.")
        target_charts = (
            [self.get_chart(chart_name)] if chart_name else self.list_charts()
        )
        hits: List[SearchHit] = []
        for chart in target_charts:
            for asset in chart.assets:
                score, line_number, snippet = score_asset(query, asset)
                if score <= 0:
                    continue
                hits.append(
                    SearchHit(
                        chart_name=chart.name,
                        relative_path=asset.relative_path,
                        kind=asset.kind,
                        score=score,
                        line_number=line_number,
                        snippet=snippet,
                    )
                )
        hits.sort(
            key=lambda item: (
                -item.score,
                item.chart_name,
                item.relative_path,
                item.line_number,
            )
        )
        return hits[: max(1, limit)]

    def format_search_results(
        self, query: str, chart_name: Optional[str] = None, limit: int = 8
    ) -> str:
        hits = self.search_docs(query=query, chart_name=chart_name, limit=limit)
        lines = [f"Query: {query}", ""]
        if not hits:
            lines.append("No matches found.")
            return "\n".join(lines)
        for index, hit in enumerate(hits, start=1):
            lines.append(
                f"{index}. [{hit.chart_name}] {hit.relative_path} "
                f"(kind={hit.kind}, score={hit.score}, line={hit.line_number})"
            )
            lines.append(f"   {hit.snippet}")
        return "\n".join(lines)

    def explain_value(
        self, path: str, chart_name: Optional[str] = None, limit: int = 8
    ) -> List[Tuple[ChartRecord, ValueEntry, int]]:
        query = path.strip()
        if not query:
            raise ToolExecutionError("`path` must not be empty.")
        target_charts = (
            [self.get_chart(chart_name)] if chart_name else self.list_charts()
        )
        hits: List[Tuple[ChartRecord, ValueEntry, int]] = []
        for chart in target_charts:
            for entry in chart.value_entries:
                score = score_value_path(query, entry.path, entry.description)
                if score > 0:
                    hits.append((chart, entry, score))
        hits.sort(key=lambda item: (-item[2], item[0].name, item[1].path))
        return hits[: max(1, limit)]

    def format_value_explanation(
        self, path: str, chart_name: Optional[str] = None, limit: int = 8
    ) -> str:
        matches = self.explain_value(path=path, chart_name=chart_name, limit=limit)
        lines = [f"Value query: {path}", ""]
        if not matches:
            lines.append("No matching values schema entries were found.")
            return "\n".join(lines)
        for index, (chart, entry, score) in enumerate(matches, start=1):
            lines.append(f"{index}. [{chart.name}] `{entry.path}` (score={score})")
            if entry.types:
                lines.append(f"   types: {', '.join(entry.types)}")
            if entry.required:
                lines.append("   required: true")
            if entry.default is not MISSING:
                lines.append(
                    f"   default: {json.dumps(entry.default, ensure_ascii=False)}"
                )
            if entry.enum:
                lines.append(
                    f"   enum: {json.dumps(list(entry.enum), ensure_ascii=False)}"
                )
            if entry.description:
                lines.append(f"   description: {entry.description}")
            if (
                chart.relationship == "dependency"
                and chart.dependency
                and chart.dependency.condition
            ):
                lines.append(f"   root toggle: `{chart.dependency.condition}`")
        return "\n".join(lines)

    @staticmethod
    def _extract_template_kinds(chart: ChartRecord) -> List[str]:
        """Extract unique Kubernetes resource kinds from template files."""
        kinds: List[str] = []
        seen: set[str] = set()
        for asset in chart.assets:
            if asset.kind != "template":
                continue
            content = asset.content
            if not content and asset.path and asset.path.exists():
                try:
                    content = asset.path.read_text(encoding="utf-8")
                except OSError:
                    continue
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped.startswith("kind:"):
                    continue
                kind = stripped[5:].split("#")[0].strip().strip("'\"")
                if kind and kind not in seen:
                    seen.add(kind)
                    kinds.append(kind)
        return kinds

    def suggest_chart_for_resource(
        self, resource: str, limit: int = 6
    ) -> List[Tuple[ChartRecord, int]]:
        query = normalize_resource_name(resource)
        if not query:
            raise ToolExecutionError("`resource` must not be empty.")
        matches: List[Tuple[ChartRecord, int]] = []
        for chart in self.list_charts():
            score = 0
            # Primary: README "Supported Resources" section
            for item in chart.supported_resources:
                normalized = normalize_resource_name(item)
                if normalized == query:
                    score = max(score, 100)
                elif query in normalized or normalized in query:
                    score = max(score, 70)
            # Fallback: scan template files for kind: entries
            if score == 0:
                for kind in self._extract_template_kinds(chart):
                    normalized_kind = normalize_resource_name(kind)
                    if normalized_kind == query:
                        score = max(score, 60)
                    elif query in normalized_kind or normalized_kind in query:
                        score = max(score, 40)
            # Last resort: README full-text search
            if score == 0 and chart.readme_text:
                text = chart.readme_text.lower()
                if query.lower() in normalize_resource_name(text):
                    score = 35
            if score > 0:
                matches.append((chart, score))
        matches.sort(key=lambda item: (-item[1], item[0].name))
        return matches[: max(1, limit)]

    def format_resource_suggestions(self, resource: str, limit: int = 6) -> str:
        matches = self.suggest_chart_for_resource(resource=resource, limit=limit)
        lines = [f"Resource query: {resource}", ""]
        if not matches:
            lines.append("No chart match was found.")
            return "\n".join(lines)
        for index, (chart, score) in enumerate(matches, start=1):
            lines.append(f"{index}. {chart.name} (score={score})")
            if chart.description:
                lines.append(f"   {chart.description}")
            if (
                chart.relationship == "dependency"
                and chart.dependency
                and chart.dependency.condition
            ):
                lines.append(
                    f"   enabled by `{chart.dependency.condition}` in the root chart"
                )
            if chart.supported_resources:
                lines.append(
                    f"   resources: {', '.join(chart.supported_resources[:12])}"
                )
        return "\n".join(lines)

    def validate_values(
        self, chart_name: Optional[str], values_yaml: str
    ) -> Dict[str, Any]:
        chart = self.get_chart(chart_name)
        if not chart.available:
            raise ToolExecutionError(
                f"Chart `{chart.name}` is not available in the current source cache."
            )
        if not chart.schema:
            raise ToolExecutionError(
                f"Chart `{chart.name}` does not provide values.schema.json."
            )
        if jsonschema is None:
            raise ToolExecutionError("The `jsonschema` package is not installed.")
        loaded = yaml.safe_load(values_yaml) if values_yaml.strip() else {}
        if loaded is None:
            loaded = {}
        validator = jsonschema.Draft7Validator(chart.schema)
        errors = sorted(validator.iter_errors(loaded), key=lambda item: list(item.path))
        return {
            "chart": chart.name,
            "valid": not errors,
            "errors": [
                {
                    "path": ".".join(str(part) for part in error.path) or "<root>",
                    "message": error.message,
                }
                for error in errors[:20]
            ],
            "errorCount": len(errors),
        }

    def format_validation_report(
        self, chart_name: Optional[str], values_yaml: str
    ) -> str:
        result = self.validate_values(chart_name=chart_name, values_yaml=values_yaml)
        lines = [
            f"Chart: {result['chart']}",
            f"Valid: {'yes' if result['valid'] else 'no'}",
        ]
        if result["valid"]:
            return "\n".join(lines)
        lines.append(f"Errors: {result['errorCount']}")
        lines.append("")
        for item in result["errors"]:
            lines.append(f"- {item['path']}: {item['message']}")
        return "\n".join(lines)

    def render_chart(
        self,
        chart_name: Optional[str],
        values_yaml: str,
        release_name: str = "mcp-preview",
        namespace: str = "default",
        include_manifest: bool = False,
    ) -> Dict[str, Any]:
        chart = self.get_chart(chart_name)
        if not chart.available or chart.path is None:
            raise ToolExecutionError(
                f"Chart `{chart.name}` is not available in the current source cache."
            )
        if chart.chart_type == "library":
            raise ToolExecutionError(
                f"Chart `{chart.name}` is a Helm library chart and cannot be rendered directly."
            )
        helm_binary = shutil.which("helm")
        if not helm_binary:
            raise ToolExecutionError("The `helm` binary was not found in PATH.")

        # Fast path: if charts/ is already populated (e.g. vendored or helm dep update was run),
        # run helm template directly against the original chart path — no copytree needed.
        charts_dir = chart.path / "charts"
        vendored = charts_dir.exists() and any(
            item.is_dir() for item in charts_dir.iterdir()
        )

        if vendored:
            with tempfile.TemporaryDirectory(prefix="nuc-chart-mcp-") as temp_dir_name:
                values_file = Path(temp_dir_name) / "values.override.yaml"
                values_file.write_text(values_yaml or "{}\n", encoding="utf-8")
                command = [
                    helm_binary,
                    "template",
                    release_name,
                    str(chart.path),
                    "--namespace",
                    namespace,
                    "--values",
                    str(values_file),
                ]
                result = subprocess.run(
                    command, check=False, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise ToolExecutionError(
                        result.stderr.strip() or "helm template failed."
                    )
                manifest = result.stdout.strip()
        else:
            # Slow path: stage a temporary copy with dependency symlinks
            with tempfile.TemporaryDirectory(prefix="nuc-chart-mcp-") as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                staged_chart = temp_dir / chart.name
                shutil.copytree(
                    chart.path,
                    staged_chart,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", ".pytest_cache"
                    ),
                )
                staged_charts_dir = staged_chart / "charts"
                staged_charts_dir.mkdir(exist_ok=True)
                for dependency in chart.declared_dependencies:
                    if not dependency.local_path:
                        continue
                    destination = staged_charts_dir / dependency.name
                    if destination.exists():
                        continue
                    try:
                        os.symlink(
                            dependency.local_path, destination, target_is_directory=True
                        )
                    except OSError:
                        shutil.copytree(
                            dependency.local_path, destination, symlinks=True
                        )

                values_file = temp_dir / "values.override.yaml"
                values_file.write_text(values_yaml or "{}\n", encoding="utf-8")
                command = [
                    helm_binary,
                    "template",
                    release_name,
                    str(staged_chart),
                    "--namespace",
                    namespace,
                    "--values",
                    str(values_file),
                ]
                result = subprocess.run(
                    command, check=False, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise ToolExecutionError(
                        result.stderr.strip() or "helm template failed."
                    )
                manifest = result.stdout.strip()

        resources = summarize_manifest(manifest)
        return {
            "chart": chart.name,
            "releaseName": release_name,
            "namespace": namespace,
            "documents": len(resources),
            "resources": resources,
            "manifest": manifest if include_manifest else "",
        }

    def format_render_report(
        self,
        chart_name: Optional[str],
        values_yaml: str,
        release_name: str = "mcp-preview",
        namespace: str = "default",
        include_manifest: bool = False,
    ) -> str:
        result = self.render_chart(
            chart_name=chart_name,
            values_yaml=values_yaml,
            release_name=release_name,
            namespace=namespace,
            include_manifest=include_manifest,
        )
        lines = [
            f"Chart: {result['chart']}",
            f"Release: {result['releaseName']}",
            f"Namespace: {result['namespace']}",
            f"Rendered documents: {result['documents']}",
            "",
            "Resources:",
        ]
        for item in result["resources"][:50]:
            location = f" ({item['namespace']})" if item["namespace"] else ""
            lines.append(f"- {item['kind']}/{item['name']}{location}")
        if include_manifest and result["manifest"]:
            lines.append("")
            lines.append("Manifest:")
            lines.append(result["manifest"])
        return "\n".join(lines)

    def list_resources(
        self, cursor: Optional[str] = None, page_size: int = 50
    ) -> Dict[str, Any]:
        all_resources: List[Dict[str, Any]] = [
            {
                "uri": "chart://catalog",
                "name": "Chart Catalog",
                "description": "Root chart and dependency chart index.",
                "mimeType": "application/json",
            }
        ]
        for chart in self.list_charts():
            all_resources.append(
                {
                    "uri": f"chart://{chart.name}/overview",
                    "name": f"{chart.name} overview",
                    "description": "Overview of chart metadata, supported resources, and values model.",
                    "mimeType": "text/markdown",
                }
            )
            all_resources.append(
                {
                    "uri": f"chart://{chart.name}/values-index",
                    "name": f"{chart.name} values index",
                    "description": "Flattened values schema index for this chart.",
                    "mimeType": "application/json",
                }
            )
            for asset in chart.assets:
                if asset.kind not in {"chart", "values", "schema", "readme", "doc"}:
                    continue
                all_resources.append(
                    {
                        "uri": asset.resource_uri,
                        "name": f"{chart.name} {asset.relative_path}",
                        "description": f"{chart.name} {asset.kind} file",
                        "mimeType": asset.mime_type,
                    }
                )

        start = 0
        if cursor:
            try:
                start = int(cursor)
            except (ValueError, TypeError):
                start = 0

        page = all_resources[start : start + page_size]
        result: Dict[str, Any] = {"resources": page}
        if start + page_size < len(all_resources):
            result["nextCursor"] = str(start + page_size)
        return result

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri == "chart://catalog":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(
                    self.build_catalog_summary(), ensure_ascii=False, indent=2
                ),
            }
        match = RESOURCE_URI_RE.match(uri)
        if not match:
            raise ResourceNotFoundError(f"Unsupported resource URI: {uri}")
        chart_name, tail = match.groups()
        chart = self.get_chart(chart_name)
        tail = tail or "overview"
        if tail == "overview":
            return {
                "uri": uri,
                "mimeType": "text/markdown",
                "text": self.format_chart_overview(chart_name),
            }
        if tail == "values-index":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(
                    [item.to_dict() for item in chart.value_entries],
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        for asset in chart.assets:
            candidate_uri = asset.resource_uri
            if candidate_uri == uri:
                content = asset.content
                if not content and asset.path and asset.path.exists():
                    content = asset.path.read_text(encoding="utf-8")
                return {"uri": uri, "mimeType": asset.mime_type, "text": content}
        raise ResourceNotFoundError(f"Resource not found: {uri}")


class SchemaIndexer:
    def __init__(self, schema: Dict[str, Any]) -> None:
        self.schema = schema or {}
        self.entries: Dict[str, ValueEntry] = {}

    def build(self) -> List[ValueEntry]:
        for name, subschema in (self.schema.get("properties") or {}).items():
            self._visit(
                str(name),
                subschema,
                required=str(name) in set(self.schema.get("required", [])),
            )
        return sorted(self.entries.values(), key=lambda item: item.path)

    def _visit(
        self,
        path: str,
        node: Any,
        required: bool = False,
        ref_stack: Tuple[str, ...] = (),
        depth: int = 0,
    ) -> None:
        if depth > _SCHEMA_MAX_DEPTH:
            # Record the node as-is without descending further to avoid stack overflow
            if isinstance(node, dict):
                self._record(path, node, required)
            return
        if not isinstance(node, dict):
            return
        # Track any $ref resolved at this level so child visits don't re-enter it.
        incoming_ref = node.get("$ref", "")
        child_ref_stack = (
            (ref_stack + (incoming_ref,))
            if incoming_ref and incoming_ref.startswith("#/")
            else ref_stack
        )
        node = self._resolve_node(node, ref_stack)
        if not isinstance(node, dict):
            return
        for combiner in ("allOf", "anyOf", "oneOf"):
            if combiner in node:
                base = {key: value for key, value in node.items() if key != combiner}
                for child in node.get(combiner, []):
                    merged = merge_schema_nodes(
                        base, child if isinstance(child, dict) else {}
                    )
                    self._visit(
                        path,
                        merged,
                        required=required,
                        ref_stack=child_ref_stack,
                        depth=depth + 1,
                    )
                return

        self._record(path, node, required)
        child_required = set(node.get("required", []))
        for name, subschema in (node.get("properties") or {}).items():
            child_path = join_schema_path(path, str(name))
            self._visit(
                child_path,
                subschema,
                required=str(name) in child_required,
                ref_stack=child_ref_stack,
                depth=depth + 1,
            )
        if isinstance(node.get("additionalProperties"), dict):
            self._visit(
                join_schema_path(path, "*"),
                node["additionalProperties"],
                required=False,
                ref_stack=child_ref_stack,
                depth=depth + 1,
            )
        for _, subschema in (node.get("patternProperties") or {}).items():
            self._visit(
                join_schema_path(path, "*"),
                subschema,
                required=False,
                ref_stack=child_ref_stack,
                depth=depth + 1,
            )
        if "items" in node:
            self._visit(
                join_schema_path(path, "[]"),
                node["items"],
                required=False,
                ref_stack=child_ref_stack,
                depth=depth + 1,
            )

    def _resolve_node(
        self, node: Dict[str, Any], ref_stack: Tuple[str, ...]
    ) -> Dict[str, Any]:
        if "$ref" not in node:
            return node
        ref = str(node["$ref"])
        if ref in ref_stack:
            return {key: value for key, value in node.items() if key != "$ref"}
        if not ref.startswith("#/"):
            return {key: value for key, value in node.items() if key != "$ref"}
        target: Any = self.schema
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target[part]
        base = self._resolve_node(
            target if isinstance(target, dict) else {}, ref_stack + (ref,)
        )
        overlay = {key: value for key, value in node.items() if key != "$ref"}
        return merge_schema_nodes(base, overlay)

    def _record(self, path: str, node: Dict[str, Any], required: bool) -> None:
        types = node.get("type", ())
        if isinstance(types, str):
            normalized_types = (types,)
        elif isinstance(types, list):
            normalized_types = tuple(str(item) for item in types)
        else:
            normalized_types = ()
        description = normalize_space(str(node.get("description", "")))
        enum = tuple(node.get("enum", [])) if isinstance(node.get("enum"), list) else ()
        examples = (
            tuple(node.get("examples", []))
            if isinstance(node.get("examples"), list)
            else ()
        )
        entry = ValueEntry(
            path=path,
            types=normalized_types,
            description=description,
            default=node.get("default", MISSING),
            enum=enum,
            examples=examples,
            required=required,
        )
        existing = self.entries.get(path)
        self.entries[path] = merge_value_entries(existing, entry)


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_values_yaml(text: str) -> Dict[str, Any]:
    if not text.strip():
        return {}
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        try:
            return next(yaml.safe_load_all(text), None) or {}
        except yaml.YAMLError:
            return {}


def load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def read_chart_version(path: Optional[Path]) -> str:
    if not path:
        return ""
    chart_yaml = load_yaml_file(path / "Chart.yaml")
    return str(chart_yaml.get("version", ""))


def pull_oci_chart(ref: str, version: str, cache_dir: Path) -> Path:
    helm_binary = shutil.which("helm")
    if not helm_binary:
        raise CatalogError(
            "The `helm` binary was not found in PATH, so OCI chart pull is unavailable."
        )

    chart_name = ref.rstrip("/").rsplit("/", 1)[-1]
    cache_key = hashlib.sha256(f"{ref}@{version}".encode("utf-8")).hexdigest()[:16]
    dest_dir = cache_dir / "oci" / cache_key
    chart_dir = dest_dir / chart_name

    if (chart_dir / "Chart.yaml").exists():
        return chart_dir.resolve()

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    command = [helm_binary, "pull", "--untar", "--untardir", str(dest_dir)]
    if version:
        command += ["--version", version]
    command.append(ref)

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise CatalogError(
            f"Failed to pull OCI chart `{ref}@{version}`: "
            f"{normalize_space(result.stderr or result.stdout or 'helm pull failed')}"
        )
    if not (chart_dir / "Chart.yaml").exists():
        raise CatalogError(f"Chart.yaml not found after pulling `{ref}`")

    return chart_dir.resolve()


def clone_git_repository(repository_url: str, revision: str, cache_dir: Path) -> Path:
    git_binary = shutil.which("git")
    if not git_binary:
        raise CatalogError(
            "The `git` binary was not found in PATH, so remote chart cloning is unavailable."
        )

    repo_hash = hashlib.sha256(
        f"{repository_url}@{revision}".encode("utf-8")
    ).hexdigest()[:16]
    target_dir = cache_dir / "git" / repo_hash

    # Cache hit: .git directory signals a completed clone — skip re-fetching.
    if (target_dir / ".git").exists():
        return target_dir

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Isolate git from system/user config to prevent SSH URL rewrites in containers.
    git_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
    # Identity rewrite for the base URL ensures any insteadOf rule from inherited env is overridden.
    parsed = urlsplit(repository_url)
    https_base = f"{parsed.scheme}://{parsed.netloc}/"
    git_force_https = ["-c", f"url.{https_base}.insteadOf={https_base}"]

    run_external_command(
        [git_binary, "init", str(target_dir)],
        "Unable to initialize the git cache directory",
        env=git_env,
    )
    run_external_command(
        [git_binary, "-C", str(target_dir), "remote", "add", "origin", repository_url],
        f"Unable to add remote `{repository_url}`",
        env=git_env,
    )
    run_external_command(
        [
            git_binary,
            "-C",
            str(target_dir),
            *git_force_https,
            "fetch",
            "--depth",
            "1",
            "origin",
            revision,
        ],
        f"Unable to fetch `{revision}` from `{repository_url}`",
        env=git_env,
    )
    run_external_command(
        [git_binary, "-C", str(target_dir), "checkout", "--detach", "FETCH_HEAD"],
        f"Unable to checkout `{revision}` from `{repository_url}`",
        env=git_env,
    )
    return target_dir


def pull_dependency_chart(
    dependency: ChartDependency, cache_dir: Path
) -> ResolvedChartLocation:
    repository = dependency.repository.strip()
    if not repository:
        return ResolvedChartLocation(
            path=None,
            source="declared-only",
            notes=("The dependency does not declare a repository URL.",),
        )

    helm_binary = shutil.which("helm")
    if not helm_binary:
        return ResolvedChartLocation(
            path=None,
            source="declared-only",
            notes=(
                "The `helm` binary was not found in PATH, so remote dependency fetch is unavailable.",
            ),
        )

    chart_version = dependency.version.strip()
    target_root = cache_dir / "helm" / dependency.name / (chart_version or "latest")
    chart_path = target_root / dependency.name
    if (chart_path / "Chart.yaml").exists():
        return ResolvedChartLocation(
            path=chart_path.resolve(),
            source="repository-cache",
            notes=(f"Resolved from cached repository pull `{repository}`.",),
        )

    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    if repository.startswith("oci://"):
        chart_ref = f"{repository.rstrip('/')}/{dependency.name}"
        command = [helm_binary, "pull", chart_ref]
    else:
        command = [helm_binary, "pull", dependency.name, "--repo", repository]

    if chart_version:
        command.extend(["--version", chart_version])
    command.extend(["--untar", "--untardir", str(target_root)])

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ResolvedChartLocation(
            path=None,
            source="declared-only",
            notes=(
                f"Remote fetch from `{repository}` failed: {normalize_space(result.stderr or result.stdout or 'helm pull failed')}",
            ),
        )
    if not (chart_path / "Chart.yaml").exists():
        return ResolvedChartLocation(
            path=None,
            source="declared-only",
            notes=(
                f"`helm pull` completed, but the unpacked chart `{chart_path}` was not found.",
            ),
        )
    return ResolvedChartLocation(
        path=chart_path.resolve(),
        source="repository",
        notes=(f"Pulled from remote chart repository `{repository}`.",),
    )


def run_external_command(
    command: Sequence[str],
    error_prefix: str,
    env: Optional[Dict[str, str]] = None,
) -> None:
    result = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        return
    stderr = normalize_space(result.stderr)
    stdout = normalize_space(result.stdout)
    detail = stderr or stdout or "command failed"
    raise CatalogError(f"{error_prefix}: {detail}")


def guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return "text/yaml"
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain"


def normalize_space(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value or "").strip()


def normalize_title(value: str) -> str:
    return normalize_space(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()))


def normalize_resource_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def extract_markdown_section(text: str, titles: Iterable[str]) -> str:
    wanted = {normalize_title(title) for title in titles}
    capture = False
    level = 0
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = HEADING_RE.match(line.strip())
        if heading:
            current_level = len(heading.group(1))
            title = normalize_title(heading.group(2))
            if capture and current_level <= level:
                break
            if title in wanted:
                capture = True
                level = current_level
                continue
        if capture:
            lines.append(line)
    return "\n".join(lines).strip()


def extract_supported_resources(readme_text: str) -> List[str]:
    section = extract_markdown_section(readme_text, ["Supported Resources"])
    items = extract_bullet_items(section)
    if not items:
        items = extract_table_first_column(section)
    return dedupe(items)


def extract_values_model(readme_text: str, schema: Dict[str, Any]) -> List[str]:
    section = extract_markdown_section(
        readme_text, ["Values Model", "Dependency Toggle Fields"]
    )
    items = extract_bullet_items(section)
    if not items:
        items = [str(item) for item in (schema.get("properties") or {}).keys()]
    return dedupe(items[:30])


def extract_bullet_items(section: str) -> List[str]:
    items: List[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith(("- ", "* ")):
            continue
        body = line[2:].strip()
        code_items = re.findall(r"`([^`]+)`", body)
        if code_items:
            items.extend(code_items)
        else:
            items.append(re.sub(r"\s+", " ", body))
    return items


def extract_table_first_column(section: str) -> List[str]:
    items: List[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if not columns or columns[0].lower() in {"subchart", "field", "key"}:
            continue
        item = columns[0].strip("` ")
        if item:
            items.append(item)
    return items


def dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        normalized = normalize_space(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def merge_schema_nodes(
    base: Dict[str, Any], override: Dict[str, Any]
) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_schema_nodes(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_value_entries(
    existing: Optional[ValueEntry], new_entry: ValueEntry
) -> ValueEntry:
    if existing is None:
        return new_entry
    types = tuple(dict.fromkeys([*existing.types, *new_entry.types]))
    description = existing.description or new_entry.description
    default = existing.default if existing.default is not MISSING else new_entry.default
    enum = tuple(dict.fromkeys([*existing.enum, *new_entry.enum]))
    examples = tuple(dict.fromkeys([*existing.examples, *new_entry.examples]))
    required = existing.required or new_entry.required
    return ValueEntry(
        path=existing.path,
        types=types,
        description=description,
        default=default,
        enum=enum,
        examples=examples,
        required=required,
    )


def join_schema_path(prefix: str, suffix: str) -> str:
    if suffix == "[]":
        return f"{prefix}[]"
    if not prefix:
        return suffix
    return f"{prefix}.{suffix}"


def split_path_segments(path: str) -> List[str]:
    normalized = path.replace("[*]", "[]")
    parts = [part for part in normalized.split(".") if part]
    segments: List[str] = []
    for part in parts:
        while part.endswith("[]") and part != "[]":
            segments.append(part[:-2])
            segments.append("[]")
            part = ""
        if part:
            segments.append(part)
    return [item for item in segments if item]


def path_structurally_matches(query: str, schema_path: str) -> bool:
    query_segments = split_path_segments(query)
    schema_segments = split_path_segments(schema_path)
    if len(query_segments) != len(schema_segments):
        return False
    for left, right in zip(query_segments, schema_segments):
        if right in {"*", "[]"}:
            continue
        if left.lower() != right.lower():
            return False
    return True


def path_prefix_matches(query: str, schema_path: str) -> bool:
    query_segments = split_path_segments(query)
    schema_segments = split_path_segments(schema_path)
    if len(query_segments) > len(schema_segments):
        return False
    for left, right in zip(query_segments, schema_segments):
        if right in {"*", "[]"}:
            continue
        if left.lower() != right.lower():
            return False
    return True


def score_value_path(query: str, schema_path: str, description: str) -> int:
    query_norm = query.lower().strip()
    schema_norm = schema_path.lower()
    if query_norm == schema_norm:
        return 120
    if path_structurally_matches(query_norm, schema_norm):
        return 110
    if path_prefix_matches(query_norm, schema_norm):
        return 90 - max(
            0,
            len(split_path_segments(schema_norm))
            - len(split_path_segments(query_norm)),
        )
    query_tail = (
        split_path_segments(query_norm)[-1]
        if split_path_segments(query_norm)
        else query_norm
    )
    schema_tail = (
        split_path_segments(schema_norm)[-1]
        if split_path_segments(schema_norm)
        else schema_norm
    )
    if query_tail and query_tail == schema_tail:
        return 50
    if query_norm in schema_norm:
        return 40
    if query_tail and query_tail in description.lower():
        return 20
    return 0


def score_asset(query: str, asset: TextAsset) -> Tuple[int, int, str]:
    # Template content is stored as "" and loaded on first access to avoid reading
    # large template directories (some charts have 100+ template files) at startup.
    content = asset.content
    if not content and asset.kind == "template" and asset.path.exists():
        try:
            content = asset.path.read_text(encoding="utf-8")
        except OSError:
            return 0, 0, ""

    lowered_query = query.lower().strip()
    terms = [item for item in re.split(r"\s+", lowered_query) if item]
    haystack = content.lower()
    path_score = 12 if lowered_query in asset.relative_path.lower() else 0
    line_number = 1
    snippet = ""
    score = 0
    if lowered_query and lowered_query in haystack:
        score += 30
        index = haystack.index(lowered_query)
        line_number = content[:index].count("\n") + 1
        snippet = build_snippet(content, index, len(lowered_query))
    elif terms and all(term in haystack for term in terms):
        score += 18
        positions = [haystack.index(term) for term in terms if term in haystack]
        index = min(positions) if positions else 0
        line_number = content[:index].count("\n") + 1
        snippet = build_snippet(content, index, len(terms[0]) if terms else 1)
    elif any(term in haystack for term in terms):
        score += 8
        matched = next(term for term in terms if term in haystack)
        index = haystack.index(matched)
        line_number = content[:index].count("\n") + 1
        snippet = build_snippet(content, index, len(matched))
    else:
        return 0, 0, ""

    score += path_score
    if asset.kind == "readme":
        score += 6
    elif asset.kind == "doc":
        score += 4
    return score, line_number, snippet


def build_snippet(content: str, start_index: int, match_length: int) -> str:
    start = max(0, start_index - 110)
    end = min(len(content), start_index + match_length + 110)
    snippet = content[start:end].replace("\n", " ")
    snippet = normalize_space(snippet)
    return snippet


def summarize_manifest(manifest: str) -> List[Dict[str, str]]:
    resources: List[Dict[str, str]] = []
    if not manifest.strip():
        return resources
    for document in yaml.safe_load_all(manifest):
        if not isinstance(document, dict):
            continue
        metadata = document.get("metadata") or {}
        resources.append(
            {
                "kind": str(document.get("kind", "Unknown")),
                "name": str(metadata.get("name", "")),
                "namespace": str(metadata.get("namespace", "")),
            }
        )
    return resources
