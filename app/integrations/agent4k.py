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


@dataclass(frozen=True)
class PublishedRoleProfileReference:
    id: int
    code: str
    version: int
    methodology_version: str
    checksum: str


@dataclass(frozen=True)
class EducationalContextPreparation:
    operation_id: str
    status: str
    organization_id: int
    assignment_id: int
    assignment_ref: str
    reasons: tuple[str, ...]
    cycle_id: str | None


@dataclass(frozen=True)
class EducationalProgramOption:
    id: int
    code: str
    version: str
    name: str
    checksum: str


@dataclass(frozen=True)
class EducationalProgramConnection:
    program_definition_id: int
    program_code: str
    program_version: str
    status: str


class Agent4KPort(Protocol):
    async def resolve_participant(
        self, *, email: str, display_name: str
    ) -> ParticipantIdentityLink: ...

    async def get_published_role_profile(
        self, *, version_id: int
    ) -> PublishedRoleProfileReference: ...

    async def prepare_educational_context(
        self, *, snapshot: dict[str, object], checksum: str
    ) -> EducationalContextPreparation: ...

    async def list_educational_programs(
        self, *, assignment_ref: str
    ) -> tuple[EducationalProgramOption, ...]: ...

    async def connect_educational_program(
        self, *, assignment_ref: str, program_definition_id: int, operation_id: str
    ) -> EducationalProgramConnection: ...

    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str) -> CaseEnvelope: ...


class DisabledAgent4KAdapter:
    async def resolve_participant(
        self, *, email: str, display_name: str
    ) -> ParticipantIdentityLink:
        del email, display_name
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def get_published_role_profile(
        self, *, version_id: int
    ) -> PublishedRoleProfileReference:
        del version_id
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def prepare_educational_context(
        self, *, snapshot: dict[str, object], checksum: str
    ) -> EducationalContextPreparation:
        del snapshot, checksum
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def list_educational_programs(
        self, *, assignment_ref: str
    ) -> tuple[EducationalProgramOption, ...]:
        del assignment_ref
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def connect_educational_program(
        self, *, assignment_ref: str, program_definition_id: int, operation_id: str
    ) -> EducationalProgramConnection:
        del assignment_ref, program_definition_id, operation_id
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

    async def get_published_role_profile(
        self, *, version_id: int
    ) -> PublishedRoleProfileReference:
        try:
            response = await self._client.get(
                f"/integration/v1/role-profile-versions/{version_id}"
            )
            response.raise_for_status()
            payload = response.json()
            return PublishedRoleProfileReference(
                id=int(payload["id"]),
                code=str(payload["code"]),
                version=int(payload["version"]),
                methodology_version=str(payload["methodology_version"]),
                checksum=str(payload["checksum"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K role profile request failed") from exc

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

    async def prepare_educational_context(
        self, *, snapshot: dict[str, object], checksum: str
    ) -> EducationalContextPreparation:
        try:
            response = await self._client.post(
                "/integration/v1/educational-contexts/prepare",
                json={"snapshot": snapshot, "checksum": checksum},
            )
            response.raise_for_status()
            payload = response.json()
            return EducationalContextPreparation(
                operation_id=str(payload["operation_id"]),
                status=str(payload["status"]),
                organization_id=int(payload["organization_id"]),
                assignment_id=int(payload["assignment_id"]),
                assignment_ref=str(payload["assignment_ref"]),
                reasons=tuple(str(value) for value in payload.get("reasons", [])),
                cycle_id=str(payload["cycle_id"]) if payload.get("cycle_id") else None,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError(
                "Agent4K educational context request failed"
            ) from exc

    async def list_educational_programs(
        self, *, assignment_ref: str
    ) -> tuple[EducationalProgramOption, ...]:
        try:
            response = await self._client.post(
                "/integration/v1/educational-contexts/program-options",
                json={"assignment_ref": assignment_ref},
            )
            response.raise_for_status()
            return tuple(
                EducationalProgramOption(
                    id=int(item["id"]),
                    code=str(item["code"]),
                    version=str(item["version"]),
                    name=str(item["name"]),
                    checksum=str(item["definition_checksum"]),
                )
                for item in response.json()
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K program options request failed") from exc

    async def connect_educational_program(
        self, *, assignment_ref: str, program_definition_id: int, operation_id: str
    ) -> EducationalProgramConnection:
        try:
            response = await self._client.post(
                "/integration/v1/educational-contexts/connect-program",
                json={
                    "assignment_ref": assignment_ref,
                    "program_definition_id": program_definition_id,
                    "operation_id": operation_id,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return EducationalProgramConnection(
                program_definition_id=int(payload["program_definition_id"]),
                program_code=str(payload["program_code"]),
                program_version=str(payload["program_version"]),
                status=str(payload["status"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K program connection request failed") from exc

    async def close(self) -> None:
        await self._client.aclose()

