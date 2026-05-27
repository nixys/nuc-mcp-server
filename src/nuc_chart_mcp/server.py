from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from . import __version__
from .catalog import (
    CatalogError,
    ChartCatalog,
    ResourceNotFoundError,
    ToolExecutionError,
)


logger = logging.getLogger("nuc_chart_mcp")


@dataclass
class JsonRpcError(Exception):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class HttpTransportConfig:
    bind: str
    port: int
    mcp_path: str
    allowed_origins: Tuple[str, ...]
    bearer_token: str = ""

    @property
    def normalized_mcp_path(self) -> str:
        if not self.mcp_path:
            return "/mcp"
        return self.mcp_path if self.mcp_path.startswith("/") else f"/{self.mcp_path}"


class NucChartMCPServer:
    def __init__(
        self,
        catalog: ChartCatalog,
        server_name: str = "nuc-chart-mcp",
        catalog_factory: Optional[Callable[[], ChartCatalog]] = None,
        catalog_ttl_seconds: int = 0,
    ) -> None:
        self.catalog = catalog
        self.server_name = server_name
        self._catalog_factory = catalog_factory
        self._catalog_ttl_seconds = catalog_ttl_seconds
        self._catalog_loaded_at = time.monotonic()
        self._catalog_lock = threading.Lock()
        self.initialized = False

    def _reload_catalog(self) -> str:
        if self._catalog_factory is None:
            raise ToolExecutionError(
                "Catalog factory is not configured; reload is unavailable."
            )
        # Build new catalog outside the lock so requests can continue during refresh
        new_catalog = self._catalog_factory()
        with self._catalog_lock:
            self.catalog = new_catalog
            self._catalog_loaded_at = time.monotonic()
        n = len(new_catalog.chart_names())
        return f"Catalog reloaded: {new_catalog.root_chart_name}, {n} chart{'s' if n != 1 else ''}."

    def _maybe_refresh_catalog(self) -> None:
        if self._catalog_ttl_seconds <= 0 or self._catalog_factory is None:
            return
        if time.monotonic() - self._catalog_loaded_at >= self._catalog_ttl_seconds:
            try:
                self._reload_catalog()
                logger.info(
                    "Catalog auto-refreshed (TTL=%ds)", self._catalog_ttl_seconds
                )
            except Exception:
                logger.exception("Catalog auto-refresh failed")

    def handle_request(
        self, method: str, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        self._maybe_refresh_catalog()
        params = params or {}
        if method == "initialize":
            self.initialized = True
            return {
                "protocolVersion": params.get("protocolVersion") or "2025-03-26",
                "capabilities": {
                    "resources": {"listChanged": False},
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": self.server_name,
                    "version": __version__,
                },
                "instructions": (
                    "Use the tools to inspect nxs-universal-chart, search documentation, "
                    "explain values paths, validate values, and render manifests."
                ),
            }
        if method == "ping":
            return {}
        if method == "resources/list":
            cursor = params.get("cursor")
            result = self.catalog.list_resources(
                cursor=cursor if isinstance(cursor, str) else None
            )
            return result
        if method == "resources/read":
            uri = require_string(params, "uri")
            resource = self.catalog.read_resource(uri)
            return {"contents": [resource]}
        if method == "tools/list":
            return {"tools": self._tools()}
        if method == "tools/call":
            name = require_string(params, "name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise JsonRpcError(-32602, "`arguments` must be an object.")
            return self._call_tool(name, arguments)
        raise JsonRpcError(-32601, f"Method not found: {method}")

    def handle_notification(
        self, method: str, params: Optional[Dict[str, Any]]
    ) -> None:
        if method == "notifications/initialized":
            self.initialized = True
            return
        logger.debug("Ignoring notification %s with params=%s", method, params)

    def process_message(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict):
            return error_payload(
                None, JsonRpcError(-32600, "Invalid request: expected a JSON object.")
            )

        message_id = message.get("id")
        method = message.get("method")
        params = message.get("params")

        if method is None:
            if "result" in message or "error" in message:
                logger.debug("Ignoring client-side JSON-RPC response: %s", message)
                return None
            return error_payload(
                message_id, JsonRpcError(-32600, "Invalid request: missing method.")
            )

        try:
            if message_id is None:
                self.handle_notification(
                    method, params if isinstance(params, dict) else None
                )
                return None
            result = self.handle_request(
                method, params if isinstance(params, dict) else None
            )
            return result_payload(message_id, result)
        except JsonRpcError as exc:
            return error_payload(message_id, exc)
        except ResourceNotFoundError as exc:
            return error_payload(message_id, JsonRpcError(-32002, str(exc)))
        except Exception as exc:  # pragma: no cover - defensive protocol guard
            logger.exception("Unhandled server error")
            return error_payload(message_id, JsonRpcError(-32603, str(exc)))

    def process_payload(self, payload: Any) -> Tuple[HTTPStatus, Optional[Any]]:
        if isinstance(payload, list):
            if not payload:
                return (
                    HTTPStatus.BAD_REQUEST,
                    error_payload(
                        None,
                        JsonRpcError(
                            -32600, "Invalid request: batch payload must not be empty."
                        ),
                    ),
                )
            responses: list[Dict[str, Any]] = []
            for message in payload:
                response = self.process_message(message)
                if response is not None:
                    responses.append(response)
            if not responses:
                return HTTPStatus.ACCEPTED, None
            if len(responses) == 1:
                return HTTPStatus.OK, responses[0]
            return HTTPStatus.OK, responses

        if isinstance(payload, dict):
            response = self.process_message(payload)
            if response is None:
                return HTTPStatus.ACCEPTED, None
            return HTTPStatus.OK, response

        return (
            HTTPStatus.BAD_REQUEST,
            error_payload(
                None,
                JsonRpcError(
                    -32600, "Invalid request: expected an object or a non-empty array."
                ),
            ),
        )

    def _tools(self) -> Sequence[Dict[str, Any]]:
        return [
            {
                "name": "list_charts",
                "description": "List the root chart and dependency charts declared in Chart.yaml.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
            },
            {
                "name": "get_chart_overview",
                "description": "Get metadata, supported resources, values model, and dependency notes for a chart.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "chart": {
                            "type": "string",
                            "description": "Chart name. Defaults to the root chart.",
                        }
                    },
                },
            },
            {
                "name": "search_chart_docs",
                "description": "Search README, docs, values, schema, and templates across the indexed charts.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "chart": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                },
            },
            {
                "name": "explain_chart_value",
                "description": "Explain a values path using values.schema.json from the root chart or a dependency chart.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "chart": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                },
            },
            {
                "name": "suggest_chart_for_resource",
                "description": "Suggest which chart is responsible for a Kubernetes resource kind or topic.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["resource"],
                    "properties": {
                        "resource": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                },
            },
            {
                "name": "validate_chart_values",
                "description": "Validate YAML values against a chart values.schema.json file.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["values_yaml"],
                    "properties": {
                        "chart": {"type": "string"},
                        "values_yaml": {"type": "string"},
                    },
                },
            },
            {
                "name": "render_chart",
                "description": "Render a chart with Helm template using the resolved dependency charts.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["values_yaml"],
                    "properties": {
                        "chart": {"type": "string"},
                        "values_yaml": {"type": "string"},
                        "release_name": {"type": "string"},
                        "namespace": {"type": "string"},
                        "include_manifest": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "reload_catalog",
                "description": (
                    "Reload the chart catalog from its configured source (OCI registry, Git repository, or local path). "
                    "Call after deploying a new chart version to pick up the latest values schema and documentation "
                    "without restarting the server."
                ),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
            },
        ]

    def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "list_charts":
                text = self.catalog.format_chart_list()
            elif name == "get_chart_overview":
                text = self.catalog.format_chart_overview(arguments.get("chart"))
            elif name == "search_chart_docs":
                text = self.catalog.format_search_results(
                    query=require_string(arguments, "query"),
                    chart_name=optional_string(arguments, "chart"),
                    limit=optional_int(arguments, "limit", 8),
                )
            elif name == "explain_chart_value":
                text = self.catalog.format_value_explanation(
                    path=require_string(arguments, "path"),
                    chart_name=optional_string(arguments, "chart"),
                    limit=optional_int(arguments, "limit", 8),
                )
            elif name == "suggest_chart_for_resource":
                text = self.catalog.format_resource_suggestions(
                    resource=require_string(arguments, "resource"),
                    limit=optional_int(arguments, "limit", 6),
                )
            elif name == "validate_chart_values":
                text = self.catalog.format_validation_report(
                    chart_name=optional_string(arguments, "chart"),
                    values_yaml=require_string(arguments, "values_yaml"),
                )
            elif name == "render_chart":
                text = self.catalog.format_render_report(
                    chart_name=optional_string(arguments, "chart"),
                    values_yaml=require_string(arguments, "values_yaml"),
                    release_name=optional_string(arguments, "release_name")
                    or "mcp-preview",
                    namespace=optional_string(arguments, "namespace") or "default",
                    include_manifest=optional_bool(
                        arguments, "include_manifest", False
                    ),
                )
            elif name == "reload_catalog":
                text = self._reload_catalog()
            else:
                raise JsonRpcError(-32601, f"Unknown tool: {name}")
            return {"content": [{"type": "text", "text": text}]}
        except (CatalogError, ToolExecutionError) as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}


class MCPHTTPTransportServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        app: NucChartMCPServer,
        config: HttpTransportConfig,
    ) -> None:
        super().__init__(server_address, MCPHTTPRequestHandler)
        self.app = app
        self.config = config


class MCPHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "nuc-chart-mcp"
    sys_version = ""

    @property
    def app(self) -> NucChartMCPServer:
        return self.server.app  # type: ignore[attr-defined]

    @property
    def config(self) -> HttpTransportConfig:
        return self.server.config  # type: ignore[attr-defined]

    def do_OPTIONS(self) -> None:
        path = self._request_path()
        if path != self.config.normalized_mcp_path:
            self._send_text(HTTPStatus.NOT_FOUND, "Not found.\n")
            return
        if not self._check_origin():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.send_header("Allow", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Accept, Authorization, Content-Type, Last-Event-ID, Mcp-Session-Id",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        path = self._request_path()
        if not self._check_origin():
            return
        if path in {"/healthz", "/readyz"}:
            self._send_text(HTTPStatus.OK, "ok\n")
            return
        if path == "/":
            self._send_json(
                HTTPStatus.OK,
                {
                    "name": self.app.server_name,
                    "version": __version__,
                    "transport": "streamable-http",
                    "mcpPath": self.config.normalized_mcp_path,
                    "healthz": "/healthz",
                    "readyz": "/readyz",
                },
            )
            return
        if path != self.config.normalized_mcp_path:
            self._send_text(HTTPStatus.NOT_FOUND, "Not found.\n")
            return
        if not self._check_auth():
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._send_common_headers()
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_DELETE(self) -> None:
        path = self._request_path()
        if path != self.config.normalized_mcp_path:
            self._send_text(HTTPStatus.NOT_FOUND, "Not found.\n")
            return
        if not self._check_origin():
            return
        if not self._check_auth():
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._send_common_headers()
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:
        path = self._request_path()
        if path != self.config.normalized_mcp_path:
            self._send_text(HTTPStatus.NOT_FOUND, "Not found.\n")
            return
        if not self._check_origin():
            return
        if not self._check_auth():
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        _MAX_BODY = 10 * 1024 * 1024  # 10 MB
        if content_length > _MAX_BODY:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                error_payload(None, JsonRpcError(-32600, "Request body too large.")),
            )
            return
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                error_payload(
                    None,
                    JsonRpcError(
                        -32700, "Parse error: request body is not valid JSON."
                    ),
                ),
            )
            return

        status, response_payload = self.app.process_payload(payload)
        if response_payload is None:
            self.send_response(status)
            self._send_common_headers()
            self.end_headers()
            return
        self._send_json(status, response_payload)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _request_path(self) -> str:
        return urlsplit(self.path).path or "/"

    def _check_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if self._origin_allowed(origin):
            return True
        self._send_text(HTTPStatus.FORBIDDEN, "Origin is not allowed.\n")
        return False

    def _origin_allowed(self, origin: str) -> bool:
        allowed = self.config.allowed_origins
        if not allowed:
            return False
        return "*" in allowed or origin in allowed

    def _check_auth(self) -> bool:
        token = self.config.bearer_token
        if not token:
            return True
        provided = self.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        # Constant-time comparison to prevent timing-based token enumeration
        if hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self._send_common_headers()
        self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        return False

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: HTTPStatus, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed(origin):
            self.send_header(
                "Access-Control-Allow-Origin",
                "*" if "*" in self.config.allowed_origins else origin,
            )
            self.send_header("Vary", "Origin")


def require_string(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JsonRpcError(-32602, f"`{key}` must be a non-empty string.")
    return value


def optional_string(payload: Dict[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise JsonRpcError(-32602, f"`{key}` must be a string.")
    return value


def optional_int(payload: Dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise JsonRpcError(-32602, f"`{key}` must be an integer.")
    return value


def optional_bool(payload: Dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise JsonRpcError(-32602, f"`{key}` must be a boolean.")
    return value


def read_message(stdin: Any) -> Optional[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None
    raw_body = stdin.read(content_length)
    return json.loads(raw_body.decode("utf-8"))


def write_message(stdout: Any, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stdout.write(header)
    stdout.write(body)
    stdout.flush()


def error_payload(message_id: Any, error: JsonRpcError) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }
    if error.data is not None:
        payload["error"]["data"] = error.data
    return payload


def result_payload(message_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def serve_stdio(server: NucChartMCPServer) -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            message = read_message(stdin)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("JSON parse error on stdin: %s", exc)
            write_message(
                stdout, error_payload(None, JsonRpcError(-32700, f"Parse error: {exc}"))
            )
            continue
        if message is None:
            return 0
        logger.debug("Received stdio message: %s", message)
        response = server.process_message(message)
        if response is not None:
            write_message(stdout, response)


def build_http_server(
    server: NucChartMCPServer, config: HttpTransportConfig
) -> MCPHTTPTransportServer:
    return MCPHTTPTransportServer((config.bind, config.port), server, config)


def serve_http(server: NucChartMCPServer, config: HttpTransportConfig) -> int:
    httpd = build_http_server(server, config)
    logger.warning(
        "Serving MCP over HTTP on %s:%s%s",
        config.bind,
        httpd.server_address[1],
        config.normalized_mcp_path,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.warning("HTTP server interrupted, shutting down.")
        return 0
    finally:
        httpd.server_close()


def parse_allowed_origins(cli_values: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if cli_values:
        return tuple(item for item in cli_values if item)
    env_value = os.environ.get("NUC_ALLOWED_ORIGINS", "")
    if not env_value:
        return tuple()
    return tuple(item.strip() for item in env_value.split(",") if item.strip())


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MCP server for nxs-universal-chart and dependency charts."
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.environ.get("NUC_TRANSPORT", "stdio"),
    )
    parser.add_argument(
        "--root-chart-dir", type=Path, help="Path to nxs-universal-chart."
    )
    parser.add_argument(
        "--root-chart-git-url",
        help="Git URL used to clone the root chart when no local path is mounted.",
    )
    parser.add_argument(
        "--root-chart-git-ref",
        help="Git ref, branch, or tag used for the remote root chart.",
    )
    parser.add_argument(
        "--root-chart-subdir",
        help="Optional subdirectory inside the cloned git repository that contains Chart.yaml.",
    )
    parser.add_argument(
        "--chart-search-root",
        action="append",
        type=Path,
        dest="chart_search_roots",
        help="Additional parent directory where dependency chart repos can be discovered.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Directory used to cache cloned and pulled remote chart sources.",
    )
    parser.add_argument(
        "--server-name",
        default="nuc-chart-mcp",
        help="Server name shown to the MCP client.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging to stderr."
    )
    parser.add_argument(
        "--bind",
        default=os.environ.get("NUC_HTTP_BIND", "127.0.0.1"),
        help="Bind address for HTTP transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("NUC_HTTP_PORT", "8080")),
        help="Port for HTTP transport.",
    )
    parser.add_argument(
        "--http-path",
        default=os.environ.get("NUC_HTTP_PATH", "/mcp"),
        help="Path for the MCP HTTP endpoint.",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        dest="allowed_origins",
        help="Allowed Origin header value for HTTP transport. Repeat to allow multiple origins.",
    )
    parser.add_argument(
        "--catalog-ttl",
        type=int,
        default=int(os.environ.get("NUC_CATALOG_TTL_SECONDS", "0")),
        dest="catalog_ttl",
        help="Automatically reload the catalog every N seconds (0 = disabled). Also set via NUC_CATALOG_TTL_SECONDS.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    def make_catalog() -> ChartCatalog:
        return ChartCatalog.discover(
            root_chart_dir=args.root_chart_dir,
            search_roots=args.chart_search_roots,
            root_chart_git_url=args.root_chart_git_url,
            root_chart_git_ref=args.root_chart_git_ref,
            root_chart_subdir=args.root_chart_subdir,
            cache_dir=args.cache_dir,
        )

    catalog = make_catalog()
    server = NucChartMCPServer(
        catalog=catalog,
        server_name=args.server_name,
        catalog_factory=make_catalog,
        catalog_ttl_seconds=args.catalog_ttl,
    )
    if args.transport == "http":
        http_config = HttpTransportConfig(
            bind=args.bind,
            port=args.port,
            mcp_path=args.http_path,
            allowed_origins=parse_allowed_origins(args.allowed_origins),
            bearer_token=os.environ.get("NUC_HTTP_BEARER_TOKEN", ""),
        )
        return serve_http(server, http_config)
    return serve_stdio(server)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
