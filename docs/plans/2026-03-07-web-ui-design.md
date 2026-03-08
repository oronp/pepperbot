# Web UI Design

**Issue:** #6 — Build a simple web UI for settings, usage, and agent chat
**Date:** 2026-03-07

## Summary

Add a browser-based UI to pepperbot covering four sections: Chat, Settings, Usage, and Profile. Implemented as a `WebChannel` that integrates into the existing channel/bus architecture. Pure HTML/JS/CSS frontend, no build step.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend web framework | aiohttp | Asyncio-native, handles HTTP + WebSocket, minimal overhead, one new dependency |
| Frontend | Pure HTML/JS/CSS | No build step, fits the lightweight project philosophy |
| Channel integration | WebChannel | Fits existing architecture; bus handles chat routing naturally |
| Auth | Username + password, session cookie | HTTPONLY + SameSite cookie, PBKDF2 password hashing via stdlib |
| User storage | `~/.pepperbot/users.json` | File-based like everything else; naturally extends to multi-user |
| Chat streaming | WebSocket | Already a project dependency; full-duplex, token-by-token streaming |
| Usage data | Tokens + request counts | Append-only `usage.jsonl`, aggregated by provider + day |

## Architecture

`WebChannel` lives in `pepperbot/channels/web.py` and is initialized by `ChannelManager` when `web.enabled: true`. It starts an aiohttp server on a configurable port (default `8080`).

### Chat Flow

1. Browser opens `ws://localhost:8080/ws?session=<chat_id>`
2. Auth middleware validates session cookie
3. User sends `{"type": "message", "content": "..."}` over WS
4. `WebChannel` wraps it as `InboundMessage(channel="web", chat_id=<chat_id>, ...)` and puts it on the `MessageBus`
5. `AgentLoop` processes it and calls `WebChannel.send(OutboundMessage)` for each streamed chunk
6. `WebChannel.send()` looks up the active WS connection by `chat_id` and pushes `{"type": "chunk", "content": "..."}`
7. Final chunk carries `{"type": "done"}` — browser stops the spinner

### Settings Flow

- `GET /api/settings` — reads `config.json`, redacts sensitive fields (passwords, API keys)
- `POST /api/settings` — validates with Pydantic, writes back to `config.json`

### Usage Flow

- `WebChannel.send()` intercepts `OutboundMessage` metadata (token counts from LiteLLM) and appends to `usage.jsonl`:
  ```json
  {"ts": "...", "provider": "openai", "model": "gpt-4o", "input_tokens": 120, "output_tokens": 45, "requests": 1}
  ```
- `GET /api/usage` — aggregates `usage.jsonl` by provider + day and returns totals

### Profile Flow

- `GET /api/profile` — returns contents of `SOUL.md`
- `POST /api/profile` — overwrites `SOUL.md`

### Auth Flow

1. All routes guarded by a custom HMAC-based session middleware (no extra deps)
2. `POST /login` — verifies username/password against `users.json` (PBKDF2), sets `HttpOnly; SameSite=Strict` cookie
3. `GET /logout` — clears cookie, redirects to `/login`
4. First-run: if `users.json` doesn't exist, gateway startup prompts via CLI to create the first user

## Components

### New Files

```
pepperbot/channels/web.py               # WebChannel implementation
pepperbot/channels/web/auth.py          # Session middleware + login logic
pepperbot/channels/web/routes.py        # aiohttp route handlers (REST + WS)
pepperbot/channels/web/usage.py         # Usage tracking: write/read usage.jsonl
pepperbot/channels/web/static/
  index.html                            # Single-page app shell
  app.js                                # Chat, settings, usage, profile logic
  style.css                             # Minimal styling
```

### Modified Files

```
pepperbot/channels/manager.py           # Initialize WebChannel if web.enabled
pepperbot/config/schema.py              # Add WebConfig (port, users_file path)
pyproject.toml                          # Add aiohttp dependency
```

### Runtime Files (created on first run)

```
~/.pepperbot/users.json                 # User credentials (PBKDF2-hashed passwords)
~/.pepperbot/workspace/usage.jsonl      # Append-only usage log
```

## Config Schema Addition

```json
"web": {
  "enabled": true,
  "port": 8080
}
```

Users are managed via `users.json` — not in `config.json` — to keep credentials separate and support future multi-user scenarios.

## Testing Plan

- Unit tests for `auth.py`: hash/verify passwords, middleware accept/reject
- Unit tests for `usage.py`: append line, aggregate by provider + day
- Route handler tests using `aiohttp.test_utils.TestClient`: settings read/write, profile read/write
- Integration test: full WebSocket chat round-trip with a mock `AgentLoop`
- No frontend tests (plain JS, no build step)

## Out of Scope (Future)

- Multi-tenant routing (one agent per user)
- OAuth / SSO
- Usage cost estimation
- Frontend build tooling
