# learning-mcp

A minimal MCP server and client, built on the official `mcp` Python SDK, exercising both
supported transports: **stdio** and **streamable HTTP**.

The server exposes:
- Tools: `add(a, b)`, `echo(text)`
- Resource: `memo://notes`
- Prompt: `summarize(text)`

## Setup

```bash
uv sync
```

## Run it

With `ollama serve` running and the default model (`gemma4`) pulled, just run:

```bash
uv run learning-mcp-client
```

This spawns the server over stdio and lets a local Ollama model decide which tools to
call: it lists the server's tools, hands their schemas to Ollama, executes whatever tool
calls the model requests, and feeds the results back until Ollama gives a final answer.

Override the model or prompt:

```bash
uv run learning-mcp-client --prompt "Echo back 'hello'" --model qwen3.5:2b
```

Run the built-in tool/resource/prompt demo instead (no LLM involved):

```bash
uv run learning-mcp-client --demo
```

`src/learning_mcp/tool.py` defines a local tool and an MCP tool in one file
and shows what actually differs *at registration*: the MCP tool (`add`) is
registered up front with `@server.tool()`; the local tool (`multiply`) is
never registered at all, it's just a function handed to Ollama at call
time. See "Local tool vs. MCP tool" in `MCP_Overview.md`. Requires `ollama
serve` running with `gemma4` pulled:

```bash
uv run learning-mcp-local-vs-mcp
```

## Run over HTTP

Start the server in one terminal:

```bash
uv run learning-mcp-server --transport http --host 127.0.0.1 --port 8000
```

Then, in another terminal:

```bash
uv run learning-mcp-client --transport http --url http://127.0.0.1:8000/mcp
```
