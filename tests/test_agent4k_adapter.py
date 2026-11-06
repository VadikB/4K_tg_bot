import json

import httpx
import pytest

from app.integrations.agent4k import (
    Agent4KUnavailableError,
    DisabledAgent4KAdapter,
    HttpAgent4KAdapter,
)


async def test_disabled_adapter_fails_closed() -> None:
    adapter = DisabledAgent4KAdapter()
    with pytest.raises(Agent4KUnavailableError, match="disabled"):
        await adapter.issue_next_case(cycle_id="cycle-1", idempotency_key="request-1")


async def test_http_adapter_resolves_participant_without_exposing_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/integration/v1/participants/resolve"
        assert request.headers["Authorization"] == "Bearer private-service-token"
        assert json.loads(request.content) == {
            "email": "student@example.edu",
            "display_name": "Студент",
        }
        return httpx.Response(200, json={"agent4k_user_id": 42, "status": "provisioned"})

    adapter = HttpAgent4KAdapter(
        base_url="https://agent4k.example",
        token="private-service-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await adapter.resolve_participant(
            email="student@example.edu",
            display_name="Студент",
        )
    finally:
        await adapter.close()
    assert result.agent4k_user_id == 42
    assert result.status == "provisioned"

