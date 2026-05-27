from __future__ import annotations

import json
import tempfile
import textwrap
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from nuc_chart_mcp.catalog import ChartCatalog
from nuc_chart_mcp.server import (
    HttpTransportConfig,
    NucChartMCPServer,
    build_http_server,
    parse_allowed_origins,
)


class ServerToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        workspace = Path(self.temp_dir.name)
        root_chart = workspace / "nxs-universal-chart"
        dependency_chart = workspace / "nuc-native-gateway"

        root_chart.mkdir(parents=True)
        dependency_chart.mkdir(parents=True)

        (root_chart / "Chart.yaml").write_text(
            textwrap.dedent(
                """\
                apiVersion: v2
                name: nxs-universal-chart
                description: Root chart
                type: application
                version: 1.0.0
                dependencies:
                  - name: nuc-native-gateway
                    version: 1.0.0
                    repository: oci://example.local/charts
                    condition: nuc-native-gateway.enabled
                """
            ),
            encoding="utf-8",
        )
        (root_chart / "values.yaml").write_text(
            "nuc-native-gateway:\n  enabled: false\n", encoding="utf-8"
        )
        (root_chart / "values.schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {
                        "nuc-native-gateway": {
                            "type": "object",
                            "properties": {
                                "enabled": {
                                    "type": "boolean",
                                    "description": "Enable dependency chart.",
                                    "default": False,
                                }
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (root_chart / "README.md").write_text(
            "# Root\n\n## Supported Resources\n\n- `Deployment`\n", encoding="utf-8"
        )

        (dependency_chart / "Chart.yaml").write_text(
            textwrap.dedent(
                """\
                apiVersion: v2
                name: nuc-native-gateway
                description: Gateway chart
                type: application
                version: 1.0.0
                """
            ),
            encoding="utf-8",
        )
        (dependency_chart / "values.yaml").write_text(
            "enabled: true\n", encoding="utf-8"
        )
        (dependency_chart / "values.schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "Enable rendering for this subchart.",
                            "default": True,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (dependency_chart / "README.md").write_text(
            "# Gateway\n\n## Supported Resources\n\n- `Gateway`\n", encoding="utf-8"
        )

        catalog = ChartCatalog.discover(
            root_chart_dir=root_chart, search_roots=[workspace]
        )
        self.server = NucChartMCPServer(catalog)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_tools_list_exposes_expected_tool_names(self) -> None:
        payload = self.server.handle_request("tools/list", {})
        names = [item["name"] for item in payload["tools"]]
        self.assertIn("list_charts", names)
        self.assertIn("render_chart", names)

    def test_get_chart_overview_tool_returns_text(self) -> None:
        result = self.server.handle_request(
            "tools/call",
            {
                "name": "get_chart_overview",
                "arguments": {"chart": "nuc-native-gateway"},
            },
        )
        self.assertIn("content", result)
        self.assertIn("nuc-native-gateway", result["content"][0]["text"])

    def test_value_explanation_tool_returns_dependency_toggle(self) -> None:
        result = self.server.handle_request(
            "tools/call",
            {
                "name": "explain_chart_value",
                "arguments": {"path": "nuc-native-gateway.enabled"},
            },
        )
        text = result["content"][0]["text"]
        self.assertIn("nuc-native-gateway.enabled", text)
        self.assertIn("default: false", text.lower())

    def test_http_payload_processing_returns_initialize_result(self) -> None:
        status, payload = self.server.process_payload(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
        )
        self.assertEqual(int(status), 200)
        self.assertEqual(payload["result"]["serverInfo"]["name"], "nuc-chart-mcp")
        self.assertEqual(payload["result"]["protocolVersion"], "2025-03-26")

    def test_http_payload_processing_returns_accepted_for_notification(self) -> None:
        status, payload = self.server.process_payload(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self.assertEqual(int(status), 202)
        self.assertIsNone(payload)

    def test_http_transport_config_normalizes_path(self) -> None:
        config = HttpTransportConfig(
            bind="127.0.0.1",
            port=0,
            mcp_path="mcp",
            allowed_origins=tuple(),
            bearer_token="secret-token",
        )
        self.assertEqual(config.normalized_mcp_path, "/mcp")
        self.assertEqual(config.bearer_token, "secret-token")

    def test_resources_list_returns_catalog_and_overviews(self) -> None:
        payload = self.server.handle_request("resources/list", {})
        uris = [r["uri"] for r in payload["resources"]]
        self.assertIn("chart://catalog", uris)
        self.assertIn("chart://nxs-universal-chart/overview", uris)
        self.assertIn("chart://nuc-native-gateway/overview", uris)

    def test_resources_read_catalog_returns_json(self) -> None:
        payload = self.server.handle_request(
            "resources/read", {"uri": "chart://catalog"}
        )
        self.assertIn("contents", payload)
        catalog_data = json.loads(payload["contents"][0]["text"])
        self.assertEqual(catalog_data["rootChart"], "nxs-universal-chart")

    def test_resources_read_overview_returns_markdown(self) -> None:
        payload = self.server.handle_request(
            "resources/read", {"uri": "chart://nxs-universal-chart/overview"}
        )
        text = payload["contents"][0]["text"]
        self.assertIn("nxs-universal-chart", text)

    def test_list_charts_tool_returns_chart_names(self) -> None:
        result = self.server.handle_request(
            "tools/call", {"name": "list_charts", "arguments": {}}
        )
        text = result["content"][0]["text"]
        self.assertIn("nxs-universal-chart", text)
        self.assertIn("nuc-native-gateway", text)

    def test_search_chart_docs_tool_finds_content(self) -> None:
        result = self.server.handle_request(
            "tools/call",
            {"name": "search_chart_docs", "arguments": {"query": "Deployment"}},
        )
        text = result["content"][0]["text"]
        self.assertIn("Deployment", text)

    def test_suggest_chart_for_resource_tool(self) -> None:
        result = self.server.handle_request(
            "tools/call",
            {
                "name": "suggest_chart_for_resource",
                "arguments": {"resource": "Gateway"},
            },
        )
        text = result["content"][0]["text"]
        self.assertIn("nuc-native-gateway", text)

    def test_validate_chart_values_tool_valid(self) -> None:
        result = self.server.handle_request(
            "tools/call",
            {
                "name": "validate_chart_values",
                "arguments": {
                    "chart": "nxs-universal-chart",
                    "values_yaml": "nuc-native-gateway:\n  enabled: false\n",
                },
            },
        )
        text = result["content"][0]["text"]
        self.assertIn("Valid: yes", text)

    def test_unknown_tool_surfaces_as_json_rpc_error(self) -> None:
        # handle_request propagates JsonRpcError for unknown tools;
        # the error is caught at process_message level and becomes an error response.
        response = self.server.process_message(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "nonexistent_tool_xyz", "arguments": {}},
            }
        )
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_missing_required_argument_returns_error(self) -> None:
        from nuc_chart_mcp.server import JsonRpcError

        with self.assertRaises(JsonRpcError):
            self.server.handle_request(
                "tools/call",
                {"name": "search_chart_docs", "arguments": {}},
            )

    def test_ping_returns_empty_result(self) -> None:
        result = self.server.handle_request("ping", {})
        self.assertEqual(result, {})

    def test_unknown_method_raises_json_rpc_error(self) -> None:
        from nuc_chart_mcp.server import JsonRpcError

        with self.assertRaises(JsonRpcError) as ctx:
            self.server.handle_request("completely/unknown/method", {})
        self.assertEqual(ctx.exception.code, -32601)

    def test_batch_payload_processes_multiple_requests(self) -> None:
        status, payload = self.server.process_payload(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            ]
        )
        self.assertEqual(int(status), 200)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_batch_notification_only_returns_accepted(self) -> None:
        status, payload = self.server.process_payload(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            ]
        )
        self.assertEqual(int(status), 202)
        self.assertIsNone(payload)

    def test_empty_batch_returns_bad_request(self) -> None:
        status, payload = self.server.process_payload([])
        self.assertEqual(int(status), 400)

    def test_process_invalid_payload_returns_error(self) -> None:
        status, payload = self.server.process_payload("not-a-dict-or-list")
        self.assertEqual(int(status), 400)

    def test_process_message_missing_method_returns_error(self) -> None:
        response = self.server.process_message({"jsonrpc": "2.0", "id": 1})
        self.assertIn("error", response)

    def test_parse_allowed_origins_from_env(self) -> None:
        import os

        os.environ["NUC_ALLOWED_ORIGINS"] = (
            "https://a.example.com,https://b.example.com"
        )
        try:
            origins = parse_allowed_origins(None)
            self.assertIn("https://a.example.com", origins)
            self.assertIn("https://b.example.com", origins)
        finally:
            del os.environ["NUC_ALLOWED_ORIGINS"]

    def test_parse_allowed_origins_prefers_cli_over_env(self) -> None:
        import os

        os.environ["NUC_ALLOWED_ORIGINS"] = "https://env.example.com"
        try:
            origins = parse_allowed_origins(["https://cli.example.com"])
            self.assertIn("https://cli.example.com", origins)
            self.assertNotIn("https://env.example.com", origins)
        finally:
            del os.environ["NUC_ALLOWED_ORIGINS"]

    def test_reload_catalog_tool_refreshes_catalog(self) -> None:
        calls: list[int] = []

        def factory() -> ChartCatalog:
            calls.append(1)
            return self.server.catalog

        srv = NucChartMCPServer(self.server.catalog, catalog_factory=factory)
        result = srv.handle_request(
            "tools/call", {"name": "reload_catalog", "arguments": {}}
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("Catalog reloaded", result["content"][0]["text"])

    def test_reload_catalog_without_factory_returns_error(self) -> None:
        result = self.server.handle_request(
            "tools/call", {"name": "reload_catalog", "arguments": {}}
        )
        self.assertTrue(result.get("isError"))
        self.assertIn("unavailable", result["content"][0]["text"].lower())

    def test_stdio_json_decode_error_writes_parse_error_response(self) -> None:
        import io
        import sys

        from nuc_chart_mcp.server import serve_stdio

        invalid_json = b"not-valid-json!"
        fake_stdin = io.BytesIO(
            f"Content-Length: {len(invalid_json)}\r\n\r\n".encode() + invalid_json
        )
        fake_stdout = io.BytesIO()

        class _FakeStdin:
            buffer = fake_stdin

        class _FakeStdout:
            buffer = fake_stdout

        orig_in, orig_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = _FakeStdin(), _FakeStdout()  # type: ignore[assignment]
        try:
            serve_stdio(self.server)
        finally:
            sys.stdin, sys.stdout = orig_in, orig_out

        output = fake_stdout.getvalue()
        body_start = output.find(b"\r\n\r\n")
        self.assertGreater(body_start, 0, "no HTTP-style header found in stdio output")
        response = json.loads(output[body_start + 4 :])
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32700)


class HTTPTransportTest(unittest.TestCase):
    """Integration tests that spin up a real HTTP server on a random port."""

    @classmethod
    def _build_catalog(cls, workspace: Path) -> ChartCatalog:
        root_chart = workspace / "nxs-universal-chart"
        root_chart.mkdir(parents=True)
        (root_chart / "Chart.yaml").write_text(
            textwrap.dedent("""\
                apiVersion: v2
                name: nxs-universal-chart
                type: application
                version: 3.0.21
                dependencies: []
            """),
            encoding="utf-8",
        )
        (root_chart / "values.yaml").write_text("{}\n", encoding="utf-8")
        (root_chart / "values.schema.json").write_text(
            json.dumps({"type": "object", "properties": {}}), encoding="utf-8"
        )
        (root_chart / "README.md").write_text(
            "# Root\n\n## Supported Resources\n\n- `Deployment`\n", encoding="utf-8"
        )
        return ChartCatalog.discover(root_chart_dir=root_chart)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        workspace = Path(self.temp_dir.name)
        catalog = self._build_catalog(workspace)
        mcp_server = NucChartMCPServer(catalog)

        self.config_no_auth = HttpTransportConfig(
            bind="127.0.0.1",
            port=0,
            mcp_path="/mcp",
            allowed_origins=("*",),
            bearer_token="",
        )
        self.httpd = build_http_server(mcp_server, self.config_no_auth)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        mcp_server_auth = NucChartMCPServer(catalog)
        config_auth = HttpTransportConfig(
            bind="127.0.0.1",
            port=0,
            mcp_path="/mcp",
            allowed_origins=tuple(),
            bearer_token="secret",
        )
        self.httpd_auth = build_http_server(mcp_server_auth, config_auth)
        self.port_auth = self.httpd_auth.server_address[1]
        thread_auth = threading.Thread(
            target=self.httpd_auth.serve_forever, daemon=True
        )
        thread_auth.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd_auth.shutdown()
        self.temp_dir.cleanup()

    def _get(self, path: str, port: int | None = None) -> tuple[int, bytes, str]:
        p = port or self.port
        req = urllib.request.Request(f"http://127.0.0.1:{p}{path}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), ""

    def _post_mcp(
        self,
        body: dict,
        port: int | None = None,
        token: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict]:
        p = port or self.port
        raw = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            f"http://127.0.0.1:{p}/mcp",
            data=raw,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    def test_healthz_returns_200_ok(self) -> None:
        status, body, _ = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertIn(b"ok", body)

    def test_readyz_returns_200_ok(self) -> None:
        status, body, _ = self._get("/readyz")
        self.assertEqual(status, 200)
        self.assertIn(b"ok", body)

    def test_root_returns_server_metadata(self) -> None:
        status, body, ct = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        data = json.loads(body)
        self.assertEqual(data["name"], "nuc-chart-mcp")
        self.assertIn("mcpPath", data)

    def test_unknown_path_returns_404(self) -> None:
        status, _, _ = self._get("/not/found")
        self.assertEqual(status, 404)

    def test_post_mcp_initialize_returns_200(self) -> None:
        status, data = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
            }
        )
        self.assertEqual(status, 200)
        self.assertIn("result", data)
        self.assertIn("serverInfo", data["result"])

    def test_post_mcp_tools_list_returns_tools(self) -> None:
        status, data = self._post_mcp(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        self.assertEqual(status, 200)
        names = [t["name"] for t in data["result"]["tools"]]
        self.assertIn("list_charts", names)
        self.assertIn("validate_chart_values", names)

    def test_auth_rejects_request_without_token(self) -> None:
        status, _ = self._post_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            port=self.port_auth,
        )
        self.assertEqual(status, 401)

    def test_auth_accepts_request_with_correct_token(self) -> None:
        status, data = self._post_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            port=self.port_auth,
            token="secret",
        )
        self.assertEqual(status, 200)

    def test_cors_forbidden_for_disallowed_origin(self) -> None:
        # Server has empty allowed_origins, so any Origin header is rejected
        status, _ = self._post_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            port=self.port_auth,
            token="secret",
            origin="https://evil.example.com",
        )
        self.assertEqual(status, 403)

    def test_cors_allowed_for_wildcard_server(self) -> None:
        # No-auth server has allowed_origins=("*",)
        status, data = self._post_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            origin="https://any.example.com",
        )
        self.assertEqual(status, 200)

    def test_invalid_json_body_returns_parse_error(self) -> None:
        raw = b"not json at all"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/mcp",
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                status, body = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            status, body = exc.code, json.loads(exc.read())
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_body_too_large_returns_413(self) -> None:
        import socket

        # Send only headers with Content-Length > 10 MB; the server rejects
        # before attempting to read the body.
        big_cl = 10 * 1024 * 1024 + 1
        request = (
            f"POST /mcp HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {big_cl}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        status_code = int(response.split(b"\r\n")[0].split(b" ")[1])
        self.assertEqual(status_code, 413)
