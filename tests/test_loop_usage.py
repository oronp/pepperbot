"""Tests that the agent loop threads usage data into the final OutboundMessage."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from pepperbot.agent.loop import AgentLoop
from pepperbot.providers.base import LLMResponse


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    provider = MagicMock()
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    loop = AgentLoop.__new__(AgentLoop)
    loop.provider = provider
    loop.model = "test-model"
    loop.temperature = 0.0
    loop.max_tokens = 100
    loop.max_iterations = 5
    loop.reasoning_effort = None
    loop.tools = MagicMock()
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.context = MagicMock()
    loop.context.add_assistant_message = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)
    return loop


@pytest.mark.asyncio
async def test_run_agent_loop_returns_usage():
    loop = _make_loop()
    loop.provider.chat = AsyncMock(return_value=LLMResponse(
        content="Hello",
        tool_calls=[],
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    ))
    _, _, _, usage = await loop._run_agent_loop([{"role": "user", "content": "hi"}])
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["requests"] == 1
    assert usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_run_agent_loop_accumulates_usage_across_iterations():
    loop = _make_loop()
    call_count = 0

    async def fake_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: tool call response
            tc = MagicMock()
            tc.id = "tc1"
            tc.name = "test_tool"
            tc.arguments = {}
            return LLMResponse(
                content="",
                tool_calls=[tc],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        else:
            return LLMResponse(
                content="Done",
                tool_calls=[],
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            )

    loop.provider.chat = fake_chat
    loop.tools.execute = AsyncMock(return_value="tool result")
    loop.context.add_tool_result = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)

    _, _, _, usage = await loop._run_agent_loop([{"role": "user", "content": "hi"}])
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 13
    assert usage["requests"] == 2
    assert usage["total_tokens"] == 43  # 15 + 28
