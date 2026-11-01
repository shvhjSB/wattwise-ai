"""Bounded HTTP requests and privacy-preserving structured access records."""

import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("wattwise.access")


def configure_access_logging() -> None:
    """Emit JSON without configuring unrelated libraries or logging request payloads."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class RequestLimitsMiddleware:
    """Limit intake and response time; retain capacity for work outliving its HTTP deadline."""

    def __init__(
        self, app: ASGIApp, *, max_bytes: int, timeout_seconds: float, max_concurrent: int
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_concurrent = max_concurrent
        self.tasks: set[asyncio.Task[None]] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        request_id = uuid4().hex
        status = 500
        response_started = False
        expired = False
        error_type: str | None = None

        async def safe_send(message: Message) -> None:
            nonlocal status, response_started
            if expired:
                return
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Cache-Control"] = "no-store"
            await send(message)

        async def error(code: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, status_code=code)(scope, receive, safe_send)

        async def run() -> None:
            nonlocal error_type
            total = 0

            async def limited_receive() -> Message:
                nonlocal total
                remaining = self.timeout_seconds - (time.monotonic() - started)
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(0, remaining))
                except TimeoutError:
                    raise HTTPException(504, "Request deadline exceeded") from None
                if message["type"] == "http.request":
                    total += len(message.get("body", b""))
                    if total > self.max_bytes:
                        raise HTTPException(413, "Request body too large")
                return message

            try:
                await self.app(scope, limited_receive, safe_send)
            except Exception as exc:
                error_type = type(exc).__name__
                if not response_started:
                    await error(500, "Internal server error")

        def finished(task: asyncio.Task[None]) -> None:
            self.tasks.discard(task)
            if not task.cancelled() and (exc := task.exception()) is not None:
                logger.error(
                    json.dumps(
                        {
                            "event": "response_failure",
                            "request_id": request_id,
                            "error_type": type(exc).__name__,
                        }
                    )
                )

        try:
            lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
            if lengths and (
                len(lengths) != 1
                or not lengths[0]
                or len(lengths[0]) > 20
                or not lengths[0].isdigit()
            ):
                await error(400, "Invalid Content-Length")
            elif lengths and int(lengths[0]) > self.max_bytes:
                await error(413, "Request body too large")
            elif len(self.tasks) >= self.max_concurrent:
                await error(503, "Server busy; retry later")
            else:
                task = asyncio.create_task(run())
                self.tasks.add(task)
                task.add_done_callback(finished)
                completed, _ = await asyncio.wait({task}, timeout=self.timeout_seconds)
                if completed:
                    await task
                else:
                    if not response_started:
                        await error(504, "Request deadline exceeded")
                    expired = True
        finally:
            expired = True
            route = scope.get("route")
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                        "error_type": error_type,
                    }
                )
            )
