"""Message bus module for decoupled channel-agent communication."""

from pepperbot.bus.events import InboundMessage, OutboundMessage
from pepperbot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
