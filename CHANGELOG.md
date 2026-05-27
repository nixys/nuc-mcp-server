# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.0.2] - 2026-05-27

### Added
- GitHub Actions CI pipeline: `lint` (ruff format + check), `test` (pytest matrix Python 3.9 / 3.11 / 3.12 with coverage), `security` (bandit `-ll -ii` + pip-audit), `docker-build` (Dockerfile validation)
- `docs/nuc-argocd.md` — best-practice guide for the `nuc-argocd` subchart (Application, ApplicationSet, AppProject)
- Tests for previously untested code paths: HTTP 413 body-size limit, `reload_catalog` tool (with and without factory), stdio `JSONDecodeError` recovery — test count grows from 85 to 89

### Changed
- Pinned `NUC_ROOT_CHART_GIT_REF` to `v3.1.0` in Dockerfile, `.env.example`, `docker-compose.yaml`, and `k8s/deployment.yaml`
- Updated `NUC_ROOT_CHART_OCI_VERSION` to `3.1.0` in `.env.example` and `docker-compose.yaml`
- GitHub Actions steps now pinned to full commit SHA (supply chain hardening per SLSA)
- `docs/nuc-native-gateway.md` updated for chart v1.0.6: added `BackendTLSPolicies` (end-to-end mTLS), `ListenerSets` (Gateway API v1.3+), `GatewayClasses`
- `docs/nuc-external-secrets.md` updated for chart v1.1.0: added generator resources (`Password`, `VaultDynamicSecret`, `ClusterGenerator`, ECR/GCR/ACR/GitHub token generators) and `sourceRef.generatorRef` usage

### Fixed
- `NameError: name 'cls'` in `ChartCatalog.resolve_root_chart_dir()` — `cls` is not defined in a `@staticmethod`; replaced with `ChartCatalog.resolve_cache_dir(None)`
- `test_resource_listing_includes_catalog_and_overviews` was iterating `list_resources()` as a list; the method returns `{"resources": [...]}` after pagination was added
- stdio transport: unhandled `JSONDecodeError` / `UnicodeDecodeError` would crash the server loop; now caught and returned as JSON-RPC `-32700` parse error, allowing the session to continue
- HTTP transport: missing body-size guard allowed arbitrarily large payloads; requests with `Content-Length > 10 MB` now receive HTTP 413 before the body is read
- `k8s/deployment.yaml`: enabled `readOnlyRootFilesystem: true` with a dedicated `emptyDir` volume at `/tmp` (covers both the catalog cache and Helm temp files); added `initialDelaySeconds` to readiness and liveness probes to accommodate the git-clone startup time; added `NUC_CATALOG_TTL_SECONDS` env var
- `k8s/ingress.yaml`: added `tls:` section (was missing entirely)

### Security
- Helm binary download in `Dockerfile` now verified with SHA-256: the `.tar.gz.sha256sum` file is fetched from `get.helm.sh` and checked with `sha256sum -c` before `tar` is invoked

## [v1.0.0] - 2026-05-25

### Added
- Comprehensive test suite — 85 tests across `tests/test_catalog.py` and `tests/test_server.py`, covering catalog discovery, schema indexing, all MCP tools, HTTP transport (auth, CORS, batch, health endpoints), and stdio transport
- `docker-compose.yaml` for local development with all supported chart sources (local path, OCI, git)
- `.env.example` documenting all environment variables
- Documentation for 24 subcharts in `docs/`:
  - Root chart overview: `root-chart.md`
  - Databases: `nuc-clickhouse`, `nuc-cloudnativepg`, `nuc-mongodb-percona-operator`, `nuc-mysql-percona-operator`, `nuc-valkey`
  - Network & Gateway: `nuc-certificates`, `nuc-envoy-gateway`, `nuc-istio`, `nuc-native-gateway`, `nuc-traefik`
  - Observability: `nuc-elk`, `nuc-kube-prometheus-stack`, `nuc-victoria-metrics`
  - Platform: `nuc-fluxcd`, `nuc-keycloak-operator`, `nuc-knative`, `nuc-kserve`
  - Messaging & Streaming: `nuc-rabbitmq`, `nuc-strimzi-kafka-operator`
  - Autoscaling: `nuc-keda`
  - Secrets: `nuc-external-secrets`, `nuc-vault-secret-operator`
- `reload_catalog` MCP tool — hot-reload the chart catalog from its configured source without restarting the server
- Catalog TTL auto-refresh (`NUC_CATALOG_TTL_SECONDS`): the server periodically rebuilds the catalog in the background
- Bearer token authentication with constant-time comparison (`hmac.compare_digest`) to prevent timing-based token enumeration
- CORS support: configurable allowed origins via `NUC_ALLOWED_ORIGINS` env var or `--allow-origin` CLI flag
- Batch JSON-RPC request support (array of requests in a single HTTP POST)
- MCP Resources API: `resources/list` (with cursor-based pagination) and `resources/read`
- HTTP health endpoints: `GET /healthz` and `GET /readyz`
- Server metadata endpoint: `GET /` returns name, version, and MCP path as JSON
- GitLab CI pipeline (`.gitlab-ci.yml`)
- `docs/README.md` — documentation index

### Changed
- `README.md` rewritten with full installation, configuration, tool reference, and deployment guides
- `_load_values_yaml()` extracted as a shared helper for consistent YAML parsing across catalog methods
- `catalog.py` restructured with explicit error hierarchy: `CatalogError`, `ChartNotFoundError`, `ResourceNotFoundError`, `ToolExecutionError`

## [v0.1.0] - 2026-04-29

### Added
- Initial MCP server implementation supporting both **stdio** (JSON-RPC over stdin/stdout) and **HTTP** (`POST /mcp`, streamable-HTTP transport) protocols
- `ChartCatalog` — dynamic discovery of root chart and dependency subcharts from three sources:
  - Local filesystem path (`NUC_ROOT_CHART_DIR`)
  - OCI registry (`NUC_ROOT_CHART_OCI_REF` + `NUC_ROOT_CHART_OCI_VERSION`)
  - Git repository (`NUC_ROOT_CHART_GIT_URL` + `NUC_ROOT_CHART_GIT_REF`) with SHA-keyed local cache
- `SchemaIndexer` — recursive JSON Schema traversal with circular-reference protection (`child_ref_stack`) and configurable depth limit (`_SCHEMA_MAX_DEPTH = 24`)
- Seven MCP tools exposed to AI agents:
  - `list_charts` — enumerate root and dependency charts with descriptions
  - `explain_chart_value` — resolve a dot-path (e.g. `nuc-istio.gateway.enabled`) to its schema definition, type, default, and description
  - `get_chart_overview` — return the chart's README as Markdown
  - `search_chart_docs` — full-text search across all chart documentation
  - `suggest_chart_for_resource` — map a Kubernetes resource kind to the subchart that manages it
  - `validate_chart_values` — validate a YAML values blob against the chart's JSON Schema
  - `render_chart` — run `helm template` and return rendered manifests (requires Helm binary)
- 3-stage `Dockerfile`: Python wheel builder → Helm binary stage → minimal runtime image (non-root user `nuc`, port 8080)
- Kubernetes manifests in `k8s/`: `namespace.yaml`, `deployment.yaml`, `service.yaml`, `ingress.yaml`, `secret.example.yaml`, `kustomization.yaml`
- `pyproject.toml` with `nuc-chart-mcp` entry point and Python ≥ 3.9 requirement
- `requirements.txt`: `PyYAML >= 5.3`, `jsonschema >= 4.19`
