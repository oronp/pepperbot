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
