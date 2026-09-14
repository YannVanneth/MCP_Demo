"""A small MCP client. By default it lets a local Ollama model decide which
of the server's tools to call (requires `ollama serve` running and the
default model, gemma4, pulled) — just run it with no arguments:

    uv run learning-mcp-client

Other examples:

    # ask something else, or use a different model
    uv run learning-mcp-client --prompt "Echo back 'hello'" --model qwen3.5:2b

    # run the built-in tool/resource/prompt demo instead (no LLM involved)
    uv run learning-mcp-client --demo

    # talk to a server already running with
    #   uv run learning-mcp-server --transport http --port 8000
    uv run learning-mcp-client --transport http --url http://127.0.0.1:8000/mcp
"""

import argparse
import sys
from collections.abc import Awaitable, Callable

import anyio
import ollama
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

SessionHandler = Callable[[ClientSession], Awaitable[None]]


# Diagnostics go to stderr so they never mix with the human-readable
# results printed to stdout below.
def log(message: str) -> None:
    print(message, file=sys.stderr)


async def run_session(session: ClientSession) -> None:
    print(f"Connected to: {session.server_info}\n")

    tools = await session.list_tools()
    print("Tools:", [t.name for t in tools.tools])

    add_result = await session.call_tool("add", {"a": 2, "b": 3})
    log(f"tool 'add' returned: {add_result.content}")
    print("add(2, 3) ->", add_result.content)

    echo_result = await session.call_tool("echo", {"text": "hello mcp"})
    log(f"tool 'echo' returned: {echo_result.content}")
    print("echo('hello mcp') ->", echo_result.content)

    print()
    resources = await session.list_resources()
    print("Resources:", [r.uri for r in resources.resources])

    resource_result = await session.read_resource("memo://notes")
    log(f"resource memo://notes returned {len(resource_result.contents)} content item(s)")
    print("memo://notes ->", resource_result.contents)

    print()
    prompts = await session.list_prompts()
    print("Prompts:", [p.name for p in prompts.prompts])

    prompt_result = await session.get_prompt("summarize", {"text": "MCP connects models to tools."})
    log(f"prompt 'summarize' returned {len(prompt_result.messages)} message(s)")
    print("summarize prompt ->", prompt_result.messages)


def _tool_result_to_text(result) -> str:
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


async def _call_tool(session: ClientSession, name: str, arguments: dict) -> str:
    print(f"[tool call] {name}({arguments})")
    result = await session.call_tool(name, arguments)
    content = _tool_result_to_text(result)
    print(f"[tool result] {content}")
    return content


async def run_agent(session: ClientSession, model: str, user_input: str) -> None:
    """Let an Ollama model converse and decide when to call the server's tools.

    Ollama has no notion of MCP; this is the host-side glue that (1) tells
    Ollama what tools exist by translating MCP tool schemas into Ollama's
    function-calling format, and (2) executes whatever tool calls the model
    requests via the same ClientSession used elsewhere in this file, feeding
    results back until the model produces a final answer.
    """
    mcp_tools = await session.list_tools()
    tools = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            },
        }
        for t in mcp_tools.tools
    ]
    log(f"advertising tools to ollama: {[t['function']['name'] for t in tools]}")

    messages = [{"role": "user", "content": user_input}]
    print(f"> {user_input}\n")

    client = ollama.AsyncClient()
    max_rounds = 8  # guard against a model that loops on tool calls forever
    for _ in range(max_rounds):
        response = await client.chat(model=model, messages=messages, tools=tools)
        message = response["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            print(message.get("content", ""))
            return

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            content = await _call_tool(session, name, arguments)
            messages.append({"role": "tool", "content": content, "tool_name": name})

    print(f"(stopped after {max_rounds} tool-call rounds without a final answer)")


async def run_with_transport(transport_cm, handler: SessionHandler) -> None:
    async with transport_cm as (read, write):
        async with ClientSession(read, write) as session:
            log("sending initialize request")
            await session.initialize()
            log(f"session initialized: server_info={session.server_info}")
            await handler(session)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the learning MCP client.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to connect over (default: stdio).",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/mcp",
        help="Server URL (http transport only; server must already be running).",
    )
    parser.add_argument(
        "--model",
        default="gemma4",
        help="Ollama model to drive the server through (default: gemma4). Requires `ollama serve` running locally and the model pulled.",
    )
    parser.add_argument(
        "--prompt",
        default="What is 21 plus 21? Use the add tool to find out.",
        help="User prompt to send the model.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in tool/resource/prompt demo instead of the Ollama agent.",
    )
    args = parser.parse_args()

    if args.demo:
        handler = run_session
    else:
        async def handler(session: ClientSession) -> None:
            await run_agent(session, args.model, args.prompt)

    if args.transport == "stdio":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "learning_mcp.server", "--transport", "stdio"],
        )
        log(f"spawning server subprocess: {params.command} {' '.join(params.args)}")
        anyio.run(run_with_transport, stdio_client(params), handler)
    else:
        log(f"connecting to MCP server over HTTP: {args.url}")
        anyio.run(run_with_transport, streamable_http_client(args.url), handler)


if __name__ == "__main__":
    main()
