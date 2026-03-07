"""Web UI channel — serves the browser interface via aiohttp."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger

from pepperbot.bus.events import OutboundMessage
from pepperbot.bus.queue import MessageBus
from pepperbot.channels.base import BaseChannel
from pepperbot.config.schema import WebConfig


class WebChannel(BaseChannel):
    """Browser-based UI channel served over HTTP + WebSocket."""

    name = "web"

    def __init__(self, config: WebConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._ws_connections: dict[str, Any] = {}  # chat_id -> WebSocketResponse

    async def start(self) -> None:
        from pepperbot.channels.web.routes import auth_middleware, setup_routes

        static_dir = Path(__file__).parent / "static"

        self._app = web.Application(middlewares=[auth_middleware])
        setup_routes(self._app, self)
        if static_dir.exists():
            self._app.router.add_static("/static", static_dir, name="static")

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        self._running = True
        logger.info("Web UI available at http://{}:{}", self.config.host, self.config.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        ws = self._ws_connections.get(msg.chat_id)
        if ws is None or ws.closed:
            return

        is_progress = msg.metadata.get("_progress", False)
        is_tool_hint = msg.metadata.get("_tool_hint", False)

        try:
            if is_progress and not is_tool_hint:
                await ws.send_json({"type": "chunk", "content": msg.content})
            elif not is_progress:
                # Final message — send content then done signal
                await ws.send_json({"type": "message", "content": msg.content})
                await ws.send_json({"type": "done"})
        except Exception:
            logger.exception("WebChannel.send() error for chat_id={}", msg.chat_id)
