"""Pieces for the public, read-only demo (T046, D064).

- `ReadOnlyMiddleware`: with `WATTWISE_READ_ONLY=true`, every API request that could change data
  or start work (anything but GET, HEAD and OPTIONS under `/api/`) answers 403 with a plain
  reason. Reviews, uploads and analyses are therefore off on the public site.
- `SecurityHeadersMiddleware`: the headers the Nginx front end adds in the Docker recipes, for the
  single-service deployment where the API serves the frontend itself.
- `mount_frontend`: serves the built React app from `WATTWISE_STATIC_DIR` on the same origin as
  the API, with the single-page-app fallback to `index.html`. Paths under `/api/` are never
  answered with the app, and files are only ever read from inside the directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_DETAIL: Final = (
    "This public demo is read-only: reviews, uploads and analyses are switched off. "
    "Run WattWise locally to use them."
)
SECURITY_HEADERS: Final = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


class ReadOnlyMiddleware:
    """Refuse API requests that are not GET, HEAD or OPTIONS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/api/")
            and scope["method"] not in SAFE_METHODS
        ):
            body = json.dumps({"detail": READ_ONLY_DETAIL}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Add the static security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS:
                    headers[name.decode()] = value.decode()
            await send(message)

        await self.app(scope, receive, with_headers)


def mount_frontend(app: FastAPI, directory: Path) -> None:
    """Serve the built frontend in `directory`; call after the API routers are included."""
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise ValueError(f"WATTWISE_STATIC_DIR has no index.html: {root}")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        if path.startswith("assets/"):  # a missing build file is a 404, not the app
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
