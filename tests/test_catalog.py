from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from nuc_chart_mcp.catalog import (
    ChartCatalog,
    ChartNotFoundError,
    ResourceNotFoundError,
    SchemaIndexer,
    ToolExecutionError,
    _load_values_yaml,
    dedupe,
    extract_bullet_items,
    extract_supported_resources,
    normalize_space,
    score_value_path,
    split_path_segments,
)


ROOT_SCHEMA = {
    "type": "object",
    "properties": {
        "generic": {
            "type": "object",
            "properties": {
                "fullnameOverride": {
                    "type": "string",
                    "description": "Deterministic base name override.",
                }
            },
        },
        "deployments": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "replicas": {
                        "type": "integer",
                        "description": "Replica count for a deployment entry.",
                        "default": 1,
                    }
                },
            },
        },
        "nuc-native-gateway": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "Enable the gateway dependency.",
                    "default": False,
                }
            },
        },
        "nuc-argocd": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "Schema-only toggle.",
                }
            },
        },
    },
}

DEPENDENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {
            "type": "boolean",
            "description": "Enable rendering for this subchart.",
            "default": True,
        },
        "gateways": {
            "type": "object",
            "description": "Map of Gateway resources keyed by name.",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Gateway resource name.",
                    }
                },
            },
        },
    },
}


class ChartCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.root_chart = self.workspace / "nxs-universal-chart"
        self.dep_chart = self.workspace / "nuc-native-gateway"
        self._write_root_chart()
        self._write_dependency_chart()
        self.catalog = ChartCatalog.discover(
            root_chart_dir=self.root_chart,
            search_roots=[self.workspace],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_root_chart(self) -> None:
        (self.root_chart / "docs").mkdir(parents=True)
        (self.root_chart / "templates").mkdir(parents=True)
        (self.root_chart / "Chart.yaml").write_text(
            textwrap.dedent(
                """\
                apiVersion: v2
                name: nxs-universal-chart
                description: Root chart for applications
                type: application
                version: 3.0.7
                dependencies:
                  - name: nuc-native-gateway
                    version: 1.0.4
                    repository: oci://registry.nixys.ru/nuc
                    condition: nuc-native-gateway.enabled
                """
            ),
            encoding="utf-8",
        )
        (self.root_chart / "values.yaml").write_text(
            "generic: {}\ndeployments: {}\nnuc-native-gateway:\n  enabled: false\n",
            encoding="utf-8",
        )
        (self.root_chart / "values.schema.json").write_text(
            json.dumps(ROOT_SCHEMA), encoding="utf-8"
        )
        (self.root_chart / "README.md").write_text(
            textwrap.dedent(
                """\
                # Root

                ## Supported Resources

                - `Deployment`
                - `Service`

                ## Values Model

                - `generic`
                - `deployments`
                - `nuc-native-gateway`
                """
            ),
            encoding="utf-8",
        )
        (self.root_chart / "docs" / "DEPENDENCY.md").write_text(
            "Use nuc-native-gateway for Gateway API resources.\n",
            encoding="utf-8",
        )
        (self.root_chart / "templates" / "configmap.yaml").write_text(
            "{{- if .Values.generic }}\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: test\n{{- end }}\n",
            encoding="utf-8",
        )

    def _write_dependency_chart(self) -> None:
        self.dep_chart.mkdir(parents=True)
        (self.dep_chart / "Chart.yaml").write_text(
            textwrap.dedent(
                """\
                apiVersion: v2
                name: nuc-native-gateway
                description: Gateway API standard resources
                type: application
                version: 1.0.9
                """
            ),
            encoding="utf-8",
        )
        (self.dep_chart / "values.yaml").write_text(
            "enabled: true\ngateways: {}\n", encoding="utf-8"
        )
        (self.dep_chart / "values.schema.json").write_text(
            json.dumps(DEPENDENCY_SCHEMA), encoding="utf-8"
        )
        (self.dep_chart / "README.md").write_text(
            textwrap.dedent(
                """\
                # Gateway

                ## Supported Resources

                - `Gateway`
                - `HTTPRoute`

                ## Values Model

                - `enabled`
                - `gateways`
                """
            ),
            encoding="utf-8",
        )

    def test_discovers_root_and_declared_dependency(self) -> None:
        charts = self.catalog.list_charts()
        self.assertEqual(
            [item.name for item in charts],
            ["nxs-universal-chart", "nuc-native-gateway"],
        )
        dependency = self.catalog.get_chart("nuc-native-gateway")
        self.assertTrue(dependency.available)
        self.assertEqual(dependency.dependency.condition, "nuc-native-gateway.enabled")

    def test_reports_schema_only_toggles(self) -> None:
        self.assertEqual(self.catalog.schema_only_dependency_toggles(), ["nuc-argocd"])

    def test_search_finds_dependency_docs(self) -> None:
        results = self.catalog.search_docs("HTTPRoute", chart_name=None, limit=3)
        self.assertTrue(results)
        self.assertTrue(
            any(item.chart_name == "nuc-native-gateway" for item in results)
        )

    def test_explain_value_matches_wildcard_schema_paths(self) -> None:
        matches = self.catalog.explain_value("deployments.api.replicas")
        self.assertTrue(matches)
        chart, entry, _ = matches[0]
        self.assertEqual(chart.name, "nxs-universal-chart")
        self.assertEqual(entry.path, "deployments.*.replicas")

    def test_resource_read_returns_catalog_json(self) -> None:
        resource = self.catalog.read_resource("chart://catalog")
        payload = json.loads(resource["text"])
        self.assertEqual(payload["rootChart"], "nxs-universal-chart")
        self.assertEqual(len(payload["charts"]), 2)

    def test_discovers_root_chart_from_git_repository(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        remote_repo = self.workspace / "remote-root"
        shutil.copytree(self.root_chart, remote_repo)
        subprocess.run(
            ["git", "init", str(remote_repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(remote_repo), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(remote_repo), "config", "user.name", "Test User"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(remote_repo), "add", "."],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(remote_repo), "commit", "-m", "initial"],
            check=True,
            capture_output=True,
            text=True,
        )

        cache_dir = self.workspace / "cache"
        catalog = ChartCatalog.discover(
            root_chart_git_url=remote_repo.as_uri(),
            root_chart_git_ref="HEAD",
            search_roots=[self.workspace],
            cache_dir=cache_dir,
        )

        root = catalog.get_chart("nxs-universal-chart")
        self.assertIsNotNone(root.path)
        self.assertTrue(str(root.path).startswith(str(cache_dir)))
        self.assertTrue(any("git repository" in note for note in root.notes))


class CatalogValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.root_chart = self.workspace / "nxs-universal-chart"
        self.dep_chart = self.workspace / "nuc-native-gateway"
        self._write_charts()
        self.catalog = ChartCatalog.discover(
            root_chart_dir=self.root_chart,
            search_roots=[self.workspace],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_charts(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "replicas": {
                    "type": "integer",
                    "description": "Number of replicas.",
                    "default": 1,
                },
                "image": {"type": "string", "description": "Container image."},
                "nuc-native-gateway": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "Enable gateway subchart.",
                            "default": False,
                        }
                    },
                },
            },
            "additionalProperties": False,
        }
        self.root_chart.mkdir(parents=True)
        (self.root_chart / "Chart.yaml").write_text(
            textwrap.dedent("""\
                apiVersion: v2
                name: nxs-universal-chart
                description: Root chart
                type: application
                version: 3.0.21
                dependencies:
                  - name: nuc-native-gateway
                    version: 1.0.4
                    repository: oci://registry.nixys.ru/nuc
                    condition: nuc-native-gateway.enabled
            """),
            encoding="utf-8",
        )
        (self.root_chart / "values.yaml").write_text(
            "replicas: 1\nimage: nginx\n", encoding="utf-8"
        )
        (self.root_chart / "values.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )
        (self.root_chart / "README.md").write_text(
            "# Root\n\n## Supported Resources\n\n- `Deployment`\n- `Service`\n",
            encoding="utf-8",
        )

        self.dep_chart.mkdir(parents=True)
        (self.dep_chart / "Chart.yaml").write_text(
            textwrap.dedent("""\
                apiVersion: v2
                name: nuc-native-gateway
                description: Gateway chart
                type: application
                version: 1.0.4
            """),
            encoding="utf-8",
        )
        (self.dep_chart / "values.yaml").write_text("enabled: true\n", encoding="utf-8")
        (self.dep_chart / "README.md").write_text(
            "# Gateway\n\n## Supported Resources\n\n- `Gateway`\n- `HTTPRoute`\n",
            encoding="utf-8",
        )

    def test_validate_valid_values_returns_no_errors(self) -> None:
        result = self.catalog.validate_values(
            chart_name="nxs-universal-chart",
            values_yaml="replicas: 3\nimage: nginx:latest\n",
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["errorCount"], 0)
        self.assertEqual(result["errors"], [])

    def test_validate_invalid_values_detects_type_error(self) -> None:
        result = self.catalog.validate_values(
            chart_name="nxs-universal-chart",
            values_yaml='replicas: "not-an-integer"\n',
        )
        self.assertFalse(result["valid"])
        self.assertGreater(result["errorCount"], 0)
        error_paths = [e["path"] for e in result["errors"]]
        self.assertIn("replicas", error_paths)

    def test_validate_additional_properties_are_rejected(self) -> None:
        result = self.catalog.validate_values(
            chart_name="nxs-universal-chart",
            values_yaml="unknown_field: yes\n",
        )
        self.assertFalse(result["valid"])

    def test_validate_empty_values_passes_schema(self) -> None:
        result = self.catalog.validate_values(
            chart_name="nxs-universal-chart",
            values_yaml="",
        )
        self.assertTrue(result["valid"])

    def test_validate_chart_without_schema_raises_tool_error(self) -> None:
        with self.assertRaises(ToolExecutionError):
            self.catalog.validate_values(
                chart_name="nuc-native-gateway",
                values_yaml="enabled: true\n",
            )

    def test_format_validation_report_valid(self) -> None:
        report = self.catalog.format_validation_report(
            chart_name="nxs-universal-chart",
            values_yaml="replicas: 2\n",
        )
        self.assertIn("Valid: yes", report)

    def test_format_validation_report_invalid(self) -> None:
        report = self.catalog.format_validation_report(
            chart_name="nxs-universal-chart",
            values_yaml='replicas: "bad"\n',
        )
        self.assertIn("Valid: no", report)
        self.assertIn("replicas", report)

    def test_get_chart_raises_for_unknown_name(self) -> None:
        with self.assertRaises(ChartNotFoundError):
            self.catalog.get_chart("does-not-exist")

    def test_suggest_chart_for_resource_matches_readme(self) -> None:
        matches = self.catalog.suggest_chart_for_resource("Gateway")
        self.assertTrue(matches)
        chart_names = [chart.name for chart, _ in matches]
        self.assertIn("nuc-native-gateway", chart_names)

    def test_suggest_chart_for_resource_returns_empty_for_unknown(self) -> None:
        matches = self.catalog.suggest_chart_for_resource("XyzAbcNothing")
        self.assertEqual(matches, [])

    def test_format_resource_suggestions_no_match(self) -> None:
        text = self.catalog.format_resource_suggestions("Frobnicator")
        self.assertIn("No chart match was found", text)

    def test_resource_listing_includes_catalog_and_overviews(self) -> None:
        result = self.catalog.list_resources()
        uris = [r["uri"] for r in result["resources"]]
        self.assertIn("chart://catalog", uris)
        self.assertIn("chart://nxs-universal-chart/overview", uris)
        self.assertIn("chart://nuc-native-gateway/overview", uris)

    def test_resource_read_values_yaml_returns_content(self) -> None:
        resource = self.catalog.read_resource("chart://nxs-universal-chart/values.yaml")
        self.assertEqual(resource["mimeType"], "text/yaml")
        self.assertIn("replicas", resource["text"])

    def test_resource_read_readme_returns_markdown(self) -> None:
        resource = self.catalog.read_resource("chart://nxs-universal-chart/README.md")
        self.assertEqual(resource["mimeType"], "text/markdown")
        self.assertIn("Root", resource["text"])

    def test_resource_read_overview_returns_markdown(self) -> None:
        resource = self.catalog.read_resource("chart://nxs-universal-chart/overview")
        self.assertEqual(resource["mimeType"], "text/markdown")
        self.assertIn("nxs-universal-chart", resource["text"])

    def test_resource_read_values_index_returns_json(self) -> None:
        resource = self.catalog.read_resource(
            "chart://nxs-universal-chart/values-index"
        )
        self.assertEqual(resource["mimeType"], "application/json")
        entries = json.loads(resource["text"])
        self.assertIsInstance(entries, list)
        paths = [e["path"] for e in entries]
        self.assertIn("replicas", paths)

    def test_resource_read_unknown_uri_raises(self) -> None:
        with self.assertRaises(ResourceNotFoundError):
            self.catalog.read_resource(
                "chart://nxs-universal-chart/nonexistent-file.yaml"
            )

    def test_resource_read_malformed_uri_raises(self) -> None:
        with self.assertRaises(ResourceNotFoundError):
            self.catalog.read_resource("http://not-a-chart-uri")

    def test_format_chart_list_mentions_all_charts(self) -> None:
        text = self.catalog.format_chart_list()
        self.assertIn("nxs-universal-chart", text)
        self.assertIn("nuc-native-gateway", text)

    def test_format_chart_overview_includes_condition(self) -> None:
        text = self.catalog.format_chart_overview("nuc-native-gateway")
        self.assertIn("nuc-native-gateway.enabled", text)

    def test_build_catalog_summary_structure(self) -> None:
        summary = self.catalog.build_catalog_summary()
        self.assertEqual(summary["rootChart"], "nxs-universal-chart")
        self.assertIn("charts", summary)
        self.assertIn("searchRoots", summary)

    def test_unavailable_dependency_shows_in_catalog(self) -> None:
        # Chart declared in Chart.yaml but not resolvable locally and no remote available
        workspace2 = self.workspace / "workspace2"
        workspace2.mkdir()
        root2 = workspace2 / "nxs-universal-chart"
        root2.mkdir()
        (root2 / "Chart.yaml").write_text(
            textwrap.dedent("""\
                apiVersion: v2
                name: nxs-universal-chart
                type: application
                version: 3.0.0
                dependencies:
                  - name: nuc-does-not-exist
                    version: 1.0.0
                    repository: ""
                    condition: nuc-does-not-exist.enabled
            """),
            encoding="utf-8",
        )
        (root2 / "values.yaml").write_text("", encoding="utf-8")
        catalog2 = ChartCatalog.discover(
            root_chart_dir=root2, search_roots=[workspace2]
        )
        missing = catalog2.get_chart("nuc-does-not-exist")
        self.assertFalse(missing.available)
        self.assertIsNone(missing.path)


class CatalogHelperFunctionsTest(unittest.TestCase):
    def test_load_values_yaml_empty_returns_empty_dict(self) -> None:
        self.assertEqual(_load_values_yaml(""), {})
        self.assertEqual(_load_values_yaml("   "), {})

    def test_load_values_yaml_basic_mapping(self) -> None:
        result = _load_values_yaml("replicas: 3\nimage: nginx\n")
        self.assertEqual(result, {"replicas": 3, "image": "nginx"})

    def test_load_values_yaml_with_document_end_marker(self) -> None:
        # Values files with YAML `...` document-end markers (e.g. nuc-envoy-gateway)
        text = "replicas: 1\nimage: nginx\n...\nextra: ignored\n"
        result = _load_values_yaml(text)
        # Must return the first document without crashing
        self.assertIsInstance(result, dict)
        self.assertIn("replicas", result)

    def test_load_values_yaml_invalid_returns_empty_dict(self) -> None:
        result = _load_values_yaml(": bad: yaml: [unclosed")
        self.assertIsInstance(result, dict)

    def test_normalize_space_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_space("  hello   world  "), "hello world")
        self.assertEqual(normalize_space(""), "")

    def test_dedupe_preserves_order_and_removes_duplicates(self) -> None:
        result = dedupe(["a", "b", "a", "c", "b"])
        self.assertEqual(result, ["a", "b", "c"])

    def test_dedupe_removes_empty_strings(self) -> None:
        result = dedupe(["", "  ", "a"])
        self.assertEqual(result, ["a"])

    def test_extract_bullet_items_with_backtick_code(self) -> None:
        section = "- `Deployment`\n- `Service`\n- plain item\n"
        items = extract_bullet_items(section)
        self.assertIn("Deployment", items)
        self.assertIn("Service", items)
        self.assertIn("plain item", items)

    def test_extract_supported_resources_from_readme(self) -> None:
        readme = "# Chart\n\n## Supported Resources\n\n- `Deployment`\n- `Service`\n"
        items = extract_supported_resources(readme)
        self.assertIn("Deployment", items)
        self.assertIn("Service", items)

    def test_split_path_segments_basic(self) -> None:
        self.assertEqual(split_path_segments("a.b.c"), ["a", "b", "c"])

    def test_split_path_segments_with_array_notation(self) -> None:
        self.assertEqual(split_path_segments("items[].name"), ["items", "[]", "name"])

    def test_score_value_path_exact_match(self) -> None:
        score = score_value_path("deployments.*.replicas", "deployments.*.replicas", "")
        self.assertEqual(score, 120)

    def test_score_value_path_structural_match(self) -> None:
        score = score_value_path(
            "deployments.myapp.replicas", "deployments.*.replicas", ""
        )
        self.assertGreaterEqual(score, 100)

    def test_score_value_path_zero_for_unrelated(self) -> None:
        score = score_value_path("completelydifferent", "deployments.*.replicas", "")
        self.assertEqual(score, 0)


class SchemaIndexerTest(unittest.TestCase):
    def test_indexes_simple_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "replicas": {"type": "integer", "description": "Count.", "default": 1},
                "image": {"type": "string"},
            },
            "required": ["image"],
        }
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("replicas", paths)
        self.assertIn("image", paths)

    def test_marks_required_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        entries = SchemaIndexer(schema).build()
        name_entry = next(e for e in entries if e.path == "name")
        self.assertTrue(name_entry.required)

    def test_resolves_inline_ref(self) -> None:
        schema = {
            "$defs": {
                "ResourceSpec": {
                    "type": "object",
                    "properties": {
                        "cpu": {"type": "string", "description": "CPU request."}
                    },
                }
            },
            "type": "object",
            "properties": {"resources": {"$ref": "#/$defs/ResourceSpec"}},
        }
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("resources", paths)
        self.assertIn("resources.cpu", paths)

    def test_indexes_additional_properties_wildcard(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "deployments": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {"replicas": {"type": "integer"}},
                    },
                }
            },
        }
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("deployments.*.replicas", paths)

    def test_indexes_array_items(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "hosts": {
                    "type": "array",
                    "items": {"type": "string", "description": "Hostname."},
                }
            },
        }
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("hosts", paths)
        # Array items path uses compact notation without dot: "hosts[]"
        self.assertIn("hosts[]", paths)

    def test_handles_circular_ref_gracefully(self) -> None:
        schema = {
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/$defs/Node"},
                        "name": {"type": "string"},
                    },
                }
            },
            "type": "object",
            "properties": {"root": {"$ref": "#/$defs/Node"}},
        }
        # Should not raise RecursionError
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("root", paths)

    def test_empty_schema_returns_empty_entries(self) -> None:
        entries = SchemaIndexer({}).build()
        self.assertEqual(entries, [])

    def test_handles_allof_combiner(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "allOf": [
                        {"type": "object", "properties": {"key": {"type": "string"}}},
                    ]
                }
            },
        }
        entries = SchemaIndexer(schema).build()
        paths = {e.path for e in entries}
        self.assertIn("config.key", paths)
