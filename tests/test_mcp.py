"""Offline MCP wire, schema, school transport, session and subprocess integration tests."""
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bakalari import BakalariClient, BakalariConfigError, BakalariConnectionError, BakalariContractError, BakalariError
from bakalari._mcp_tools import MAX_ATTACHMENT_BYTES, build_tools, validate
from bakalari.cli import main as cli_main
from bakalari.mcp import MAX_MESSAGE_BYTES, MCPServer, main
from bakalari.schools import SchoolDirectory

from .support import (
    BASE_URL,
    FORBIDDEN,
    INVALID_GRANT,
    FakeClock,
    FakeTransport,
    binary_response,
    empty_response,
    json_response,
    load_fixture,
    logged_in_client,
    token_response,
)
from .test_cli import clean_environment, write_session


def request(method, params=None, identifier=1):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}


def initialize(version="2025-11-25"):
    return request("initialize", {"protocolVersion": version, "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "1"}})


INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def ready(server, version="2025-11-25"):
    server.handle(initialize(version))
    server.handle(INITIALIZED)
    return server


def call(server, name, arguments=None):
    return server.handle(request("tools/call", {"name": name, "arguments": arguments or {}}))


def frames(*messages):
    return b"".join((json.dumps(message) + "\n").encode() for message in messages)


class ProtocolTest(unittest.TestCase):
    def test_handshake_versions_and_lazy_discovery(self):
        provider = mock.Mock(side_effect=AssertionError("Discovery must not connect"))
        for version in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "future-version"):
            with self.subTest(version=version):
                server = MCPServer(client_provider=provider)
                self.assertEqual(server.handle(request("server/discover"))["error"]["code"], -32601)
                self.assertEqual(server.handle(request("tools/list"))["error"]["code"], -32000)
                self.assertEqual(server.handle(request("ping"))["result"], {})
                result = server.handle(initialize(version))["result"]
                self.assertEqual(result["protocolVersion"], version if version != "future-version" else "2025-11-25")
                self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
                self.assertEqual(server.handle(request("tools/list"))["error"]["code"], -32000)
                self.assertIsNone(server.handle(INITIALIZED))
                tools = server.handle(request("tools/list"))["result"]["tools"]
                self.assertGreater(len(tools), 40)
                self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))
                self.assertEqual(server.handle(initialize())["error"]["code"], -32600)
        provider.assert_not_called()

    def test_protocol_errors_and_notifications(self):
        server = ready(MCPServer())
        for message, code in [
            ([], -32600), (None, -32600), ({}, -32600),
            (request("ping", identifier=True), -32600), (request("ping", identifier=None), -32600),
            (request("ping", identifier=1.5), -32600),
            ({"jsonrpc": "2.0", "id": 1, "method": 2}, -32600),
            ({"jsonrpc": "2.0", "id": 1, "method": "ping", "result": {}}, -32600),
            ({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}, -32602),
            (request("unknown"), -32601), (request("tools/list", {"cursor": "wrong"}), -32602),
            (request("tools/call"), -32602),
            (request("tools/call", {"name": "marks", "arguments": []}), -32602),
            (request("tools/call", {"name": "__dict__"}), -32602),
        ]:
            with self.subTest(message=message):
                self.assertEqual(server.handle(message)["error"]["code"], code)
        for message in (INITIALIZED, {"jsonrpc": "2.0", "method": "unknown"},
                        {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "send_message"}},
                        {"jsonrpc": "2.0", "id": 1, "result": {}}):
            self.assertIsNone(server.handle(message))
        for identifier in (0, "", "request-2"):
            self.assertEqual(server.handle(request("ping", identifier=identifier))["id"], identifier)

    def test_invalid_initialization_can_be_retried(self):
        server = MCPServer()
        self.assertIsNone(server.handle(INITIALIZED))
        for field in ("protocolVersion", "capabilities", "clientInfo"):
            message = initialize()
            del message["params"][field]
            self.assertEqual(server.handle(message)["error"]["code"], -32602)
        self.assertIn("result", server.handle(initialize()))

    def test_stream_errors_recover_and_flush(self):
        output = io.BytesIO()
        malformed = b'not json\n\xff\n{"x":NaN}\n{"x":1e999}\n' + b"[" * 2000 + b"\n"
        oversize = b"x" * (MAX_MESSAGE_BYTES * 2 + 1) + b"\n"
        source = io.BytesIO(malformed + oversize + frames(initialize(), INITIALIZED, request("ping")))
        MCPServer().serve(source, output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item["error"]["code"] for item in replies[:6]], [-32700] * 5 + [-32600])
        self.assertIn("protocolVersion", replies[6]["result"])
        self.assertEqual(replies[7]["result"], {})
        self.assertEqual(len(replies), 8)
        output = io.BytesIO()
        MCPServer().serve(io.BytesIO(frames(request("ping", {"value": 1.25}))), output)
        self.assertEqual(json.loads(output.getvalue())["result"], {})

    def test_internal_protocol_error_is_redacted(self):
        server = ready(MCPServer())
        with mock.patch.object(server, "_dispatch", side_effect=RuntimeError("SECRET")):
            result = server.handle(request("tools/list"))
        self.assertEqual(result["error"]["code"], -32603)
        self.assertNotIn("SECRET", json.dumps(result))


class ToolsTest(unittest.TestCase):
    def test_readonly_cannot_be_bypassed(self):
        client = mock.Mock(spec=BakalariClient)
        server = ready(MCPServer(client))
        forbidden = [name for name, tool in build_tools(True).items() if tool.write]
        forbidden += ["request", "get_json", "post_json", "login", "login_token", "web_login_url", "export_session"]
        for name in forbidden:
            self.assertEqual(call(server, name)["error"]["code"], -32602)
        self.assertTrue(call(server, "marks", {"allow_writes": True})["result"]["isError"])
        client.assert_not_called()
        self.assertEqual(client.mock_calls, [])

    def test_invalid_arguments_never_reach_school(self):
        provider = mock.Mock(side_effect=AssertionError("Invalid input must not connect"))
        server = ready(MCPServer(client_provider=provider, allow_writes=True))
        cases = [
            ("message", {}), ("message", {"message_id": ""}), ("message", {"message_id": 42}),
            ("message", {"message_id": "a", "folder": "SECRET"}),
            ("marks", {"since": "2026-02-30"}), ("marks", {"since": "20261015"}),
            ("marks", {"since": None}), ("marks", {"validate": False}),
            ("find_schools", {"text": "a", "max_requests": True}),
            ("find_schools", {"text": "a", "max_requests": 101}),
            ("set_homework_done", {"homework_id": "x", "done": "false"}),
            ("confirm_marks", {"mark_ids": [1]}),
            ("predict_marks", {"subject": "x", "hypothetical": [["1"]]}),
            ("predict_marks", {"subject": "x", "hypothetical": [["1", 0]]}),
            ("predict_marks", {"subject": "x", "hypothetical": [["1", True]]}),
            ("predict_marks", {"subject": "x", "hypothetical": []}),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                result = call(server, name, args)["result"]
                self.assertTrue(result["isError"])
                self.assertNotIn("SECRET", json.dumps(result))
        provider.assert_not_called()

    def test_catalog_defaults_required_and_write_annotations(self):
        tools = build_tools(True)
        self.assertEqual(tools["classbook"].schema["required"], ["since", "until"])
        self.assertEqual(tools["messages"].schema["properties"]["folder"]["default"], "received")
        self.assertFalse(tools["send_message"].definition()["annotations"]["idempotentHint"])
        self.assertTrue(tools["delete_message"].definition()["annotations"]["destructiveHint"])
        self.assertTrue(tools["predict_marks"].definition()["annotations"]["readOnlyHint"])
        for tool in tools.values():
            self.assertFalse(tool.schema["additionalProperties"])
            for schema in tool.schema["properties"].values():
                if "default" in schema:
                    validate(schema["default"], schema)

    def test_every_catalog_tool_dispatches_only_its_method(self):
        # Check the whole explicit catalog against real signatures without contacting a school.
        import inspect

        def sample(schema):
            if "default" in schema:
                return schema["default"]
            if "enum" in schema:
                return schema["enum"][0]
            if schema.get("format") == "date":
                return "2026-10-15"
            kind = schema.get("type")
            if isinstance(kind, list):
                kind = kind[0]
            if kind == "object":
                return {key: sample(schema["properties"][key]) for key in schema.get("required", [])}
            if kind == "array":
                if "prefixItems" in schema:
                    return [sample(item) for item in schema["prefixItems"]]
                return [sample(schema["items"]) for _ in range(schema.get("minItems", 0))]
            return {"string": "X", "boolean": False, "integer": 1, "number": 1}.get(kind)

        client = mock.Mock(spec=BakalariClient)
        directory = mock.Mock(spec=SchoolDirectory)
        server = ready(MCPServer(client, allow_writes=True, directory_provider=lambda: directory))
        for name, tool in build_tools(True).items():
            if name == "upload_attachment":
                continue
            with self.subTest(name=name):
                args = {key: sample(schema) for key, schema in tool.schema["properties"].items()}
                owner = SchoolDirectory if tool.target == "directory" else BakalariClient
                inspect.signature(getattr(owner, tool.method)).bind(None, **args)
                target = directory if tool.target == "directory" else client
                method = getattr(target, tool.method)
                method.return_value = {"ok": True}
                self.assertFalse(call(server, name, args)["result"]["isError"])
                method.assert_called_once_with(**args)
                method.reset_mock()

    def test_real_school_read_and_serialization(self):
        client, transport = logged_in_client(json_response(200, load_fixture("komens_received_detail.json")))
        result = call(ready(MCPServer(client)), "message", {"message_id": "  A/B"})["result"]
        self.assertFalse(result["isError"])
        data = result["structuredContent"]["data"]
        self.assertIn("plain_text", data)
        self.assertIn("text", data)
        self.assertNotIn("raw", data)
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertIn("%20%20A%2FB", transport.api_calls[0].url)
        self.assertEqual([item.method for item in transport.api_calls], ["GET"])
        for secret in ("access-1", "refresh-1", "Secret-Pa55word"):
            self.assertNotIn(secret, json.dumps(result))

    def test_legacy_text_results(self):
        client, _ = logged_in_client(json_response(200, 3))
        result = call(ready(MCPServer(client), "2024-11-05"), "new_marks_count")["result"]
        self.assertNotIn("structuredContent", result)
        self.assertEqual(json.loads(result["content"][0]["text"]), {"data": 3})

    def test_writes_and_no_retry_on_post(self):
        client, transport = logged_in_client(empty_response(), json_response(200, None),
                                            BakalariConnectionError("SECRET"), retries=2)
        server = ready(MCPServer(client, allow_writes=True))
        self.assertFalse(call(server, "set_homework_done", {"homework_id": "H1", "done": False})["result"]["isError"])
        self.assertTrue(transport.api_calls[0].path.endswith("/H1/student-done/false"))
        args = {"message_type": "OBECNA", "recipient_type": "UCITEL", "text": "Hello", "recipients": ["T1"]}
        self.assertFalse(call(server, "send_message", args)["result"]["isError"])
        self.assertEqual(transport.api_calls[1].json["Recipients"], ["T1"])
        result = call(server, "send_message", args)["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(len(transport.api_calls), 3)

    def test_directory_without_school_configuration(self):
        transport = FakeTransport(json_response(200, load_fixture("schools_municipalities.json")))
        server = ready(MCPServer(directory_provider=lambda: SchoolDirectory(transport=transport)))
        with clean_environment():
            result = call(server, "school_municipalities")["result"]
        self.assertFalse(result["isError"])
        self.assertIsInstance(result["structuredContent"]["data"], list)

    def test_attachment_transfer_and_limits(self):
        client, transport = logged_in_client(binary_response(b"\x00\xffdata"), json_response(201, "ATT1"))
        server = ready(MCPServer(client, allow_writes=True))
        result = call(server, "download_attachment", {"attachment_id": "ATT1"})["result"]
        self.assertEqual(base64.b64decode(result["structuredContent"]["data"]["content_base64"]), b"\x00\xffdata")
        args = {"content_base64": base64.b64encode(b"data").decode(), "filename": "file.txt"}
        result = call(server, "upload_attachment", args)["result"]
        self.assertFalse(result["isError"])
        self.assertIn(b"data", transport.api_calls[-1].body)
        for content in ("/etc/passwd", "bad!", base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES + 1)).decode()):
            result = call(server, "upload_attachment", dict(args, content_base64=content))["result"]
            self.assertTrue(result["isError"])
        self.assertEqual(len(transport.api_calls), 2)
        transport.responses.append(binary_response(b"x" * (MAX_ATTACHMENT_BYTES + 1)))
        self.assertTrue(call(server, "download_attachment", {"attachment_id": "big"})["result"]["isError"])

    def test_failures_are_tool_results_and_do_not_kill_connection(self):
        client, _ = logged_in_client(FORBIDDEN, json_response(404, {"SECRET": "secret"}),
                                    json_response(500, {"SECRET": "secret"}), json_response(200, 2))
        server = ready(MCPServer(client))
        for _ in range(3):
            result = call(server, "new_marks_count")["result"]
            self.assertTrue(result["isError"])
            self.assertNotIn("secret", json.dumps(result))
        self.assertFalse(call(server, "new_marks_count")["result"]["isError"])
        for error in (BakalariConfigError("SECRET"), BakalariContractError(["SECRET"]),
                      BakalariError("SECRET"), TypeError("SECRET"), RuntimeError("SECRET")):
            with self.subTest(error=type(error)):
                server = ready(MCPServer(client_provider=mock.Mock(side_effect=error)))
                result = call(server, "marks")["result"]
                self.assertTrue(result["isError"])
                self.assertNotIn("SECRET", json.dumps(result))
        transport = FakeTransport(INVALID_GRANT)
        client = BakalariClient(BASE_URL, "user", "SECRET", transport=transport)
        self.assertTrue(call(ready(MCPServer(client)), "marks")["result"]["isError"])

    def test_result_size_limit(self):
        client = mock.Mock(spec=BakalariClient)
        client.api_version.return_value = {"big": "x" * 200}
        with mock.patch("bakalari.mcp.MAX_RESULT_BYTES", 100):
            result = call(ready(MCPServer(client)), "api_version")["result"]
        self.assertTrue(result["isError"])

    def test_environment_client_can_use_public_tools_without_credentials(self):
        with clean_environment():
            self.assertTrue(call(ready(MCPServer()), "api_version")["result"]["isError"])
        with clean_environment(BAKALARI_URL=BASE_URL):
            with mock.patch.object(BakalariClient, "api_version", return_value={}):
                self.assertFalse(call(ready(MCPServer()), "api_version")["result"]["isError"])


class CliIntegrationTest(unittest.TestCase):
    def test_repeated_calls_cannot_bypass_a_mismatched_session(self):
        with tempfile.TemporaryDirectory() as temporary, clean_environment():
            path = Path(temporary) / "session.json"
            write_session(path, base_url="https://other-school.example")
            transport = FakeTransport()
            stream = io.BytesIO(frames(initialize(), INITIALIZED,
                                      request("tools/call", {"name": "api_version"}),
                                      request("tools/call", {"name": "api_version"}, identifier=2)))
            output = io.BytesIO()
            with mock.patch("sys.stdin", mock.Mock(buffer=stream)), mock.patch("sys.stdout", mock.Mock(buffer=output)):
                code = cli_main(["--session-file", str(path), "mcp"],
                                client_factory=lambda args, needs_login: BakalariClient(BASE_URL, transport=transport))
            self.assertEqual(code, 0)
            replies = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertTrue(all(reply["result"]["isError"] for reply in replies[1:]))
            self.assertEqual(transport.calls, [])

    def test_session_refresh_is_saved_during_connection(self):
        with tempfile.TemporaryDirectory() as temporary, clean_environment():
            path = Path(temporary) / "session.json"
            write_session(path, expires_at=0)

            def after_refresh(call):
                # Check while the school request is in progress, before EOF/final cleanup can save anything.
                self.assertEqual(json.loads(path.read_text())["refresh_token"], "refresh-2")
                return json_response(200, 5)

            transport = FakeTransport(token_response("access-2", "refresh-2"), after_refresh)
            stream = io.BytesIO(frames(initialize(), INITIALIZED, request("tools/call", {"name": "new_marks_count"})))
            output = io.BytesIO()

            def factory(args, needs_login):
                self.assertFalse(needs_login)
                return BakalariClient(BASE_URL, transport=transport, clock=FakeClock())

            with mock.patch("sys.stdin", mock.Mock(buffer=stream)), mock.patch("sys.stdout", mock.Mock(buffer=output)):
                code = cli_main(["--session-file", str(path), "mcp"], client_factory=factory)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text())["refresh_token"], "refresh-2")
            self.assertEqual(transport.calls[0].form["grant_type"], "refresh_token")
            self.assertNotIn(b"refresh-2", output.getvalue())
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_subprocess_stdio_without_credentials(self):
        with clean_environment():
            for command in ([sys.executable, "-m", "bakalari", "mcp"],
                            [sys.executable, "-m", "bakalari.mcp"],
                            [sys.executable, "-m", "bakalari.mcp", "--allow-writes"]):
                with self.subTest(command=command):
                    result = subprocess.run(command, input=frames(initialize(), INITIALIZED, request("tools/list")),
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, b"")
                    replies = [json.loads(line) for line in result.stdout.splitlines()]
                    self.assertEqual(len(replies), 2)
                    names = {tool["name"] for tool in replies[1]["result"]["tools"]}
                    self.assertEqual("send_message" in names, "--allow-writes" in command)

    def test_entrypoint_options(self):
        with mock.patch("bakalari.cli.main", return_value=0) as cli:
            self.assertEqual(main(["--base-url", BASE_URL, "--allow-writes"]), 0)
        cli.assert_called_once_with(["--base-url", BASE_URL, "mcp", "--allow-writes"])
        with self.assertRaises(ValueError):
            MCPServer(BakalariClient(BASE_URL), client_provider=lambda: BakalariClient(BASE_URL))


if __name__ == "__main__":
    unittest.main()
