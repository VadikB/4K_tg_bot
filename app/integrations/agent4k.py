from dataclasses import dataclass
from typing import Protocol

import httpx


class Agent4KUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseEnvelope:
    cycle_id: str
    session_id: str
    case_id: str
    participant_text: str


@dataclass(frozen=True)
class ParticipantIdentityLink:
    agent4k_user_id: int
    status: str


class Agent4KPort(Protocol):
    async def resolve_participant(
        self, *, email: str, display_name: str
    ) -> ParticipantIdentityLink: ...

    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope: ...


class DisabledAgent4KAdapter:
    async def resolve_participant(
        self, *, email: str, display_name: str
    ) -> ParticipantIdentityLink:
        del email, display_name
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope:
        del cycle_id, idempotency_key
        raise Agent4KUnavailableError("Agent4K integration is disabled")


class HttpAgent4KAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def resolve_participant(
        self, *, email: str, display_name: str
    ) -> ParticipantIdentityLink:
        try:
            response = await self._client.post(
                "/integration/v1/participants/resolve",
                json={"email": email, "display_name": display_name},
            )
            response.raise_for_status()
            payload = response.json()
            return ParticipantIdentityLink(
                agent4k_user_id=int(payload["agent4k_user_id"]),
                status=str(payload["status"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K participant identity request failed") from exc

    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope:
        try:
            response = await self._client.post(
                f"/integration/cycles/{cycle_id}/cases/next",
                headers={"Idempotency-Key": idempotency_key},
            )
            response.raise_for_status()
            payload = response.json()
            return CaseEnvelope(
                cycle_id=str(payload["cycle_id"]),
                session_id=str(payload["session_id"]),
                case_id=str(payload["case_id"]),
                participant_text=str(payload["participant_text"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K case request failed") from exc

    async def close(self) -> None:
        await self._client.aclose()

