# How MCP works with an LLM

## The three roles

MCP (Model Context Protocol) defines three parties:

- **Server** — exposes tools, resources, and prompts. In this repo, that's
  `learning_mcp.server`: it offers `add`, `echo`, the `memo://notes`
  resource, and the `summarize` prompt.
- **Client** — a protocol connection to one server. Speaks JSON-RPC over a
  transport (stdio or HTTP). This repo's `ClientSession` is a client.
- **Host** — the application that owns the LLM conversation and holds one or
  more clients. Claude Desktop, Claude Code, and this repo's `client.py` are
  all hosts.

The key thing to understand: **the LLM itself never speaks MCP.** A model
like Ollama's `gemma4` has no idea the protocol exists. MCP is a contract
between the host and the server; the host's job is to bridge that contract
to whatever tool-calling format the LLM understands.

## The loop

1. **Discover** — the host asks the server what it offers:
   `session.list_tools()`. It gets back each tool's name, description, and
   JSON-schema input parameters.
2. **Translate** — the host converts those tool definitions into the LLM's
   own function-calling format. For Ollama's chat API, that's a `tools`
   array of `{"type": "function", "function": {name, description,
   parameters}}` objects.
3. **Ask** — the host sends the user's message plus the `tools` list to the
   LLM. The model decides, on its own, whether answering requires calling a
   tool.
4. **Execute** — if the model's response includes a tool call (a name and
   arguments), the host — not the model — actually runs it, via
   `session.call_tool(name, arguments)`. The server does the work and
   returns a result.
5. **Feed back** — the host appends the tool's result to the conversation as
   a new message and sends the whole thing back to the LLM.
6. **Repeat or finish** — the model either asks for another tool call (loop
   back to step 4) or produces a final natural-language answer.

```
User prompt
   │
   ▼
┌─────────┐   list_tools()   ┌─────────┐
│         │ ───────────────▶ │   MCP   │
│  Host   │                  │ Server  │
│ (LLM +  │ ◀─────────────── │         │
│ client) │   tool schemas   └─────────┘
│         │
│         │   chat(messages, tools)
│         │ ───────────────▶  LLM (e.g. Ollama)
│         │ ◀───────────────  tool_call or final answer
│         │
│         │   call_tool(name, args)   ┌─────────┐
│         │ ─────────────────────────▶│   MCP   │
│         │ ◀─────────────────────────│ Server  │
│         │      result               └─────────┘
└─────────┘
   │
   ▼
Final answer
```

## Where this lives in this repo

`src/learning_mcp/client.py`'s `run_agent()` function is exactly this loop:

- `session.list_tools()` — discover
- the list comprehension building `tools` — translate
- `ollama.AsyncClient().chat(...)` — ask
- `session.call_tool(name, arguments)` inside `_call_tool()` — execute
- `messages.append({"role": "tool", ...})` — feed back
- the `for` loop around all of it — repeat, up to `max_rounds`

Run it with:

```bash
uv run learning-mcp-client
```

## Local tool vs. MCP tool

There are two ways to give an LLM a function it can call. Both end up
producing the same `tools` schema and the same tool-call/response messages
in the chat loop — the difference is *where the function lives* and *who
runs it*.

**Local tool** — a plain Python function defined in the same process as the
host. There's no registration step: it becomes callable by the LLM only at
the moment you build the `tools` list and hand the function straight to
`ollama.chat(tools=[multiply])`, which reads its signature/docstring right
there, per call (e.g. `ollama._utils.convert_function_to_tool`). When the
model requests it, the host calls it directly, in-process, with no network
hop.

**MCP tool** — a function registered once, up front, on a separate MCP
*server* object, via a decorator:

```python
@server.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b
```

That decorator runs at import time — before any LLM conversation exists —
and adds `add` to the server's own tool registry. From then on, any client
that connects to this server discovers it the same way, by calling
`list_tools()`; the host never calls the function itself, it goes through a
`ClientSession` over a transport (stdio, HTTP) and sends `call_tool(name,
args)` as an RPC, waiting for the server's response.

| | Local tool | MCP tool |
|---|---|---|
| Registered | never — it's just a function | once, at import time, via `@server.tool()` |
| Registration lives in | nowhere — re-derived from the function every `chat()` call | the server's tool registry (what answers `list_tools()`) |
| Defined | in the host's own code | on a separate MCP server |
| Schema comes from | the function's signature/docstring | the server's `list_tools()` response |
| Execution | direct in-process call | RPC over stdio/HTTP to the server |
| Process boundary | none — same process as the host | yes — server can be a subprocess or a remote host |
| Reusable across hosts | no — copy the function into each host | yes — any MCP host can connect to the same server |
| Add a new tool | edit the host's code | edit the server; every connected host sees it via `list_tools()` |
| Failure mode | a Python exception in the host | a network/transport error, independent of the host process |
| Example in this repo | `multiply` in `src/learning_mcp/tool.py` | `add` in `src/learning_mcp/tool.py` |

`src/learning_mcp/tool.py` puts both in one file, on purpose, so the
registration difference is the *only* thing that differs — `add` is
registered on an `MCPServer` with `@server.tool()`, `multiply` is just a
`def`. Running the file with `--serve` makes it act as the MCP server
(the demo spawns `python tool.py --serve` as a subprocess of itself); with
no args, it plays the host: it asks that server's `list_tools()` for `add`,
hands both tools to Ollama in one `tools` list, and dispatches each call the
LLM asks for down its own path:

```python
if name == "multiply":
    result = multiply(**args)                       # local tool: direct call
else:
    response = await session.call_tool(name, args)   # MCP tool: RPC to server
    result = response.content[0].text
```

`multiply` runs immediately, in this process, and returns a real Python
number. `add` is answered by the server subprocess, reached only through
`session.call_tool()`, with the result coming back as text. Run it with:

```bash
uv run learning-mcp-local-vs-mcp
```

## The N×M problem MCP solves

Without a shared protocol, every AI application ("host") that wants to use
external tools has to write its own custom integration for every tool or
data source it wants to support. If you have **N** hosts (Claude Desktop, an
IDE plugin, a custom agent, this repo's `client.py`, ...) and **M** tools
(GitHub, Slack, a database, this repo's `add`/`echo`, ...), that's up to
**N × M** bespoke, one-off integrations — and every new host or new tool
multiplies the remaining work.

```
Without MCP (N x M):                With MCP (N + M):

Host A ─┬─ GitHub integration       Host A ─┐
        ├─ Slack integration        Host B ─┼─▶  MCP protocol  ─┬─▶ GitHub server
        └─ DB integration           Host C ─┘         ▲          ├─▶ Slack server
Host B ─┬─ GitHub integration                         │          └─▶ DB server
        ├─ Slack integration              each side implements
        └─ DB integration                 the protocol once
Host C ─┬─ GitHub integration
        ├─ Slack integration
        └─ DB integration
```

MCP turns N × M into **N + M** by putting a standard protocol in the middle:
each tool/data source is wrapped once as an MCP *server*, and each host
implements the MCP *client* side once. From then on, any client can talk to
any server, because both sides only need to agree on the protocol — not on
each other.

This repo shows both halves of that split. `learning_mcp.server` wasn't
written for any particular host — it just implements the MCP server side. Any
MCP client can connect to it: this repo's own `client.py` (in `--demo` mode,
or driving it through Ollama), or, unmodified, Claude Desktop, Claude Code,
or any other MCP host, simply by pointing it at the server. That's the "M"
side implemented once. Section 4 above (Local tool vs. MCP tool) is really a
zoomed-in view of this: a local tool is the N × M approach — reimplemented
per host — while an MCP tool is written once and reused across every host
that speaks the protocol.

## Why resources and prompts don't fit this loop

Tools map naturally onto LLM function-calling because both are "the model
asks, something executes, a result comes back." Resources (`memo://notes`)
and prompts (`summarize`) don't have an LLM-native equivalent — Ollama's API
has no concept of "discover a resource" or "fetch a prompt template." A host
that wants to use them has to fetch them itself and stuff the content into
the conversation as context, the same way it would read a local file. Run
`uv run learning-mcp-client --demo` to see the server's resource and prompt
being listed and read directly, without any LLM involved.
