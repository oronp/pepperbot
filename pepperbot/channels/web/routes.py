"""aiohttp route setup for the web UI channel."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from pepperbot.channels.web.auth import authenticate, sign_session, verify_session

_COOKIE_NAME = "pepperbot_session"
_LOGIN_HTML = Path(__file__).parent / "static" / "login.html"
_CHANNEL_KEY: web.AppKey = web.AppKey("channel")


def _get_session(request: web.Request) -> dict | None:
    channel = request.app[_CHANNEL_KEY]
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    return verify_session(token, secret=channel.config.secret_key)


def _set_session(response: web.Response, payload: dict, secret: str) -> None:
    token = sign_session(payload, secret=secret)
    response.set_cookie(
        _COOKIE_NAME,
        token,
        httponly=True,
        samesite="Strict",
        max_age=60 * 60 * 24 * 7,  # 1 week
    )


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Reject unauthenticated requests to protected routes."""
    public = {"/login", "/logout", "/favicon.ico"}
    if request.path in public or request.path.startswith("/static"):
        return await handler(request)

    session = _get_session(request)
    if session is None:
        raise web.HTTPFound("/login")

    request["session"] = session
    return await handler(request)


async def handle_login_get(request: web.Request) -> web.Response:
    html = _LOGIN_HTML.read_text().replace("{error}", "")
    return web.Response(text=html, content_type="text/html")


async def handle_login_post(request: web.Request) -> web.Response:
    channel = request.app[_CHANNEL_KEY]
    data = await request.post()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    users_file = Path(channel.config.users_file).expanduser()
    if authenticate(username, password, users_file):
        resp = web.HTTPFound("/")
        _set_session(resp, {"username": username}, channel.config.secret_key)
        raise resp

    html = _LOGIN_HTML.read_text().replace(
        "{error}", '<p class="error">Invalid username or password.</p>'
    )
    return web.Response(text=html, content_type="text/html", status=401)


async def handle_logout(request: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    resp.del_cookie(_COOKIE_NAME)
    raise resp


def _redact(obj, keys: set, depth: int = 0) -> None:
    """Recursively redact sensitive keys in a dict."""
    if depth > 10 or not isinstance(obj, dict):
        return
    for k in list(obj.keys()):
        if any(s in k.lower() for s in keys):
            obj[k] = "***"
        else:
            _redact(obj[k], keys, depth + 1)


async def handle_get_settings(request: web.Request) -> web.Response:
    config_file = Path("~/.pepperbot/config.json").expanduser()
    if not config_file.exists():
        return web.json_response({})
    raw = json.loads(config_file.read_text())
    _redact(raw, {"password", "token", "api_key", "secret", "apikey", "secretkey"})
    return web.json_response(raw)


async def handle_post_settings(request: web.Request) -> web.Response:
    from pepperbot.config.schema import Config

    body = await request.json()
    config_file = Path("~/.pepperbot/config.json").expanduser()
    try:
        Config.model_validate(body)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(body, indent=2))
    return web.json_response({"ok": True})


async def handle_get_usage(request: web.Request) -> web.Response:
    from pepperbot.channels.web.usage import get_usage_summary

    channel = request.app[_CHANNEL_KEY]
    workspace = Path(channel.config.workspace).expanduser()
    log_file = workspace / "usage.jsonl"
    return web.json_response(get_usage_summary(log_file))


async def handle_get_profile(request: web.Request) -> web.Response:
    channel = request.app[_CHANNEL_KEY]
    workspace = Path(channel.config.workspace).expanduser()
    soul_file = workspace / "SOUL.md"
    content = soul_file.read_text() if soul_file.exists() else ""
    return web.json_response({"content": content})


async def handle_post_profile(request: web.Request) -> web.Response:
    channel = request.app[_CHANNEL_KEY]
    workspace = Path(channel.config.workspace).expanduser()
    soul_file = workspace / "SOUL.md"
    body = await request.json()
    content = body.get("content", "")
    soul_file.parent.mkdir(parents=True, exist_ok=True)
    soul_file.write_text(content)
    return web.json_response({"ok": True})


def setup_routes(app: web.Application, channel) -> None:
    """Register all routes on *app*. Middleware is set at Application creation."""
    app[_CHANNEL_KEY] = channel
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/api/settings", handle_get_settings)
    app.router.add_post("/api/settings", handle_post_settings)
    app.router.add_get("/api/usage", handle_get_usage)
    app.router.add_get("/api/profile", handle_get_profile)
    app.router.add_post("/api/profile", handle_post_profile)
