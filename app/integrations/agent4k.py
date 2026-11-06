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


class Agent4KPort(Protocol):
    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope: ...


class DisabledAgent4KAdapter:
    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope:
        del cycle_id, idempotency_key
        raise Agent4KUnavailableError("Agent4K integration is disabled")


class HttpAgent4KAdapter:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )

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

