import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from wattwise.api.main import create_app
from wattwise.api.security import RequestLimitsMiddleware
from wattwise.core.config import Settings

ORIGIN = "https://dashboard.example"


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example",
        "null",
        "https://example/",
        "https://u:p@example",
        "ftp://example",
        "https://example?q=x",
        "https://example#x",
        "https://example:bad",
        "https://example\n",
        "https://example?",
        "https://example#",
        "https://example:",
        "https://example\\invalid",
    ],
)
def test_cors_rejects_non_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins=(origin,))


def test_cors_allowlist_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATTWISE_CORS_ORIGINS", '["https://dashboard.example"]')
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"Origin": ORIGIN})
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert "access-control-allow-credentials" not in response.headers
        for origin in ["https://evil.example", "null"]:
            response = client.get("/api/v1/health", headers={"Origin": origin})
            assert "access-control-allow-origin" not in response.headers
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400


def test_cors_is_closed_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("length", ["-1", "not-a-number", "9" * 5000, "1,1"])
def test_invalid_content_length_is_rejected(client: TestClient, length: str) -> None:
    response = client.get("/api/v1/health", headers={"Content-Length": length})
    assert response.status_code == 400


def test_duplicate_content_length_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health", headers=[("Content-Length", "0"), ("Content-Length", "0")]
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "field", ["max_request_bytes", "request_timeout_seconds", "max_concurrent_requests"]
)
def test_limits_must_be_positive(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"WATTWISE_{field.upper()}", "0")
    with pytest.raises(ValidationError):
        Settings()


def body_app() -> FastAPI:
    app = create_app(Settings(environment="test", max_request_bytes=10))

    @app.post("/body")
    async def body(request: Request) -> dict[str, int]:
        return {"length": len(await request.body())}

    return app


def test_declared_request_size_is_checked_before_routing() -> None:
    with TestClient(body_app()) as client:
        assert client.post("/unknown", content=b"x" * 11).status_code == 413
        assert client.post("/body", content=b"x" * 10).json() == {"length": 10}


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_chunked_body_limit_without_trusting_content_length(
    headers: list[tuple[bytes, bytes]],
) -> None:
    async def scenario() -> None:
        messages: list[Message] = [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"123456", "more_body": False},
        ]
        sent: list[Message] = []

        async def receive() -> Message:
            return messages.pop(0)

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/body",
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
        }
        await body_app()(scope, receive, send)
        assert sent[0]["status"] == 413
        assert b"Request body too large" in sent[1]["body"]

    asyncio.run(scenario())


def test_multipart_overflow_is_rejected_while_streaming() -> None:
    async def scenario() -> None:
        from httpx2 import ASGITransport, AsyncClient

        app = create_app(Settings(environment="test", max_request_bytes=256))

        async def stream() -> AsyncIterator[bytes]:
            yield (
                b'--boundary\r\nContent-Disposition: form-data; name="file"; '
                b'filename="test.csv"\r\nContent-Type: text/csv\r\n\r\n'
            )
            yield b"x" * 300
            yield b"\r\n--boundary--\r\n"

        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/data/upload?table=readings",
                content=stream(),
                headers={"Content-Type": "multipart/form-data; boundary=boundary"},
            )
            assert response.status_code == 413

    asyncio.run(scenario())


def test_unexpected_errors_and_validation_do_not_reflect_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(Settings(environment="test", cors_origins=(ORIGIN,)))

    @app.get("/fail/{private_value}")
    async def fail(private_value: str) -> None:
        raise RuntimeError("password=secret-value /private/registry")

    @app.get("/validate")
    async def validate(value: int) -> dict[str, int]:
        return {"value": value}

    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="wattwise.access"):
        response = client.get("/fail/secret-path?token=secret-query", headers={"Origin": ORIGIN})
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        record = json.loads(
            [entry.message for entry in caplog.records if entry.name == "wattwise.access"][-1]
        )
        assert record["route"] == "/fail/{private_value}"
        assert record["status"] == 500
        assert record["error_type"] == "RuntimeError"
        assert record["request_id"] == response.headers["x-request-id"]
        assert "secret" not in json.dumps(record)
        invalid = client.get("/validate?value=secret-value")
        assert invalid.status_code == 422
        assert "secret-value" not in invalid.text
        assert "input" not in invalid.json()["detail"][0]


def test_request_ids_are_generated_not_reflected(client: TestClient) -> None:
    first = client.get("/api/v1/health", headers={"X-Request-ID": "untrusted"})
    second = client.get("/api/v1/health")
    assert len(first.headers["x-request-id"]) == 32
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.parametrize("threaded", [False, True])
def test_timeout_retains_capacity_until_work_finishes_and_suppresses_late_response(
    threaded: bool,
) -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        thread_release = threading.Event()

        async def slow(scope: Scope, receive: Receive, send: Send) -> None:
            if threaded:
                await asyncio.to_thread(thread_release.wait)
            else:
                await release.wait()
            await JSONResponse({"late": True})(scope, receive, send)

        app = RequestLimitsMiddleware(slow, max_bytes=10, timeout_seconds=0.02, max_concurrent=1)
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b""}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {"type": "http", "method": "GET", "headers": []}
        await app(scope, receive, send)
        assert sent[0]["status"] == 504
        assert len(app.tasks) == 1
        sent.clear()
        await app(scope, receive, send)
        assert sent[0]["status"] == 503
        sent.clear()
        release.set()
        thread_release.set()
        await asyncio.gather(*app.tasks)
        await asyncio.sleep(0)
        assert not app.tasks
        assert not sent

    asyncio.run(scenario())


def test_slow_request_body_hits_deadline() -> None:
    async def scenario() -> None:
        app = create_app(Settings(environment="test", request_timeout_seconds=0.02))

        @app.post("/body")
        async def body(request: Request) -> dict[str, int]:
            return {"length": len(await request.body())}

        async def stream() -> AsyncIterator[bytes]:
            await asyncio.sleep(0.2)
            yield b"late"

        from httpx2 import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/body", content=stream())
            assert response.status_code == 504

    asyncio.run(scenario())
