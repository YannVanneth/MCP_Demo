"""Two ways to give an AI model a tool.

1. LOCAL TOOL: a normal Python function. The AI asks for it, and WE run it
   ourselves, right here in this same program.

2. MCP TOOL: a function that lives on ANOTHER program (a "server"). The AI
   still asks for it, but we have to send a message to that other program
   asking IT to run it, then wait for the answer.

Run it with:

    uv run learning-mcp-local-vs-mcp

This same file can also run AS the server (used internally, see below):

    python tool.py --serve
"""

import sys

import anyio
import ollama
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer

# This object represents "the server". We attach tools to it below.
server = MCPServer(name="tool-demo-server")


# This is the MCP tool. @server.tool() registers it on the server.
@server.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


# This is the local tool. It's just a normal function. Nothing special.
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def demo() -> None:
    # This lets us talk to the AI model.
    ai = ollama.AsyncClient()

    # ------------------------------------------------------------------
    # PART 1: LOCAL TOOL
    # ------------------------------------------------------------------
    print("LOCAL TOOL: multiply")

    # Ask the AI a question, and tell it about the multiply() function.
    question = "What is 4 times 5?"
    messages = [{"role": "user", "content": question}]
    response = await ai.chat(model="gemma4", messages=messages, tools=[multiply])

    # The AI's answer may contain a request to call "multiply".
    tool_calls = response["message"].get("tool_calls")

    if tool_calls:
        call = tool_calls[0]
        a = call["function"]["arguments"]["a"]
        b = call["function"]["arguments"]["b"]

        answer = multiply(a, b)  # we call it ourselves, no server involved
        print("answer:", answer)

    # ------------------------------------------------------------------
    # PART 2: MCP TOOL
    # ------------------------------------------------------------------
    print()
    print("MCP TOOL: add")

    # Start the server as its own separate program, and connect to it.
    server_command = StdioServerParameters(command=sys.executable, args=[__file__, "--serve"])

    async with Client(server_command) as client:
        # Ask the server: "what tools do you have?"
        tools_on_server = await client.list_tools()
        add_tool = tools_on_server.tools[0]

        # The AI needs a description of the tool in this exact shape.
        tool_description = {
            "type": "function",
            "function": {
                "name": add_tool.name,
                "description": add_tool.description,
                "parameters": add_tool.input_schema,
            },
        }

        # Ask the AI a question, and tell it about the "add" tool.
        question = "What is 21 plus 21?"
        messages = [{"role": "user", "content": question}]
        response = await ai.chat(model="gemma4", messages=messages, tools=[tool_description])

        tool_calls = response["message"].get("tool_calls")

        if tool_calls:
            call = tool_calls[0]

            arguments = call["function"]["arguments"]

            # We do NOT call add() ourselves. We ask the server to run it.
            server_response = await client.call_tool("add", arguments)
            answer = server_response.content[0].text
            print("answer:", answer)


def main() -> None:
    if "--serve" in sys.argv:
        # We were started as the server -- just be the server.
        server.run(transport="stdio")
    else:
        # Normal start -- run the demo above.
        anyio.run(demo)


if __name__ == "__main__":
    main()
