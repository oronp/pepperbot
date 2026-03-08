"""Tests for WebChannel."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from pepperbot.bus.events import OutboundMessage
from pepperbot.config.schema import WebConfig


@pytest.fixture
def web_config():
    return WebConfig(enabled=True, port=18080, host="127.0.0.1", secret_key="testsecret")


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    return bus


async def test_webchannel_can_be_instantiated(web_config, mock_bus):
    from pepperbot.channels.web import WebChannel
    ch = WebChannel(web_config, mock_bus)
    assert ch.name == "web"
    assert ch.config.port == 18080


async def test_webchannel_send_to_unknown_chat_id_is_noop(web_config, mock_bus):
    from pepperbot.channels.web import WebChannel
    ch = WebChannel(web_config, mock_bus)
    msg = OutboundMessage(channel="web", chat_id="unknown", content="hello")
    # Should not raise
    await ch.send(msg)


async def test_webchannel_send_chunk_to_active_connection(web_config, mock_bus):
    from pepperbot.channels.web import WebChannel
    ch = WebChannel(web_config, mock_bus)

    mock_ws = AsyncMock()
    mock_ws.closed = False
    ch._ws_connections["user1"] = mock_ws

    msg = OutboundMessage(
        channel="web", chat_id="user1", content="hello",
        metadata={"_progress": True},
    )
    await ch.send(msg)
    mock_ws.send_json.assert_called_once_with({"type": "chunk", "content": "hello"})


async def test_webchannel_send_final_message(web_config, mock_bus):
    from pepperbot.channels.web import WebChannel
    ch = WebChannel(web_config, mock_bus)

    mock_ws = AsyncMock()
    mock_ws.closed = False
    ch._ws_connections["user1"] = mock_ws

    msg = OutboundMessage(
        channel="web", chat_id="user1", content="final answer",
        metadata={},
    )
    await ch.send(msg)
    calls = [c.args[0] for c in mock_ws.send_json.call_args_list]
    assert {"type": "message", "content": "final answer"} in calls
    assert {"type": "done"} in calls


async def test_unauthenticated_request_redirects_to_login(web_config, mock_bus):
    from aiohttp.test_utils import TestClient, TestServer
    from aiohttp import web
    from pepperbot.channels.web import WebChannel
    from pepperbot.channels.web.routes import setup_routes, auth_middleware

    app = web.Application(middlewares=[auth_middleware])
    ch = WebChannel(web_config, mock_bus)
    setup_routes(app, ch)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/settings", allow_redirects=False)
        assert resp.status == 302
        assert "/login" in resp.headers.get("Location", "")


async def test_login_with_valid_credentials(tmp_path, web_config, mock_bus):
    from aiohttp.test_utils import TestClient, TestServer
    from aiohttp import web
    from pepperbot.channels.web import WebChannel
    from pepperbot.channels.web.routes import setup_routes, auth_middleware
    from pepperbot.channels.web.auth import hash_password, save_users

    users_file = tmp_path / "users.json"
    save_users([{"username": "oron", "password_hash": hash_password("pass")}], users_file)

    web_config.users_file = str(users_file)
    app = web.Application(middlewares=[auth_middleware])
    ch = WebChannel(web_config, mock_bus)
    setup_routes(app, ch)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/login",
            data={"username": "oron", "password": "pass"},
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers.get("Set-Cookie", "") or resp.cookies


async def test_login_with_invalid_credentials(tmp_path, web_config, mock_bus):
    from aiohttp.test_utils import TestClient, TestServer
    from aiohttp import web
    from pepperbot.channels.web import WebChannel
    from pepperbot.channels.web.routes import setup_routes, auth_middleware
    from pepperbot.channels.web.auth import hash_password, save_users

    users_file = tmp_path / "users.json"
    save_users([{"username": "oron", "password_hash": hash_password("pass")}], users_file)

    web_config.users_file = str(users_file)
    app = web.Application(middlewares=[auth_middleware])
    ch = WebChannel(web_config, mock_bus)
    setup_routes(app, ch)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/login",
            data={"username": "oron", "password": "wrong"},
            allow_redirects=False,
        )
        assert resp.status in (200, 401)


async def _make_authed_client(tmp_path, web_config, mock_bus):
    """Helper: create a TestClient with a valid session cookie pre-set."""
    from aiohttp.test_utils import TestClient, TestServer
    from aiohttp import web
    from pepperbot.channels.web import WebChannel
    from pepperbot.channels.web.routes import setup_routes, auth_middleware, _CHANNEL_KEY
    from pepperbot.channels.web.auth import hash_password, save_users, sign_session

    users_file = tmp_path / "users.json"
    save_users([{"username": "oron", "password_hash": hash_password("pass")}], users_file)
    web_config.users_file = str(users_file)

    app = web.Application(middlewares=[auth_middleware])
    ch = WebChannel(web_config, mock_bus)
    setup_routes(app, ch)

    client = TestClient(TestServer(app))
    await client.start_server()

    # Set session cookie manually
    token = sign_session({"username": "oron"}, secret=web_config.secret_key)
    client.session.cookie_jar.update_cookies({"pepperbot_session": token})
    return client


async def test_get_usage_returns_empty_list(tmp_path, web_config, mock_bus):
    web_config.workspace = str(tmp_path)
    client = await _make_authed_client(tmp_path, web_config, mock_bus)
    async with client:
        resp = await client.get("/api/usage")
        assert resp.status == 200
        data = await resp.json()
        assert data == []


async def test_get_profile_returns_soul_content(tmp_path, web_config, mock_bus):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("You are a helpful assistant.")
    web_config.workspace = str(tmp_path)

    client = await _make_authed_client(tmp_path, web_config, mock_bus)
    async with client:
        resp = await client.get("/api/profile")
        assert resp.status == 200
        data = await resp.json()
        assert data["content"] == "You are a helpful assistant."


async def test_post_profile_updates_soul(tmp_path, web_config, mock_bus):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("old content")
    web_config.workspace = str(tmp_path)

    client = await _make_authed_client(tmp_path, web_config, mock_bus)
    async with client:
        resp = await client.post("/api/profile", json={"content": "new persona"})
        assert resp.status == 200
        assert soul_file.read_text() == "new persona"


async def test_get_settings_returns_dict(tmp_path, web_config, mock_bus):
    web_config.workspace = str(tmp_path)
    client = await _make_authed_client(tmp_path, web_config, mock_bus)
    async with client:
        resp = await client.get("/api/settings")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, dict)


async def test_post_settings_rejects_invalid_json(tmp_path, web_config, mock_bus):
    web_config.workspace = str(tmp_path)
    client = await _make_authed_client(tmp_path, web_config, mock_bus)
    async with client:
        resp = await client.post("/api/settings", json={"invalid_top_level_key": "bad"})
        # Either 200 (Pydantic extra=ignore) or 400 — either is acceptable
        # Key requirement: must NOT crash with 500
        assert resp.status in (200, 400)


async def test_websocket_requires_auth(tmp_path, web_config, mock_bus):
    from aiohttp.test_utils import TestClient, TestServer
    from aiohttp import web
    from pepperbot.channels.web import WebChannel
    from pepperbot.channels.web.routes import setup_routes, auth_middleware

    app = web.Application(middlewares=[auth_middleware])
    ch = WebChannel(web_config, mock_bus)
    setup_routes(app, ch)

    async with TestClient(TestServer(app)) as client:
        # No session cookie — middleware should redirect to /login
        resp = await client.get("/ws", allow_redirects=False)
        assert resp.status == 302
        assert "/login" in resp.headers.get("Location", "")
