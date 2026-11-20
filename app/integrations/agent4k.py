from dataclasses import dataclass
from typing import Protocol

import httpx


class Agent4KUnavailableError(RuntimeError):
    pass


class Agent4KChannelActionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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


@dataclass(frozen=True)
class ChannelProgress:
    status: str
    completed: int
    required: int
    remaining: int
    next_available_at: str | None


@dataclass(frozen=True)
class ChannelNextAction:
    action_id: str
    action_type: str
    participant_payload: dict[str, object] | None
    trace: dict[str, object] | None
    input: dict[str, object]


@dataclass(frozen=True)
class EducationalChannelState:
    assignment_ref: str
    cycle_id: str | None
    state: str
    revision: int
    next_action: ChannelNextAction | None
    progress: ChannelProgress | None


def _parse_channel_state(payload: dict[str, object]) -> EducationalChannelState:
    raw_action = payload.get("next_action")
    raw_progress = payload.get("progress")
    next_action = None
    if isinstance(raw_action, dict):
        presentation = raw_action["presentation"]
        if not isinstance(presentation, dict):
            raise TypeError("channel presentation must be an object")
        next_action = ChannelNextAction(
            action_id=str(raw_action["action_id"]),
            action_type=str(raw_action["type"]),
            participant_payload=(
                dict(presentation["participant_payload"])
                if presentation.get("participant_payload") is not None
                else None
            ),
            trace=(
                dict(presentation["trace"])
                if presentation.get("trace") is not None
                else None
            ),
            input=dict(presentation["input"]),
        )
    progress = None
    if isinstance(raw_progress, dict):
        progress = ChannelProgress(
            status=str(raw_progress["status"]),
            completed=int(raw_progress["completed"]),
            required=int(raw_progress["required"]),
            remaining=int(raw_progress["remaining"]),
            next_available_at=(
                str(raw_progress["next_available_at"])
                if raw_progress.get("next_available_at")
                else None
            ),
        )
    return EducationalChannelState(
        assignment_ref=str(payload["assignment_ref"]),
        cycle_id=str(payload["cycle_id"]) if payload.get("cycle_id") else None,
        state=str(payload["state"]),
        revision=int(str(payload["revision"])),
        next_action=next_action,
        progress=progress,
    )


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

    async def read_educational_channel_state(
        self, *, assignment_ref: str
    ) -> EducationalChannelState: ...

    async def apply_educational_channel_action(
        self,
        *,
        assignment_ref: str,
        action_id: str,
        expected_revision: int,
        action_input: dict[str, object],
        idempotency_key: str,
    ) -> EducationalChannelState: ...

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

    async def read_educational_channel_state(
        self, *, assignment_ref: str
    ) -> EducationalChannelState:
        del assignment_ref
        raise Agent4KUnavailableError("Agent4K integration is disabled")

    async def apply_educational_channel_action(
        self,
        *,
        assignment_ref: str,
        action_id: str,
        expected_revision: int,
        action_input: dict[str, object],
        idempotency_key: str,
    ) -> EducationalChannelState:
        del assignment_ref, action_id, expected_revision, action_input, idempotency_key
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
        del email, display_name
        raise Agent4KUnavailableError("Email-based participant identity request is disabled")

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

    async def read_educational_channel_state(
        self, *, assignment_ref: str
    ) -> EducationalChannelState:
        try:
            response = await self._client.get(
                f"/integration/v1/educational-assignments/{assignment_ref}/channel-state"
            )
            response.raise_for_status()
            return _parse_channel_state(response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K channel state request failed") from exc

    async def apply_educational_channel_action(
        self,
        *,
        assignment_ref: str,
        action_id: str,
        expected_revision: int,
        action_input: dict[str, object],
        idempotency_key: str,
    ) -> EducationalChannelState:
        try:
            response = await self._client.post(
                f"/integration/v1/educational-assignments/{assignment_ref}/channel-actions",
                headers={"Idempotency-Key": idempotency_key},
                json={
                    "schema_version": 1,
                    "action_id": action_id,
                    "expected_revision": expected_revision,
                    "input": action_input,
                },
            )
            response.raise_for_status()
            return _parse_channel_state(response.json())
        except httpx.HTTPStatusError as exc:
            try:
                code = exc.response.json().get("detail")
            except (ValueError, TypeError):
                code = None
            if exc.response.status_code in {404, 409, 422} and isinstance(code, str) and code in {
                "EDUCATIONAL_ASSIGNMENT_NOT_FOUND",
                "STALE_CHANNEL_REVISION",
                "ACTION_NOT_CURRENT",
                "IDEMPOTENCY_CONFLICT",
                "ACTION_INPUT_INVALID",
            }:
                raise Agent4KChannelActionError(code) from exc
            raise Agent4KUnavailableError("Agent4K channel action request failed") from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise Agent4KUnavailableError("Agent4K channel action request failed") from exc

    async def close(self) -> None:
        await self._client.aclose()
