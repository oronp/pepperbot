"""aiohttp route setup for the web UI channel. Populated in later tasks."""

from __future__ import annotations

from aiohttp import web


def setup_routes(app: web.Application, channel) -> None:
    """Register all routes on *app*. *channel* is the WebChannel instance."""
    app["channel"] = channel
