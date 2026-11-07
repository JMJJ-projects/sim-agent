"""`simagent mcp` speaks MCP over stdio in a real subprocess (R-MCP-1)."""

import sys
from typing import Any

import anyio
from mcp import Client, StdioServerParameters


def test_stdio_server_lists_tools_and_describes() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from simagent.cli import app; app()", "mcp", "--provider", "fake"],
    )

    async def go() -> tuple[Any, Any]:
        async with Client(params) as client:
            tools = await client.list_tools()
            described = await client.call_tool("describe_simulator", {})
            return tools, described

    tools, described = anyio.run(go)
    assert {t.name for t in tools.tools} == {"describe_simulator", "run_simulation_script", "solve"}
    assert "photonsim API reference" in described.content[0].text
