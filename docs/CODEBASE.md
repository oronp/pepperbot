# Pepperbot Codebase Guide

A complete reference for understanding the pepperbot codebase. Covers architecture, every module, key data structures, and exact execution flows through the code.

---

## Layer 1 — System Identity

### What pepperbot is

pepperbot is a **personal AI assistant runtime**. You give it an LLM API key, configure a chat channel (e.g. Telegram bot token), and it runs a persistent process that:
- listens for messages from that channel
- sends them through an LLM with tool-use capability
- returns the response

### What it explicitly is NOT

- **Not a framework or SDK.** It's an application you run, not a library you import.
- **Not multi-user.** One instance = one person's assistant. `allow_from` is a security filter, not user management.
- **Not a database-backed system.** All state is plain files: JSON for config/sessions/cron, Markdown for memory.
- **Not microservices.** Everything runs in a single Python asyncio process.

### Design philosophy

1. **~4,000 lines of core code.** Actively guarded constraint.
2. **Zero infrastructure dependencies.** Run with `pepperbot gateway`. No external services required.
3. **Readable over clever.** Simple code, easy to fork and modify.
4. **Workspace = filesystem.** Memory, history, persona, and scheduled tasks all live in `~/.pepperbot/workspace/` as plain files the agent can read and write.

### The mental model

> pepperbot is a **message processing loop** wrapped around an LLM, with file-based state and pluggable channels/tools.

---

## Layer 2 — Architecture Overview

### The 5 subsystems

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Channels  │────▶│   Message   │────▶│    Agent    │
│  (inbound)  │     │     Bus     │     │    Loop     │
└─────────────┘     └─────────────┘     └──────┬──────┘
                           ▲                   │
┌─────────────┐            │            ┌──────▼──────┐
│   Channels  │◀───────────┘            │  Providers  │
│  (outbound) │                         │    (LLM)    │
└─────────────┘                         └─────────────┘

         Config loads and wires everything together
```

| Subsystem | Directory | Role |
|-----------|-----------|------|
| **Bus** | `pepperbot/bus/` | In-process async queue. Channels put messages on it; the agent reads from it and puts responses back |
| **Agent** | `pepperbot/agent/` | The core loop. Reads a message, builds context, calls the LLM, executes tools, produces a response |
| **Channels** | `pepperbot/channels/` | Chat platform adapters. Translate platform events into `InboundMessage`s and send `OutboundMessage`s back |
| **Providers** | `pepperbot/providers/` | LLM abstraction. Wraps LiteLLM, custom endpoints, or OAuth providers behind a single `complete()` interface |
| **Config** | `pepperbot/config/` | Pydantic schema loaded from `~/.pepperbot/config.json`. Single source of truth wiring everything at startup |

### Full message lifecycle

```
1. TelegramChannel receives update via long-polling
   └─▶ wraps as InboundMessage(channel="telegram", sender_id="123", chat_id="123", content="Hello")
       └─▶ bus.publish_inbound(msg)

2. AgentLoop.run() consumes the bus
   └─▶ SessionManager loads conversation history for "telegram:123"
       └─▶ ContextBuilder assembles: system prompt + skills + memory + history + new message
           └─▶ provider.complete(messages, tools) → LLM response

3. LLM returns either:
   a) text reply  →  AgentLoop publishes OutboundMessage → bus
   b) tool calls  →  AgentLoop executes each tool, appends result, loops back to step 2
      (up to max_iterations=40)

4. ChannelManager routes OutboundMessage back to TelegramChannel
   └─▶ TelegramChannel sends the message to the user
```

Two asyncio tasks run concurrently:
- `agent.run()` — consuming inbound, processing, publishing outbound
- `channels.start_all()` — all channels listening and delivering

### Why the bus exists

1. **Decoupling.** Channels don't know about the agent; agent doesn't know about Telegram.
2. **Multiple channels, one agent.** All 10 channels funnel into the same queue; the agent processes sequentially.
3. **Agent can also send messages.** The `message` tool publishes to the bus, enabling proactive messages from cron/heartbeat.

### Two extra services

- **CronService** (`pepperbot/cron/`) — scheduled jobs. Fires `agent.process_direct()` when a job triggers. Bypasses the bus for invocation; uses bus only for outbound delivery.
- **HeartbeatService** (`pepperbot/heartbeat/`) — wakes every 30 min, reads `HEARTBEAT.md`, runs tasks through the agent.

### Workspace layout

```
~/.pepperbot/workspace/
  MEMORY.md        ← persistent agent memory (agent reads + writes this)
  HEARTBEAT.md     ← tasks to run every 30 min
  SOUL.md          ← agent persona / system prompt addendum
  cron/jobs.json   ← scheduled jobs
  sessions/        ← per-channel conversation history (JSONL per session)
  memory/
    MEMORY.md      ← long-term facts
    HISTORY.md     ← grep-searchable append-only log
```

---

## Layer 3 — Module Map

### `pepperbot/bus/`

**`events.py`** — Defines `InboundMessage` and `OutboundMessage`. These are the only objects that cross the channel ↔ agent boundary. `InboundMessage` carries channel, sender_id, chat_id, text, optional media paths, and an optional `session_key_override` for thread-scoped sessions. `OutboundMessage` carries channel, chat_id, text, and a metadata dict used for internal flags (e.g. `_progress: True` for streaming hints).

**`queue.py`** — `MessageBus`: two `asyncio.Queue` instances (inbound + outbound) with four methods: `publish_inbound`, `consume_inbound`, `publish_outbound`, `consume_outbound`. ~35 lines total. A thread-safe hand-off point, not a broker.

---

### `pepperbot/config/`

**`schema.py`** — Full configuration hierarchy as Pydantic models. Root is `Config` containing `AgentsConfig`, `ChannelsConfig`, `ProvidersConfig`, `ToolsConfig`, `GatewayConfig`. Each channel and provider has its own sub-model. `Config` has helper methods (`get_provider()`, `get_api_key()`) that auto-detect which provider to use by matching model name keywords against the `PROVIDERS` registry. Accepts both camelCase and snake_case keys.

**`loader.py`** — Loads `~/.pepperbot/config.json` into a `Config` object. Handles saving, path resolution, and workspace directory management.

---

### `pepperbot/agent/`

**`loop.py`** (`AgentLoop`) — The core processing engine. Two entry points: `run()` loops forever consuming the bus; `process_direct()` processes one message without the bus (used by cron and heartbeat). Per message: loads session, builds context, calls LLM, loops over tool calls until text response or `max_iterations`. Manages MCP connections via `AsyncExitStack`. Fires memory consolidation as a background task when session window fills up.

**`context.py`** (`ContextBuilder`) — Assembles the exact message list sent to the LLM. System prompt built from: identity block → bootstrap files (SOUL.md, AGENTS.md, etc.) → long-term memory → always-on skills → skills summary. Message list structure: `[system, ...history, user_message]`. Injects runtime context (current time, channel, chat_id) as a prefix on the user message. Encodes media as base64 images.

**`memory.py`** (`MemoryStore`) — Two-layer persistent memory. `MEMORY.md`: curated long-term facts, read every turn. `HISTORY.md`: grep-searchable append-only log. Consolidation: calls the LLM with old messages + a `save_memory` tool; the LLM writes the updated memory and log entry back. Triggered when `session.messages - last_consolidated >= memory_window`.

**`skills.py`** (`SkillsLoader`) — Discovers `SKILL.md` files from `pepperbot/skills/` (built-in) and `workspace/skills/` (user-installed, takes priority). Skills have YAML frontmatter: `description`, `always` (inject every prompt), `requires` (bins/env vars). Skills marked `always=true` are loaded into system prompt on every turn. Others appear as an XML summary so the agent can `read_file` them on demand.

**`subagent.py`** (`SubagentManager`) — Spawns background asyncio tasks. Each subagent has its own mini-agent loop, own tool set (no `message` or `spawn` tools), hard cap of 15 iterations. On completion, injects an `InboundMessage` back onto the bus with `channel="system"` so the main agent summarizes the result for the user.

---

### `pepperbot/agent/tools/`

**`base.py`** (`Tool`) — ABC with: `name`, `description`, `parameters` (JSON Schema), `async execute(**kwargs) -> str`, `to_schema()` (OpenAI function format), `validate_params()`.

**`registry.py`** (`ToolRegistry`) — `dict[str, Tool]` with `register()`, `get_definitions()`, `execute()`. Dispatches tool calls by name.

**`filesystem.py`** — `read_file`, `write_file`, `edit_file` (exact string replacement), `list_dir`. All respect `allowed_dir` guard when `restrict_to_workspace=True`.

**`shell.py`** (`ExecTool`) — Runs shell commands via `asyncio.create_subprocess_shell`. Configurable timeout (default 60s).

**`web.py`** — `WebSearchTool`: calls Brave Search API. `WebFetchTool`: fetches URL, converts HTML to markdown. Both support HTTP/SOCKS5 proxy.

**`message.py`** (`MessageTool`) — Agent's way to proactively send to a channel. Publishes `OutboundMessage` to the bus. Tracks `_sent_in_turn` to avoid duplicate replies from the cron service.

**`cron.py`** (`CronTool`) — Exposes `schedule_task`, `list_tasks`, `cancel_task` to the agent. Delegates to `CronService`. Guards against re-scheduling during cron execution.

**`mcp.py`** — Dynamically creates tools from connected MCP servers at startup. Tool names prefixed with server name (`myserver__tool_name`). Proxies calls to MCP server via session managed in `AgentLoop`.

**`spawn.py`** (`SpawnTool`) — Delegates to `SubagentManager.spawn()`. Lets the agent offload long-running tasks to background coroutines.

---

### `pepperbot/providers/`

**`base.py`** — `LLMProvider` ABC: `async chat(messages, tools, model, ...) -> LLMResponse`. `LLMResponse` holds `content`, `tool_calls` (list of `ToolCallRequest`), `finish_reason`, optional `reasoning_content`/`thinking_blocks` for thinking-mode models. Has `_sanitize_empty_content()` to fix empty-string content that some providers reject.

**`litellm_provider.py`** — Main provider. Wraps LiteLLM (100+ providers). Handles provider-specific env vars, API base URLs, Anthropic prompt caching headers.

**`custom_provider.py`** — Bypasses LiteLLM, calls any OpenAI-compatible endpoint directly via `httpx`.

**`openai_codex_provider.py`** — OAuth-based Codex provider using `oauth_cli_kit`.

**`registry.py`** — `PROVIDERS` list of `ProviderSpec`: `name`, `label`, `keywords` (for model-name auto-matching), `is_gateway`, `is_oauth`, `is_local`, `default_api_base`. `Config._match_provider()` iterates this to auto-detect provider from model string.

---

### `pepperbot/channels/`

**`base.py`** (`BaseChannel`) — ABC: `start()` (long-running listener), `stop()`, `send(OutboundMessage)`. `is_allowed(sender_id)` checks `config.allow_from` (empty = deny all, `"*"` = allow all). `_handle_message()` runs the allow-check and publishes to bus — every channel calls this.

**`manager.py`** (`ChannelManager`) — Instantiates enabled channels, runs them concurrently. Separate asyncio task consuming outbound bus, routing each message to the correct channel by `msg.channel`.

**Individual channels** — Each implements `BaseChannel`. Pattern: connect to platform API (WebSocket or long-polling) → receive events → call `_handle_message()` → implement `send()`. Complexity varies: Telegram is HTTP polling; Matrix handles E2EE; WhatsApp goes through a local Node.js bridge.

Supported: `telegram`, `discord`, `slack`, `whatsapp`, `email`, `feishu`, `dingtalk`, `qq`, `matrix`, `mochat`.

---

### `pepperbot/session/`

**`manager.py`** — `Session` dataclass: `key` (channel:chat_id), `messages` (append-only list of raw dicts), `last_consolidated` (pointer — messages before this have been written to MEMORY.md). `SessionManager` persists as JSONL files in `workspace/sessions/`, keyed by `channel:chat_id`. In-memory cache avoids repeated disk reads.

`get_history(max_messages)` returns only unconsolidated messages, trimmed to window, always starting on a `user` turn.

---

### `pepperbot/cron/`

**`service.py`** (`CronService`) — Manages `workspace/cron/jobs.json`. Background asyncio loop checks `next_run` timestamps, fires `on_job(job)` callback (set at startup in `gateway`). Supports one-time and repeating jobs.

**`types.py`** — `CronJob` dataclass: id, name, schedule, payload (message, channel, recipient), next_run.

---

### `pepperbot/heartbeat/`

**`service.py`** (`HeartbeatService`) — Wakes every N seconds (default 30 min). Makes a lightweight LLM call to check if `HEARTBEAT.md` has tasks. If yes, runs them through `on_execute`. Delivers results via `on_notify`. Fully independent from the main agent loop.

---

### `pepperbot/cli/`

**`commands.py`** — CLI entry point (Typer). Key commands:
- `onboard` — create config + workspace
- `gateway` — start full server: wires agent + all channels + cron + heartbeat into one asyncio event loop
- `agent` — interact directly, bypassing channels
- `status` — show what's configured

The `gateway` command is where everything gets instantiated and wired.

---

## Layer 4 — Key Data Structures

### `InboundMessage` / `OutboundMessage`

```python
@dataclass
class InboundMessage:
    channel: str           # "telegram", "discord", "slack", etc.
    sender_id: str         # user ID on that platform
    chat_id: str           # which chat/room
    content: str           # message text
    timestamp: datetime
    media: list[str]       # local file paths of downloaded attachments
    metadata: dict         # channel-specific extras (e.g. reply_to_id)
    session_key_override: str | None  # for thread-scoped sessions

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"

@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None
    media: list[str]
    metadata: dict    # {"_progress": True} = streaming hint, not final reply
                      # {"_tool_hint": True} = tool call hint specifically
```

`session_key` is the string linking a message to its conversation history on disk (`"telegram:123456"` → `workspace/sessions/telegram_123456.jsonl`).

---

### `Config` hierarchy

```
Config
├── agents: AgentsConfig
│   └── defaults: AgentDefaults
│       ├── model: str           # "anthropic/claude-opus-4-5"
│       ├── workspace: str       # "~/.pepperbot/workspace"
│       ├── max_tokens: int
│       ├── temperature: float
│       ├── max_tool_iterations: int   # max LLM↔tool loop iterations (default 40)
│       └── memory_window: int         # messages before consolidation (default 100)
│
├── channels: ChannelsConfig
│   ├── send_progress: bool
│   └── telegram / discord / slack / ... (10 channels)
│
├── providers: ProvidersConfig
│   └── anthropic / openai / openrouter / ... (15 providers)
│       each: ProviderConfig(api_key, api_base, extra_headers)
│
├── tools: ToolsConfig
│   ├── web: WebToolsConfig (brave api_key, proxy)
│   ├── exec: ExecToolConfig (timeout, path_append)
│   ├── restrict_to_workspace: bool
│   └── mcp_servers: dict[str, MCPServerConfig]
│
└── gateway: GatewayConfig (host, port, heartbeat interval)
```

Key methods: `get_provider(model)` auto-detects provider by model string. `workspace_path` returns expanded `Path`.

Env var support: `PEPPERBOT_AGENTS__DEFAULTS__MODEL` etc. (prefix + `__` delimiter).

---

### `Session`

```python
@dataclass
class Session:
    key: str                 # "telegram:123456"
    messages: list[dict]     # ALL turns ever — append-only
    last_consolidated: int   # messages[:this] already in MEMORY.md
```

Each message in `messages` is a raw OpenAI-format dict:
```python
{"role": "user",      "content": "Hello",   "timestamp": "2026-03-06T10:00:00"}
{"role": "assistant", "content": "Hi!",     "tool_calls": [...]}
{"role": "tool",      "tool_call_id": "abc", "name": "read_file", "content": "..."}
```

`get_history(max_messages)` — returns `messages[last_consolidated:][-max_messages:]`, always starting on a `user` turn.

Persisted as JSONL: first line = metadata (key, timestamps, `last_consolidated`), then one JSON object per message.

---

### `LLMResponse` / `ToolCallRequest`

```python
@dataclass
class ToolCallRequest:
    id: str           # LLM-assigned ID for matching results back
    name: str         # "read_file"
    arguments: dict   # parsed JSON arguments

@dataclass
class LLMResponse:
    content: str | None           # text reply (None if only tool calls)
    tool_calls: list[ToolCallRequest]
    finish_reason: str            # "stop", "tool_calls", "length", "error"
    usage: dict                   # token counts
    reasoning_content: str | None # DeepSeek-R1, Kimi thinking
    thinking_blocks: list[dict] | None  # Anthropic extended thinking

    @property
    def has_tool_calls(self) -> bool: ...
```

A response can have both `content` and `tool_calls` — the LLM narrating before calling a tool.

---

### `Tool` (the tool interface)

```python
class Tool(ABC):
    name: str           # "read_file" — used for dispatch
    description: str    # natural language — what the LLM reads to decide when to use this
    parameters: dict    # JSON Schema for arguments

    async def execute(self, **kwargs) -> str: ...   # always returns string
    def to_schema(self) -> dict: ...                # OpenAI function-calling format
    def validate_params(self, params) -> list[str]: ...
```

`execute()` always returns a string. Errors are returned as error strings — the agent reads them and decides what to do.

`description` is the most important field: it's the natural language the LLM reads to decide when and how to use the tool.

---

## Layer 5 — Execution Flows

### Flow 1: Telegram message → agent response

#### 1. Telegram receives the update
`telegram.py:334` — `_on_message()` fires from long-polling.
- Builds `content` from text/caption
- Downloads media to `~/.pepperbot/media/`
- Starts a typing indicator (sends "typing" action every 4s)
- Calls `_handle_message()` from `BaseChannel`

#### 2. Allow-list check + publish to bus
`base.py:96` — `_handle_message()` calls `is_allowed(sender_id)`. Checks `config.allow_from`. Denied → log warning + return. Allowed → wraps into `InboundMessage` → `bus.publish_inbound(msg)`.

#### 3. Agent loop picks it up
`loop.py:268` — `run()` unblocks from `bus.consume_inbound()`. Checks for `/stop`. Otherwise:
```python
task = asyncio.create_task(self._dispatch(msg))   # loop.py:283
```
Immediately goes back to waiting. Message processed concurrently.

#### 4. Dispatch acquires the processing lock
`loop.py:303` — `_dispatch()` acquires `self._processing_lock` (single `asyncio.Lock` — one message at a time). Calls `_process_message(msg)`.

#### 5. Session + memory window check
`loop.py:369` — Derives session key → `sessions.get_or_create(key)` → loads from JSONL or creates new.

`loop.py:405` — If `len(messages) - last_consolidated >= memory_window`, fires `_consolidate_memory()` as a **background asyncio task** (non-blocking — current message continues).

#### 6. Context building
`loop.py:423` — `_set_tool_context()` updates `message`, `spawn`, `cron` tools with current channel/chat_id.

`loop.py:428` — `session.get_history(max_messages=memory_window)` → `context.build_messages(history, content, media, channel, chat_id)`

`context.py:106` — Assembles:
```
[
  {"role": "system", "content": "<identity + SOUL.md + MEMORY.md + skills>"},
  ...history...,
  {"role": "user", "content": "[Runtime Context — time, channel, chat_id]\n\n<user message>"}
]
```

#### 7. Agent iteration loop
`loop.py:180` — `_run_agent_loop()` calls LLM → `LLMResponse`:

- `has_tool_calls=True` → stream progress hint → execute tools (see Flow 2) → append results → loop
- `has_tool_calls=False` → strip `<think>` blocks → set `final_content` → break
- `max_iterations` hit → return canned message

#### 8. Save turn + publish response
`loop.py:451` — `_save_turn()` appends new messages to `session.messages`. Strips runtime context prefix from user messages. Truncates tool results >500 chars. Images replaced with `[image]` placeholder.

`sessions.save()` rewrites full JSONL to disk.

`loop.py:454` — If `MessageTool._sent_in_turn` is set (agent already replied via `message` tool), returns `None` to avoid duplicate.

Otherwise returns `OutboundMessage(channel="telegram", chat_id="...", content=final_content)`.

#### 9. Channel routing + delivery
`loop.py:308` — `bus.publish_outbound(response)`.

`ChannelManager` consuming outbound queue → matches `msg.channel == "telegram"` → `TelegramChannel.send(msg)`.

`telegram.py:205` — Stops typing indicator. Converts markdown → Telegram HTML. Splits at 4000 chars. Calls `bot.send_message()`.

---

### Flow 2: Agent executes a tool call

Picks up inside `_run_agent_loop()` when `response.has_tool_calls=True`.

#### LLM returns tool calls
```python
LLMResponse(
    content="Let me read that file.",
    tool_calls=[ToolCallRequest(id="call_abc", name="read_file", arguments={"path": "README.md"})]
)
```

#### Progress hint published (`loop.py:204-217`)
`on_progress` fires with `read_file("README.md")` → `OutboundMessage(metadata={"_progress": True, "_tool_hint": True})` → channel shows as streaming update.

#### Assistant message appended (`loop.py:230-234`)
```python
{"role": "assistant", "content": "Let me read that file.", "tool_calls": [...]}
```
Required by the OpenAI API — must echo the assistant's tool call before providing the result.

#### Tool executed (`loop.py:240`)
```python
result = await self.tools.execute(tool_call.name, tool_call.arguments)
```
`ToolRegistry` looks up `"read_file"` → `validate_params()` → `tool.execute(**arguments)` → returns string. Exceptions are caught and returned as error strings.

#### Tool result appended (`loop.py:241-243`)
```python
{"role": "tool", "tool_call_id": "call_abc", "name": "read_file", "content": "<file contents>"}
```

#### Loop continues
Back to top of `while` loop. LLM called again with updated context. Continues until `has_tool_calls=False` or `max_iterations`.

---

### Combined flow diagram

```
[Telegram update]
      │
      ▼
TelegramChannel._on_message()
  allow-check → bus.publish_inbound(InboundMessage)
      │
      ▼
AgentLoop.run() → asyncio.create_task(_dispatch(msg))
  → _processing_lock
  → _process_message(msg)
      │
      ├─ load Session (JSONL from disk)
      ├─ fire memory consolidation if needed (background)
      ├─ build messages [system + history + user]
      │
      ▼
_run_agent_loop(messages)
  ┌──────────────────────────────────────────┐
  │  provider.chat(messages, tools) → LLMResponse  │
  │         │                                │
  │   has_tool_calls?                        │
  │    YES ──────────────────────►           │
  │         publish progress hint            │
  │         append assistant msg             │
  │         tools.execute() → str            │
  │         append tool result               │
  │         loop ↑                           │
  │    NO ──────────────────────►            │
  │         final_content = response.content │
  │         break                            │
  └──────────────────────────────────────────┘
      │
      ├─ _save_turn() → session.messages
      ├─ sessions.save() → JSONL on disk
      │
      ▼
OutboundMessage → bus.publish_outbound()
      │
      ▼
ChannelManager → TelegramChannel.send()
  markdown→HTML → bot.send_message()
      │
      ▼
[User sees reply]
```

---

## Key File Locations

| Concern | File |
|---------|------|
| Entry point / CLI | `pepperbot/cli/commands.py` |
| Core agent loop | `pepperbot/agent/loop.py` |
| Context/prompt assembly | `pepperbot/agent/context.py` |
| Memory system | `pepperbot/agent/memory.py` |
| Skills loading | `pepperbot/agent/skills.py` |
| Subagents | `pepperbot/agent/subagent.py` |
| Tool base class | `pepperbot/agent/tools/base.py` |
| Tool registry | `pepperbot/agent/tools/registry.py` |
| All tools | `pepperbot/agent/tools/` |
| Message bus | `pepperbot/bus/queue.py` |
| Bus events | `pepperbot/bus/events.py` |
| Config schema | `pepperbot/config/schema.py` |
| Config loader | `pepperbot/config/loader.py` |
| Channel base class | `pepperbot/channels/base.py` |
| Channel manager | `pepperbot/channels/manager.py` |
| Session manager | `pepperbot/session/manager.py` |
| Provider base | `pepperbot/providers/base.py` |
| Provider registry | `pepperbot/providers/registry.py` |
| Cron service | `pepperbot/cron/service.py` |
| Heartbeat service | `pepperbot/heartbeat/service.py` |
