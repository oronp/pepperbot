# Pepperbot Codebase Walkthrough Design

**Date:** 2026-03-06
**Goal:** Build deep, neutral understanding of the pepperbot codebase to support building a hosted multi-tenant agent product.

## Approach

Pure knowledge walkthrough — layered overview first, then progressive depth. Delivered as a conversation, pausing between layers for questions.

## Structure

### Layer 1 — System Identity (~5 min)
What pepperbot is, what it's explicitly NOT, and the core design philosophy (ultra-lightweight, single process, zero database). Sets the mental model for everything else.

### Layer 2 — Architecture Overview (~10 min)
The 5 major subsystems: Bus, Agent, Channels, Providers, Config. A text data-flow diagram tracing the lifecycle of a single message. Why the bus exists as an intermediary.

### Layer 3 — Module Map (~15 min)
Every module explained in 3-4 sentences: what it does, why it exists, and what it connects to. Covers `loop.py`, `context.py`, `memory.py`, `tools/`, `channels/`, `session/`, `cron/`, `heartbeat/`, `providers/`, `config/`.

### Layer 4 — Key Data Structures (~10 min)
The objects that flow through the system: `InboundMessage`, `OutboundMessage`, `Config`, `Session`, the tool interface (`BaseTool`). Understanding these is the fastest path to reading any code in the repo.

### Layer 5 — Execution Flows (~15 min)
Two key flows traced step-by-step through actual code:
1. A user sends a Telegram message → agent responds
2. Agent executes a tool call

### Layer 6 — On-demand deep dives
After Layer 5, deep dives on request: `AgentLoop` internals, memory consolidation, MCP tools, channel lifecycle, provider switching.
