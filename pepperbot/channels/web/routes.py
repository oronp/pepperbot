"""aiohttp route setup for the web UI channel."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from pepperbot.channels.web.auth import authenticate, sign_session, verify_session

_COOKIE_NAME = "pepperbot_session"
_LOGIN_HTML = Path(__file__).parent / "static" / "login.html"


def _get_session(request: web.Request) -> dict | None:
    channel = request.app["channel"]
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
    channel = request.app["channel"]
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


def setup_routes(app: web.Application, channel) -> None:
    """Register all routes on *app*. Middleware is set at Application creation."""
    app["channel"] = channel
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_get("/logout", handle_logout)
