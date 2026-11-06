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


async def test_http_adapter_reads_published_role_reference() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/integration/v1/role-profile-versions/17"
        return httpx.Response(
            200,
            json={
                "id": 17,
                "code": "specialist_expert",
                "version": 3,
                "methodology_version": "1.1",
                "checksum": "a" * 64,
            },
        )

    adapter = HttpAgent4KAdapter(
        base_url="https://agent4k.example",
        token="private-service-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await adapter.get_published_role_profile(version_id=17)
    finally:
        await adapter.close()
    assert result.id == 17
    assert result.checksum == "a" * 64


async def test_http_adapter_prepares_educational_context() -> None:
    snapshot = {"assignment_ref": "edu:4k-tg-bot:p1:a2"}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/integration/v1/educational-contexts/prepare"
        assert json.loads(request.content) == {"snapshot": snapshot, "checksum": "a" * 64}
        return httpx.Response(
            200,
            json={
                "operation_id": "educational-context:7",
                "status": "awaiting_admission",
                "organization_id": 3,
                "assignment_id": 9,
                "assignment_ref": "edu:4k-tg-bot:p1:a2",
                "reasons": ["PROGRAM_NOT_CONNECTED"],
                "cycle_id": None,
            },
        )

    adapter = HttpAgent4KAdapter(
        base_url="https://agent4k.example",
        token="private-service-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await adapter.prepare_educational_context(
            snapshot=snapshot, checksum="a" * 64
        )
    finally:
        await adapter.close()
    assert result.status == "awaiting_admission"
    assert result.reasons == ("PROGRAM_NOT_CONNECTED",)

