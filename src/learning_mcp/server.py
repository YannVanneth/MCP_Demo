"""A small MCP server exposing a couple of tools, a resource, and a prompt.

Run it over either transport:

    uv run learning-mcp-server --transport stdio
    uv run learning-mcp-server --transport http --host 127.0.0.1 --port 8000
"""

import argparse
import sys

from mcp.server.mcpserver import MCPServer

# Tool docstrings double as the description shown to MCP clients in
# list_tools()/list_resources()/list_prompts(), so keep them accurate.
#
# Diagnostics always go to stderr, never stdout: under the stdio transport,
# stdout is the JSON-RPC channel, so anything printed there would corrupt
# the protocol stream.
def log(message: str) -> None:
    print(message, file=sys.stderr)


server = MCPServer(name="learning-mcp-server")


@server.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return their sum."""
    log(f"tool call: add(a={a}, b={b})")
    return a + b


@server.tool()
def echo(text: str) -> str:
    """Echo the given text back to the caller, unchanged."""
    log(f"tool call: echo(text={text!r})")
    return text


NOTES = "This is a demo resource served by learning-mcp-server.\nIt could be file contents, DB rows, or any other context data."


@server.resource("memo://notes")
def notes() -> str:
    """Return a static memo resource, to demonstrate resource discovery/reading."""
    log("resource read: memo://notes")
    return NOTES


@server.prompt()
def summarize(text: str) -> str:
    """Build a prompt asking the model to summarize the given text in one sentence."""
    log(f"prompt request: summarize(text={text!r})")
    return f"Please summarize the following text in one sentence:\n\n{text}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the learning MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to serve over (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (http transport only).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (http transport only).")
    args = parser.parse_args()

    log(f"starting learning-mcp-server (transport={args.transport})")
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        log(f"listening on http://{args.host}:{args.port}/mcp")
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
        )
    log("learning-mcp-server stopped")


if __name__ == "__main__":
    main()
