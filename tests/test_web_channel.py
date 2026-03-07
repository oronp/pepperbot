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
