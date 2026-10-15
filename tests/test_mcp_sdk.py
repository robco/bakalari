"""Optional interoperability checks with the official MCP SDK; core tests need no dependencies.

Run with ``python -m pip install 'mcp>=1.26,<2' jsonschema`` in a separate test environment.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("jsonschema") is not None
SERVER = """
from bakalari.cli import main
from tests.support import logged_in_client, json_response, load_fixture, empty_response
from tests.test_cli import clean_environment
client, transport = logged_in_client(json_response(200, load_fixture('marks.json')), empty_response())
with clean_environment():
    raise SystemExit(main(['mcp', '--allow-writes'], client_factory=lambda args, needs_login: client))
"""


@unittest.skipUnless(SDK_AVAILABLE, "optional official MCP SDK not installed")
class SDKIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_official_client_discovers_validates_reads_and_writes(self):
        from jsonschema import Draft202012Validator
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.shared.exceptions import McpError

        parameters = StdioServerParameters(command=sys.executable, args=["-c", SERVER],
                                           cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                result = await session.initialize()
                self.assertEqual(result.serverInfo.name, "bakalari-api")
                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                self.assertIn("marks", tools)
                self.assertIn("send_message", tools)
                for tool in tools.values():
                    Draft202012Validator.check_schema(tool.inputSchema)
                result = await session.call_tool("marks", {"since": "2026-10-01"})
                self.assertFalse(result.isError)
                self.assertIn("subjects", result.structuredContent["data"])
                result = await session.call_tool("set_homework_done", {"homework_id": "H1", "done": True})
                self.assertFalse(result.isError)
                result = await session.call_tool("message", {})
                self.assertTrue(result.isError)
                with self.assertRaises(McpError):
                    await session.call_tool("export_session", {})
                await session.send_ping()


if __name__ == "__main__":
    unittest.main()
