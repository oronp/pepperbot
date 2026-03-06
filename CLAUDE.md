# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_loop_save_turn.py

# Run a single test by name
pytest tests/test_loop_save_turn.py::test_name

# Lint
ruff check pepperbot/

# Format / fix lint
ruff check --fix pepperbot/
```

## Architecture

pepperbot is an ultra-lightweight personal AI assistant. The main entry point is `pepperbot/cli/commands.py` (registered as the `pepperbot` console script).

### Data Flow

1. **Channel** (Telegram, Discord, etc.) receives a message and puts an `InboundMessage` on the `MessageBus`.
2. **AgentLoop** (`pepperbot/agent/loop.py`) consumes the bus, builds context, calls the LLM provider, executes tool calls iteratively, and publishes an `OutboundMessage` back to the bus.
3. **ChannelManager** (`pepperbot/channels/manager.py`) picks up the outbound message and routes it to the correct channel.

### Key Modules

- **`pepperbot/agent/loop.py`** — Core agent loop. Iterates LLM ↔ tool execution up to `max_iterations`. Manages session history, memory consolidation, and MCP connections.
- **`pepperbot/agent/context.py`** — Builds the message list sent to the LLM (system prompt, history, current message).
- **`pepperbot/agent/memory.py`** — `MemoryStore`: writes/reads `MEMORY.md` in the workspace; consolidates old session history into persistent memory.
- **`pepperbot/agent/skills.py`** — Loads skill markdown files from `pepperbot/skills/` into the system prompt.
- **`pepperbot/agent/subagent.py`** — `SubagentManager`: runs background tasks via `spawn_agent` tool, isolated from the main session.
- **`pepperbot/agent/tools/`** — Built-in tools: filesystem (read/write/edit/list), shell exec, web search/fetch, message sending, cron scheduling, MCP proxy, and spawn.
- **`pepperbot/providers/`** — LLM provider abstraction. `LiteLLMProvider` wraps LiteLLM for most providers; `CustomProvider` hits any OpenAI-compatible endpoint directly; `OpenAICodexProvider` uses OAuth. `registry.py` is the single source of truth for provider metadata.
- **`pepperbot/channels/`** — Chat platform integrations (Telegram, Discord, WhatsApp, Feishu, Slack, etc.). Each extends `BaseChannel`.
- **`pepperbot/bus/`** — In-process async message bus (`MessageBus`) with `InboundMessage` / `OutboundMessage` events.
- **`pepperbot/session/`** — Per-session conversation history with JSON persistence in the workspace.
- **`pepperbot/cron/`** — Cron job service (stores jobs in `workspace/cron/jobs.json`).
- **`pepperbot/heartbeat/`** — Wakes the agent every 30 min to execute tasks listed in `workspace/HEARTBEAT.md`.
- **`pepperbot/config/`** — Pydantic config schema (`schema.py`) and loader (`loader.py`). Config lives at `~/.pepperbot/config.json`. All config fields accept both camelCase and snake_case.

### Adding a Provider

Two-file change:

1. Add a `ProviderSpec` to `PROVIDERS` in `pepperbot/providers/registry.py`.
2. Add a matching field to `ProvidersConfig` in `pepperbot/config/schema.py`.

### Adding a Channel

Create `pepperbot/channels/mychannel.py` extending `BaseChannel`, then initialize it in `ChannelManager._init_channels()` in `pepperbot/channels/manager.py`.

### Workspace Layout (runtime, at `~/.pepperbot/`)

```
config.json         # user config
workspace/
  MEMORY.md         # persistent agent memory
  HEARTBEAT.md      # periodic task definitions
  SOUL.md           # agent persona
  cron/jobs.json    # scheduled jobs
  sessions/         # per-session conversation history
```

### Skills

Skills are markdown files under `pepperbot/skills/<name>/SKILL.md` that are injected into the system prompt. The agent can install new skills dynamically via the ClawHub skill.

### Tests

Tests use `pytest` with `asyncio_mode = "auto"` (no need to mark tests with `@pytest.mark.asyncio`). Test files live in `tests/`.