"""Prototype: how MCP-based integration differs from local/direct integration.

MCP integration here runs over HTTP -- the server is a real web server, and
the client talks to it with normal HTTP requests, at http://127.0.0.1:8000/mcp.

DIRECT INTEGRATION (multiply)
    You import the function and call it. That IS the integration.

MCP INTEGRATION (add)
    You can't import it -- it lives on another process, reachable only
    over HTTP. You connect to it as an MCP client, ask what it offers,
    then call the tool through that connection.

Run it with:

    python demo.py
"""
import asyncio
import subprocess
import sys

import anyio
from mcp import Client
from mcp.server.mcpserver import MCPServer

URL = "http://127.0.0.1:8000/mcp"
server = MCPServer(name="tool-demo-server")


# MCP tool: registered on the server.
@server.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


# Local tool: just a function.
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def demo_local_tool() -> None:
    # --- Direct integration: import it, call it. Done. -----------------
    print("DIRECT INTEGRATION")
    print("multiply(4, 5) =", multiply(4, 5))


async def demo_mcp_tool() -> None:

    # --- MCP integration: connect over HTTP to the other process -------
    print("\nMCP INTEGRATION (http)")

    # The server has to run in its OWN process -- server.run() blocks and
    # starts its own event loop, so it can't run inline in this coroutine.
    subprocess.Popen([sys.executable, __file__, "--serve"])
    await anyio.sleep(1)  # give the server a moment to start

    async with Client(URL) as client:
        tools = await client.list_tools()  # ask what it can do
        print("server has these tools:", [t.name for t in tools.tools])

        result = await client.call_tool("add", {"a": 21, "b": 21})  # ask it to run one
        print("add(21, 21) =", result.content[0].text)


def main() -> None:
    if "--serve" in sys.argv:
        # This is the subprocess demo_mcp_tool() spawns -- just be the server.
        server.run(transport="streamable-http")
        return

    asyncio.run(demo_local_tool())
    asyncio.run(demo_mcp_tool())


if __name__ == "__main__":
    main()
