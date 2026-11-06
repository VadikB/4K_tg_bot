import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.projects import AccessDeniedError, TelegramIdentity, normalize_project_code
from app.domain.enums import CrispDmStage
from app.integrations.agent4k import Agent4KPort
from app.models import (
    AuditEvent,
    ParticipantRole,
    Project,
    ProjectParticipant,
    ProjectRole,
    ProjectRoleVersion,
    User,
    UserSystemRole,
)

ROLE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
ALLOWED_STAGES = frozenset(stage.value for stage in CrispDmStage)


class RoleError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoleDraft:
    code: str
    name: str
    mission: str
    responsibilities: tuple[str, ...]
    typical_tasks: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    interactions: tuple[str, ...]
    crisp_dm_stages: tuple[str, ...]
    agent4k_role_profile_version_id: int
    agent4k_role_profile_checksum: str


@dataclass(frozen=True)
class RoleView:
    code: str
    name: str
    version: int
    status: str
    checksum: str


@dataclass(frozen=True)
class RoleAssignmentResult:
    participant_id: int
    role_code: str
    role_version: int
    is_primary: bool
    created: bool


@dataclass(frozen=True)
class AssignedRoleView:
    project_code: str
    role_code: str
    role_name: str
    role_version: int
    is_primary: bool


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def definition_checksum(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_items(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(";") if item.strip())
    if not items:
        raise ValueError("Укажите хотя бы один пункт, разделяя пункты ';'.")
    if any(len(item) > 500 for item in items):
        raise ValueError("Один пункт не должен превышать 500 символов.")
    return items


def validate_role_draft(draft: RoleDraft) -> RoleDraft:
    code = draft.code.strip().lower().replace(" ", "-")
    if not ROLE_CODE_RE.fullmatch(code):
        raise ValueError("Код роли: 3–64 символа a–z, 0–9, '-' или '_'.")
    if not draft.name.strip() or len(draft.name.strip()) > 255:
        raise ValueError("Название роли должно содержать от 1 до 255 символов.")
    if not draft.mission.strip() or len(draft.mission.strip()) > 2000:
        raise ValueError("Миссия роли должна содержать от 1 до 2000 символов.")
    collections = (
        draft.responsibilities,
        draft.typical_tasks,
        draft.expected_outputs,
        draft.interactions,
        draft.crisp_dm_stages,
    )
    if any(not items for items in collections):
        raise ValueError("Все разделы роли должны содержать хотя бы один пункт.")
    stages = tuple(dict.fromkeys(item.strip().lower() for item in draft.crisp_dm_stages))
    unknown = set(stages) - ALLOWED_STAGES
    if unknown:
        raise ValueError(f"Неизвестные стадии CRISP-DM: {', '.join(sorted(unknown))}.")
    if draft.agent4k_role_profile_version_id <= 0:
        raise ValueError("Выберите опубликованную версию роли 4К.")
    role_checksum = draft.agent4k_role_profile_checksum.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", role_checksum):
        raise ValueError("Checksum версии роли 4К должен быть SHA-256.")
    return RoleDraft(
        code=code,
        name=draft.name.strip(),
        mission=draft.mission.strip(),
        responsibilities=tuple(item.strip() for item in draft.responsibilities),
        typical_tasks=tuple(item.strip() for item in draft.typical_tasks),
        expected_outputs=tuple(item.strip() for item in draft.expected_outputs),
        interactions=tuple(item.strip() for item in draft.interactions),
        crisp_dm_stages=stages,
        agent4k_role_profile_version_id=draft.agent4k_role_profile_version_id,
        agent4k_role_profile_checksum=role_checksum,
    )


async def _require_admin(session: AsyncSession, identity: TelegramIdentity) -> User:
    actor = await session.scalar(
        select(User).where(User.telegram_user_id == identity.telegram_user_id)
    )
    if actor is None or not actor.is_active:
        raise AccessDeniedError("Пользователь не зарегистрирован.")
    if await session.get(UserSystemRole, (actor.id, "admin")) is None:
        raise AccessDeniedError("Управлять ролями может только администратор.")
    return actor


async def _project(session: AsyncSession, code: str) -> Project:
    project = await session.scalar(
        select(Project).where(Project.code == normalize_project_code(code))
    )
    if project is None:
        raise RoleError("Проект с таким кодом не найден.")
    return project


class RoleService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_draft(
        self, identity: TelegramIdentity, *, project_code: str, draft: RoleDraft
    ) -> RoleView:
        validated = validate_role_draft(draft)
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            role = await session.scalar(
                select(ProjectRole)
                .where(ProjectRole.project_id == project.id, ProjectRole.code == validated.code)
                .with_for_update()
            )
            if role is None:
                role = ProjectRole(project_id=project.id, code=validated.code, name=validated.name)
                session.add(role)
                await session.flush()
                version = 1
            else:
                existing_draft = await session.scalar(
                    select(ProjectRoleVersion.id).where(
                        ProjectRoleVersion.project_role_id == role.id,
                        ProjectRoleVersion.status == "draft",
                    )
                )
                if existing_draft is not None:
                    raise RoleError("У роли уже есть draft-версия.")
                latest = await session.scalar(
                    select(func.max(ProjectRoleVersion.version)).where(
                        ProjectRoleVersion.project_role_id == role.id
                    )
                )
                version = int(latest or 0) + 1
                role.name = validated.name
            definition: dict[str, Any] = {
                "schema_version": 1,
                "kind": "project_role",
                "project_code": project.code,
                "code": validated.code,
                "name": validated.name,
                "mission": validated.mission,
                "responsibilities": list(validated.responsibilities),
                "typical_tasks": list(validated.typical_tasks),
                "expected_outputs": list(validated.expected_outputs),
                "interactions": list(validated.interactions),
                "crisp_dm_stages": list(validated.crisp_dm_stages),
                "agent4k_role_profile": {
                    "version_id": validated.agent4k_role_profile_version_id,
                    "checksum": validated.agent4k_role_profile_checksum,
                },
            }
            checksum = definition_checksum(definition)
            role_version = ProjectRoleVersion(
                project_role_id=role.id,
                version=version,
                status="draft",
                definition_json=definition,
                source_json={
                    "formation_method": "teacher_authored",
                    "source_type": "course_project_card",
                    "created_by_user_id": actor.id,
                },
                agent4k_role_profile_version_id=validated.agent4k_role_profile_version_id,
                agent4k_role_profile_checksum=validated.agent4k_role_profile_checksum,
                checksum=checksum,
            )
            session.add(role_version)
            await session.flush()
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_role_version",
                    entity_id=str(role_version.id),
                    action="draft_created",
                    payload_json={"code": validated.code, "version": version},
                )
            )
            return RoleView(validated.code, validated.name, version, "draft", checksum)

    async def publish(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        role_code: str,
        adapter: Agent4KPort,
    ) -> RoleView:
        async with self._session_factory() as session:
            await _require_admin(session, identity)
            project = await _project(session, project_code)
            role = await session.scalar(
                select(ProjectRole).where(
                    ProjectRole.project_id == project.id,
                    ProjectRole.code == role_code.strip().lower(),
                )
            )
            if role is None:
                raise RoleError("Роль не найдена.")
            draft = await session.scalar(
                select(ProjectRoleVersion)
                .where(
                    ProjectRoleVersion.project_role_id == role.id,
                    ProjectRoleVersion.status == "draft",
                )
                .order_by(ProjectRoleVersion.version.desc())
            )
            if draft is None:
                raise RoleError("У роли нет draft-версии для публикации.")
            if (
                draft.agent4k_role_profile_version_id is None
                or draft.agent4k_role_profile_checksum is None
            ):
                raise RoleError("Для роли не задано сопоставление с ролью 4К.")
            mapping_id = draft.agent4k_role_profile_version_id
            mapping_checksum = draft.agent4k_role_profile_checksum

        published_ref = await adapter.get_published_role_profile(version_id=mapping_id)
        if published_ref.id != mapping_id or published_ref.checksum != mapping_checksum:
            raise RoleError("ID или checksum опубликованной роли 4К не совпадает.")

        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            role = await session.scalar(
                select(ProjectRole).where(
                    ProjectRole.project_id == project.id,
                    ProjectRole.code == role_code.strip().lower(),
                )
            )
            if role is None:
                raise RoleError("Роль не найдена.")
            version = await session.scalar(
                select(ProjectRoleVersion)
                .where(
                    ProjectRoleVersion.project_role_id == role.id,
                    ProjectRoleVersion.status == "draft",
                )
                .order_by(ProjectRoleVersion.version.desc())
                .with_for_update()
            )
            if version is None:
                raise RoleError("У роли нет draft-версии для публикации.")
            if (
                version.agent4k_role_profile_version_id != published_ref.id
                or version.agent4k_role_profile_checksum != published_ref.checksum
            ):
                raise RoleError("Сопоставление роли изменилось; повторите проверку.")
            version.status = "published"
            version.published_at = datetime.now(UTC)
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_role_version",
                    entity_id=str(version.id),
                    action="published",
                    payload_json={"code": role.code, "version": version.version},
                )
            )
            return RoleView(role.code, role.name, version.version, version.status, version.checksum)

    async def assign(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        participant_id: int,
        role_code: str,
    ) -> RoleAssignmentResult:
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            participant = await session.get(
                ProjectParticipant, participant_id, with_for_update=True
            )
            if participant is None or participant.project_id != project.id:
                raise RoleError("Участник не найден в этом проекте.")
            role = await session.scalar(
                select(ProjectRole).where(
                    ProjectRole.project_id == project.id,
                    ProjectRole.code == role_code.strip().lower(),
                )
            )
            if role is None:
                raise RoleError("Роль не найдена.")
            version = await session.scalar(
                select(ProjectRoleVersion)
                .where(
                    ProjectRoleVersion.project_role_id == role.id,
                    ProjectRoleVersion.status == "published",
                )
                .order_by(ProjectRoleVersion.version.desc())
            )
            if version is None:
                raise RoleError("Назначить можно только опубликованную роль.")
            existing = await session.get(ParticipantRole, (participant.id, version.id))
            if existing is not None:
                return RoleAssignmentResult(
                    participant.id, role.code, version.version, existing.is_primary, False
                )
            count = await session.scalar(
                select(func.count()).select_from(ParticipantRole).where(
                    ParticipantRole.participant_id == participant.id
                )
            )
            is_primary = int(count or 0) == 0
            session.add(
                ParticipantRole(
                    participant_id=participant.id,
                    project_role_version_id=version.id,
                    is_primary=is_primary,
                    assigned_by_user_id=actor.id,
                )
            )
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="participant_role",
                    entity_id=f"{participant.id}:{version.id}",
                    action="assigned",
                    payload_json={
                        "code": role.code,
                        "version": version.version,
                        "is_primary": is_primary,
                    },
                )
            )
            return RoleAssignmentResult(
                participant.id, role.code, version.version, is_primary, True
            )

    async def list_roles(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> list[RoleView]:
        async with self._session_factory() as session:
            await _require_admin(session, identity)
            project = await _project(session, project_code)
            rows = (
                await session.execute(
                    select(ProjectRole, ProjectRoleVersion)
                    .join(ProjectRoleVersion)
                    .where(ProjectRole.project_id == project.id)
                    .order_by(ProjectRole.code, ProjectRoleVersion.version.desc())
                )
            ).all()
            return [
                RoleView(role.code, role.name, version.version, version.status, version.checksum)
                for role, version in rows
            ]

    async def list_my_roles(self, identity: TelegramIdentity) -> list[AssignedRoleView]:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if user is None or not user.is_active:
                return []
            rows = (
                await session.execute(
                    select(Project, ProjectRole, ProjectRoleVersion, ParticipantRole)
                    .join(ProjectParticipant, ProjectParticipant.project_id == Project.id)
                    .join(
                        ParticipantRole,
                        ParticipantRole.participant_id == ProjectParticipant.id,
                    )
                    .join(
                        ProjectRoleVersion,
                        ProjectRoleVersion.id == ParticipantRole.project_role_version_id,
                    )
                    .join(ProjectRole, ProjectRole.id == ProjectRoleVersion.project_role_id)
                    .where(ProjectParticipant.user_id == user.id)
                    .order_by(Project.code, ParticipantRole.is_primary.desc(), ProjectRole.code)
                )
            ).all()
            return [
                AssignedRoleView(
                    project_code=project.code,
                    role_code=role.code,
                    role_name=role.name,
                    role_version=version.version,
                    is_primary=assignment.is_primary,
                )
                for project, role, version, assignment in rows
            ]
