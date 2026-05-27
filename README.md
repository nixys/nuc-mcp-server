# nuc-chart-mcp

Python MCP server for [nxs-universal-chart](https://github.com/nixys/nxs-universal-chart) and all its declared dependency charts.

The server works with a local chart checkout, a remote Git repository, or an OCI registry artifact. MCP clients can query chart documentation, explain values paths, validate configurations, and render manifests without installing the chart sources manually.

---

## Contents

- [Features](#features)
- [Supported Charts](#supported-charts)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [MCP Tools](#mcp-tools)
- [MCP Resources](#mcp-resources)
- [Running Locally (Python)](#running-locally-python)
- [Docker](#docker)
- [Docker Compose](#docker-compose)
- [Kubernetes](#kubernetes)
- [Client Configuration](#client-configuration)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Features

- Builds a catalog for the root chart and every dependency declared in `Chart.yaml`
- Shows chart metadata, supported Kubernetes resources, values model, and dependency conditions
- Full-text search across `README.md`, `docs/`, `values.yaml`, `values.schema.json`, and templates
- Explains values paths using `values.schema.json`
- Validates `values.yaml` against JSON Schema
- Renders charts with `helm template`
- Serves MCP over `stdio` or HTTP at `/mcp`

---

## Supported Charts

The server indexes `nxs-universal-chart` (v3.0.21+) and its declared dependencies:

| Chart | Purpose | Enable condition |
|-------|---------|----------------|
| `nuc-traefik` | Traefik ingress controller | `nuc-traefik.enabled` |
| `nuc-certificates` | cert-manager Issuers / Certificates | `nuc-certificates.enabled` |
| `nuc-istio` | Service mesh (gateways, virtual services) | `nuc-istio.enabled` |
| `nuc-fluxcd` | GitOps with Flux CD | `nuc-fluxcd.enabled` |
| `nuc-knative` | Knative Serving / Eventing | `nuc-knative.enabled` |
| `nuc-kserve` | Model serving with KServe | `nuc-kserve.enabled` |
| `nuc-kube-prometheus-stack` | Prometheus + Grafana monitoring | `nuc-kube-prometheus-stack.enabled` |
| `nuc-native-gateway` | Kubernetes Gateway API | `nuc-native-gateway.enabled` |
| `nuc-victoria-metrics` | VictoriaMetrics TSDB | `nuc-victoria-metrics.enabled` |
| `nuc-vault-secret-operator` | Vault Secret Operator | `nuc-vault-secret-operator.enabled` |
| `nuc-keda` | Event-driven autoscaling | `nuc-keda.enabled` |
| `nuc-cloudnativepg` | CloudNativePG (PostgreSQL operator) | `nuc-cloudnativepg.enabled` |
| `nuc-mysql-percona-operator` | Percona MySQL Operator | `nuc-mysql-percona-operator.enabled` |
| `nuc-rabbitmq` | RabbitMQ Cluster Operator | `nuc-rabbitmq.enabled` |
| `nuc-clickhouse` | ClickHouse Operator | `nuc-clickhouse.enabled` |
| `nuc-elk` | Elastic Stack (ECK) | `nuc-elk.enabled` |
| `nuc-external-secrets` | External Secrets Operator | `nuc-external-secrets.enabled` |
| `nuc-mongodb-percona-operator` | Percona MongoDB Operator | `nuc-mongodb-percona-operator.enabled` |
| `nuc-envoy-gateway` | Envoy Gateway | `global.nuc-envoy-gateway.enabled` |
| `nuc-valkey` | Valkey (Redis-compatible cache) | `nuc-valkey.enabled` |
| `nuc-keycloak-operator` | Keycloak Operator | `nuc-keycloak-operator.enabled` |
| `nuc-strimzi-kafka-operator` | Strimzi Kafka Operator | `nuc-strimzi-kafka-operator.enabled` |

Dependency charts available locally (when `--chart-search-root` points to their parent directory) are indexed in full. The rest are pulled on demand via `helm pull` from the OCI registry.

---

## Quick Start

The fastest way to run the server locally is with Docker Compose. It clones `nxs-universal-chart` from GitHub on first start and caches the result.

```bash
cp .env.example .env        # adjust NUC_HTTP_BEARER_TOKEN if needed
docker compose up --build
```

The MCP endpoint is available at `http://localhost:8080/mcp`.

Verify the server is healthy:

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz
```

---

## Configuration

All settings are controlled by environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `NUC_ROOT_CHART_DIR` | — | **Priority 1.** Absolute path to a local `nxs-universal-chart` checkout. |
| `NUC_ROOT_CHART_OCI_REF` | — | **Priority 2.** OCI ref, e.g. `oci://registry.nixys.ru/nuc/nxs-universal-chart`. |
| `NUC_ROOT_CHART_OCI_VERSION` | — | Chart version for OCI pull (required when OCI_REF is set). |
| `NUC_ROOT_CHART_GIT_URL` | `https://github.com/nixys/nxs-universal-chart.git` | **Priority 3.** Git URL to clone when no local path or OCI ref is set. |
| `NUC_ROOT_CHART_GIT_REF` | `main` | Git branch or tag for `NUC_ROOT_CHART_GIT_URL`. |
| `NUC_ROOT_CHART_SUBDIR` | — | Subdirectory inside the cloned repo that contains `Chart.yaml`. |
| `NUC_CHART_SEARCH_ROOTS` | — | Colon-separated list of directories where dependency chart repos are searched. |
| `NUC_REMOTE_CACHE_DIR` | system temp | Directory for caching cloned/pulled chart sources. |
| `NUC_TRANSPORT` | `stdio` | Transport mode: `stdio` or `http`. |
| `NUC_HTTP_BIND` | `127.0.0.1` | Bind address for HTTP transport. |
| `NUC_HTTP_PORT` | `8080` | Port for HTTP transport. |
| `NUC_HTTP_PATH` | `/mcp` | Path of the MCP HTTP endpoint. |
| `NUC_HTTP_BEARER_TOKEN` | — | Bearer token protecting the `/mcp` endpoint. Leave empty to disable. |
| `NUC_ALLOWED_ORIGINS` | — | Comma-separated allowed `Origin` header values. Use `*` to allow all. |

`NUC_CHART_SEARCH_ROOTS` uses the OS path separator. Example:

```bash
export NUC_CHART_SEARCH_ROOTS="/tmp/charts:/srv/extra-charts"
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_charts` | List the root chart and all declared dependency charts. |
| `get_chart_overview` | Metadata, supported resources, values model, and dependency notes for a chart. |
| `search_chart_docs` | Full-text search across README, docs, values, schema, and templates. |
| `explain_chart_value` | Explain a values path using `values.schema.json`. |
| `suggest_chart_for_resource` | Suggest which chart manages a given Kubernetes resource kind. |
| `validate_chart_values` | Validate `values.yaml` content against a chart's JSON Schema. |
| `render_chart` | Render a chart with `helm template` using resolved dependency charts. |

---

## MCP Resources

| URI | Description |
|-----|-------------|
| `chart://catalog` | Full chart catalog as JSON. |
| `chart://<chart>/overview` | Chart overview in Markdown. |
| `chart://<chart>/values-index` | Flattened values schema index as JSON. |
| `chart://<chart>/Chart.yaml` | Raw `Chart.yaml`. |
| `chart://<chart>/values.yaml` | Raw `values.yaml`. |
| `chart://<chart>/values.schema.json` | Raw `values.schema.json`. |
| `chart://<chart>/README.md` | Raw `README.md`. |
| `chart://<chart>/docs/<file>.md` | Any Markdown file in the `docs/` directory. |

---

## Running Locally (Python)

Install the package in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Or install dependencies only (without packaging):

```bash
pip install -r requirements.txt
```

Start with a local chart checkout:

```bash
nuc-chart-mcp \
  --root-chart-dir /tmp/nxs-universal-chart \
  --chart-search-root /tmp \
  --debug
```

Start with a remote Git repository:

```bash
nuc-chart-mcp \
  --root-chart-git-url https://github.com/nixys/nxs-universal-chart.git \
  --root-chart-git-ref main \
  --cache-dir /tmp/nuc-chart-mcp-cache
```

Start in HTTP mode:

```bash
nuc-chart-mcp \
  --transport http \
  --bind 0.0.0.0 \
  --port 8080 \
  --http-path /mcp \
  --allow-origin https://your-frontend.example.com
```

Run directly as a Python module:

```bash
python3 -m nuc_chart_mcp.server
```

---

## Docker

Build the image:

```bash
docker build -t nuc-chart-mcp:latest .
```

The image includes `git` and `helm`, runs as a non-root user, and starts in HTTP mode on port `8080` by default.

Default environment inside the container:

| Variable | Default value |
|----------|--------------|
| `NUC_ROOT_CHART_GIT_URL` | `https://github.com/nixys/nxs-universal-chart.git` |
| `NUC_ROOT_CHART_GIT_REF` | `main` |
| `NUC_REMOTE_CACHE_DIR` | `/tmp/nuc-chart-mcp-cache` |

Run with remote chart (no local sources required):

```bash
docker run --rm -p 8080:8080 \
  -e NUC_ROOT_CHART_GIT_URL=https://github.com/nixys/nxs-universal-chart.git \
  -e NUC_ROOT_CHART_GIT_REF=main \
  -e NUC_HTTP_BEARER_TOKEN=change-me \
  -e NUC_ALLOWED_ORIGINS='*' \
  nuc-chart-mcp:latest
```

Run with a local chart directory:

```bash
docker run --rm -p 8080:8080 \
  -v /tmp/nxs-universal-chart:/tmp/nxs-universal-chart:ro \
  -e NUC_ROOT_CHART_DIR=/tmp/nxs-universal-chart \
  nuc-chart-mcp:latest
```

---

## Docker Compose

Three chart source modes are available. Copy `.env.example` to `.env` and choose one:

**Mode A — GitHub (default, no extra config needed):**

```bash
cp .env.example .env
docker compose up --build
```

**Mode B — Local chart directory:**

Mount your local checkout and point the server to it:

```yaml
# Add to docker-compose.yaml → services.nuc-chart-mcp.volumes:
- /tmp/nxs-universal-chart:/tmp/nxs-universal-chart:ro
```

```bash
# Set in .env:
NUC_ROOT_CHART_DIR=/tmp/nxs-universal-chart
```

**Mode C — OCI registry:**

```bash
# Set in .env:
NUC_ROOT_CHART_OCI_REF=oci://registry.nixys.ru/nuc/nxs-universal-chart
NUC_ROOT_CHART_OCI_VERSION=3.0.21
```

After changing the mode, restart with:

```bash
docker compose up -d
```

The chart cache is stored in the `chart-cache` named volume and survives container restarts.

---

## Kubernetes

Ready-made manifests are in the `k8s/` directory:

- `k8s/namespace.yaml`
- `k8s/deployment.yaml`
- `k8s/service.yaml`
- `k8s/ingress.yaml`
- `k8s/secret.example.yaml`
- `k8s/kustomization.yaml`

Typical deploy sequence:

```bash
kubectl apply -f k8s/namespace.yaml

# Create the bearer token secret (replace with a real token)
kubectl -n nuc-chart-mcp create secret generic nuc-chart-mcp-auth \
  --from-literal=NUC_HTTP_BEARER_TOKEN=change-me-before-production

kubectl apply -k k8s
```

Before applying, update:

- Image in `k8s/deployment.yaml` → replace `registry.example.com/nuc-chart-mcp:latest`
- Domain in `k8s/ingress.yaml` → replace `mcp.example.com`
- Token in `k8s/secret.example.yaml` → replace `change-me-before-production`
- `NUC_ALLOWED_ORIGINS` in `k8s/deployment.yaml` → set real client origins

The MCP endpoint after deploy:

```
https://mcp.example.com/mcp
```

Minimal container spec:

```yaml
containers:
  - name: nuc-chart-mcp
    image: registry.example.com/nuc-chart-mcp:latest
    ports:
      - containerPort: 8080
    env:
      - name: NUC_ROOT_CHART_OCI_REF
        value: oci://registry.example.com/nxs-universal-chart
      - name: NUC_ROOT_CHART_OCI_VERSION
        value: "3.0.17"
      - name: NUC_HTTP_BEARER_TOKEN
        valueFrom:
          secretKeyRef:
            name: nuc-chart-mcp-auth
            key: NUC_HTTP_BEARER_TOKEN
      - name: NUC_ALLOWED_ORIGINS
        value: "https://your-ui.example.com"
      - name: NUC_REMOTE_CACHE_DIR
        value: /tmp/nuc-chart-mcp-cache
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 30
    readinessProbe:
      httpGet:
        path: /readyz
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
    resources:
      requests:
        cpu: 50m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 512Mi
```

### Verify after deploy

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: nuc-chart-mcp-auth
  namespace: nuc-chart-mcp
spec:
  type: kv-v2
  mount: secret
  path: apps/nuc-chart-mcp/auth
  destination:
    name: nuc-chart-mcp-auth
    create: true
  refreshAfter: 1h
```

Port-forward for local smoke test:

```bash
kubectl -n nuc-chart-mcp port-forward svc/nuc-chart-mcp 8080:80
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/readyz
```

---

## Client Configuration

### Claude Code — stdio

Add to `~/.claude.json` or `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "nuc-chart": {
      "command": "python3",
      "args": ["-m", "nuc_chart_mcp.server"],
      "env": {
        "NUC_ROOT_CHART_GIT_URL": "https://github.com/nixys/nxs-universal-chart.git",
        "NUC_ROOT_CHART_GIT_REF": "main",
        "NUC_REMOTE_CACHE_DIR": "/tmp/nuc-chart-mcp-cache"
      }
    }
  }
}
```

### Claude Code — HTTP

Add to `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "nuc-chart": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${NUC_HTTP_BEARER_TOKEN}"
      }
    }
  }
}
```

Or register via CLI:

```bash
claude mcp add --transport http nuc-chart https://mcp.example.com/mcp
```

### OpenAI Responses API

```bash
curl https://api.openai.com/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-4o",
    "input": "Use the nuc-chart MCP server and list available charts.",
    "tools": [
      {
        "type": "mcp",
        "server_label": "nuc-chart",
        "server_url": "https://mcp.example.com/mcp",
        "headers": { "Authorization": "Bearer <token>" },
        "require_approval": "never"
      }
    ]
  }'
```

### HTTP — manual test

Initialize a session:

```bash
curl -i http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

Call a tool:

```bash
curl -i http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_charts","arguments":{}}}'
```

With a bearer token:

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $NUC_HTTP_BEARER_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

If the token is stored in a Kubernetes Secret (base64-encoded), decode it first:

```bash
TOKEN="$(kubectl -n nuc-chart-mcp get secret nuc-chart-mcp-auth \
  -o jsonpath='{.data.NUC_HTTP_BEARER_TOKEN}' | base64 -d)"
```

---

## Testing

Tests cover: chart discovery, search, value explanation, schema validation, HTTP transport (healthz, auth, CORS, batch JSON-RPC), schema indexing (`$ref` resolution, circular-ref protection), and helper utilities.

Run with a virtual environment (recommended — validation tests require `jsonschema`):

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python3 -m unittest discover -s tests -v
```

Without a venv (if `jsonschema` is already installed system-wide):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected result: **85 tests, 0 failures**. Docker and Helm are not required.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | Missing or wrong bearer token | Pass `Authorization: Bearer <token>` header |
| `403 Forbidden` | `Origin` header not in `NUC_ALLOWED_ORIGINS` | Add the origin or set `NUC_ALLOWED_ORIGINS=*` |
| `405 Method Not Allowed` on GET `/mcp` | Expected — `/mcp` only accepts POST | Use POST |
| Container fails to start | No chart source configured | Set `NUC_ROOT_CHART_GIT_URL` or mount a local chart |
| `helm pull` fails | Registry authentication required | Pass registry credentials in the container environment |
| Slow startup | Cloning large Git repo | Pre-warm the cache or use a local mount / OCI pull instead |

---

## Notes

- The root chart is rendered from a temporary staged copy; resolved dependency charts are symlinked into its `charts/` directory.
- In remote mode the server clones the root chart into the cache directory and pulls dependencies via `helm pull`.
- Library charts (e.g. `nuc-common`) can be indexed and searched but cannot be rendered directly.
- If a dependency chart cannot be pulled from its declared repository, the server still exposes its declared metadata with an error note in the summary.
