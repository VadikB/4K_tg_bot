import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AuditEvent,
    Project,
    ProjectParticipant,
    ProjectRole,
    ProjectRoleVersion,
    User,
    UserSystemRole,
)
from app.role_catalog import CatalogRole, RoleCatalog, load_role_catalog

PROJECT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
EXTERNAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{2,127}$")


class AccessDeniedError(RuntimeError):
    pass


class DuplicateProjectCodeError(RuntimeError):
    pass


class CatalogBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogBackfillPlan:
    project_code: str
    catalog_version: str
    catalog_checksum: str
    fingerprint: str
    missing: tuple[str, ...]
    existing: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: int
    display_name: str
    telegram_username: str | None = None


@dataclass(frozen=True)
class ProjectDraft:
    code: str
    name: str
    course_external_id: str
    course: str
    cohort: str | None
    business_problem: str
    expected_result: str
    description: str
    timezone: str
    starts_on: date | None = None
    ends_on: date | None = None


def normalize_project_code(value: str) -> str:
    return value.strip().upper().replace(" ", "-")


def normalize_external_id(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def validate_project_draft(draft: ProjectDraft) -> ProjectDraft:
    code = normalize_project_code(draft.code)
    if not PROJECT_CODE_RE.fullmatch(code):
        raise ValueError("Код: 3–64 символа A–Z, 0–9, '-' или '_'.")
    course_external_id = normalize_external_id(draft.course_external_id)
    if not EXTERNAL_ID_RE.fullmatch(course_external_id):
        raise ValueError("ID курса: 3–128 символов a–z, 0–9, '.', ':', '-' или '_'.")
    required = {
        "Название": draft.name,
        "Курс": draft.course,
        "Бизнес-проблема": draft.business_problem,
        "Ожидаемый результат": draft.expected_result,
        "Описание": draft.description,
    }
    empty = [name for name, value in required.items() if not value.strip()]
    if empty:
        raise ValueError(f"Не заполнено поле: {empty[0]}.")
    if any(len(value.strip()) > 4000 for value in required.values()):
        raise ValueError("Текстовое поле не должно превышать 4000 символов.")
    try:
        ZoneInfo(draft.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Неизвестный часовой пояс IANA.") from exc
    if draft.starts_on and draft.ends_on and draft.ends_on < draft.starts_on:
        raise ValueError("Дата завершения не может быть раньше даты начала.")
    return ProjectDraft(
        code=code,
        name=draft.name.strip(),
        course_external_id=course_external_id,
        course=draft.course.strip(),
        cohort=draft.cohort.strip() if draft.cohort and draft.cohort.strip() else None,
        business_problem=draft.business_problem.strip(),
        expected_result=draft.expected_result.strip(),
        description=draft.description.strip(),
        timezone=draft.timezone,
        starts_on=draft.starts_on,
        ends_on=draft.ends_on,
    )


def _catalog_definition(
    project_code: str, role: CatalogRole, catalog: RoleCatalog
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "project_role",
        "project_code": project_code,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "interactions": list(role.interactions),
        "crisp_dm_stages": list(role.crisp_dm_phases),
        "role_catalog": {
            "id": catalog.catalog_id,
            "version": catalog.version,
            "checksum": catalog.sha256,
        },
    }


def _checksum(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _add_catalog_role(
    session: AsyncSession,
    project: Project,
    actor_id: int,
    catalog: RoleCatalog,
    catalog_role: CatalogRole,
) -> None:
    role = ProjectRole(project_id=project.id, code=catalog_role.code, name=catalog_role.name)
    session.add(role)
    await session.flush()
    definition = _catalog_definition(project.code, catalog_role, catalog)
    version = ProjectRoleVersion(
        project_role_id=role.id,
        version=1,
        status="published",
        definition_json=definition,
        source_json={
            "formation_method": "semester_catalog",
            "catalog_id": catalog.catalog_id,
            "catalog_version": catalog.version,
            "catalog_checksum": catalog.sha256,
        },
        agent4k_role_profile_version_id=None,
        agent4k_role_profile_checksum=None,
        checksum=_checksum(definition),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    session.add(
        AuditEvent(
            actor_user_id=actor_id,
            project_id=project.id,
            entity_type="project_role_version",
            entity_id=f"{catalog_role.code}:1",
            action="catalog_seeded",
            payload_json={
                "catalog_version": catalog.version,
                "catalog_checksum": catalog.sha256,
                "code": catalog_role.code,
            },
        )
    )


def _backfill_plan(
    project: Project,
    catalog: RoleCatalog,
    rows: list[tuple[ProjectRole, ProjectRoleVersion | None]],
) -> CatalogBackfillPlan:
    by_code: dict[str, list[tuple[ProjectRole, ProjectRoleVersion | None]]] = {}
    fingerprint_rows = []
    for role, version in rows:
        by_code.setdefault(role.code, []).append((role, version))
        fingerprint_rows.append(
            [
                role.id, role.code, role.name,
                version.id if version else None,
                version.version if version else None,
                version.status if version else None,
                version.checksum if version else None,
                version.definition_json if version else None,
                version.source_json if version else None,
                version.agent4k_role_profile_version_id if version else None,
                version.agent4k_role_profile_checksum if version else None,
            ]
        )
    missing, existing, conflicts = [], [], []
    for catalog_role in catalog.roles:
        matches = by_code.get(catalog_role.code)
        if not matches:
            missing.append(catalog_role.code)
            continue
        expected = _catalog_definition(project.code, catalog_role, catalog)
        if any(
            role.name == catalog_role.name
            and version is not None
            and version.version == 1
            and version.status == "published"
            and version.definition_json == expected
            and version.checksum == _checksum(expected)
            and version.source_json.get("formation_method") == "semester_catalog"
            and version.source_json.get("catalog_checksum") == catalog.sha256
            for role, version in matches
        ):
            existing.append(catalog_role.code)
        else:
            conflicts.append(catalog_role.code)
    fingerprint = _checksum(
        {
            "project_id": project.id,
            "project_code": project.code,
            "catalog_checksum": catalog.sha256,
            "rows": sorted(fingerprint_rows, key=lambda row: (row[0], row[3] or 0)),
        }
    )
    return CatalogBackfillPlan(
        project.code, catalog.version, catalog.sha256, fingerprint,
        tuple(missing), tuple(existing), tuple(conflicts),
    )


class ProjectService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        bootstrap_admin_ids: tuple[int, ...],
        superadmin_ids: tuple[int, ...] = (),
    ) -> None:
        self._session_factory = session_factory
        self._bootstrap_admin_ids = frozenset(bootstrap_admin_ids)
        self._superadmin_ids = frozenset(superadmin_ids)

    async def is_superadmin(self, identity: TelegramIdentity) -> bool:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            return bool(
                user is not None
                and user.is_active
                and await session.get(UserSystemRole, (user.id, "superadmin")) is not None
            )

    async def ensure_actor(self, identity: TelegramIdentity) -> tuple[User, bool]:
        async with self._session_factory.begin() as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if user is None:
                user = User(
                    telegram_user_id=identity.telegram_user_id,
                    telegram_username=identity.telegram_username,
                    display_name=identity.display_name,
                )
                session.add(user)
                await session.flush()
            else:
                user.telegram_username = identity.telegram_username
                user.display_name = identity.display_name
            role = await session.get(UserSystemRole, (user.id, "admin"))
            superadmin_role = await session.get(UserSystemRole, (user.id, "superadmin"))
            if identity.telegram_user_id in self._superadmin_ids and superadmin_role is None:
                session.add(UserSystemRole(user_id=user.id, role="superadmin"))
            if role is None and (
                identity.telegram_user_id in self._bootstrap_admin_ids
                or identity.telegram_user_id in self._superadmin_ids
                or superadmin_role is not None
            ):
                session.add(UserSystemRole(user_id=user.id, role="admin"))
                return user, True
            return user, role is not None

    async def create_project(self, identity: TelegramIdentity, draft: ProjectDraft) -> Project:
        validated = validate_project_draft(draft)
        catalog = load_role_catalog()
        async with self._session_factory.begin() as session:
            actor = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if actor is None or not actor.is_active:
                raise AccessDeniedError("Пользователь не зарегистрирован.")
            admin = await session.get(UserSystemRole, (actor.id, "admin"))
            if admin is None:
                raise AccessDeniedError("Создавать проекты может только администратор.")
            existing = await session.scalar(
                select(Project.id).where(Project.code == validated.code)
            )
            if existing is not None:
                raise DuplicateProjectCodeError("Проект с таким кодом уже существует.")
            project = Project(
                code=validated.code,
                name=validated.name,
                course_external_id=validated.course_external_id,
                course=validated.course,
                cohort=validated.cohort,
                business_problem=validated.business_problem,
                expected_result=validated.expected_result,
                description=validated.description,
                timezone=validated.timezone,
                starts_on=validated.starts_on,
                ends_on=validated.ends_on,
                created_by_user_id=actor.id,
            )
            session.add(project)
            await session.flush()
            for catalog_role in catalog.roles:
                await _add_catalog_role(session, project, actor.id, catalog, catalog_role)
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project",
                    entity_id=str(project.id),
                    action="created",
                    payload_json={"code": project.code, "status": project.status},
                )
            )
            return project

    async def preview_catalog_backfill(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> CatalogBackfillPlan:
        catalog = load_role_catalog()
        async with self._session_factory() as session:
            project, _ = await self._owned_project(session, identity, project_code)
            rows = await self._catalog_rows(session, project.id)
            return _backfill_plan(project, catalog, rows)

    async def apply_catalog_backfill(
        self, identity: TelegramIdentity, *, project_code: str, expected_fingerprint: str
    ) -> CatalogBackfillPlan:
        catalog = load_role_catalog()
        async with self._session_factory.begin() as session:
            project, actor = await self._owned_project(
                session, identity, project_code, lock=True
            )
            rows = await self._catalog_rows(session, project.id)
            plan = _backfill_plan(project, catalog, rows)
            if plan.fingerprint != expected_fingerprint:
                raise CatalogBackfillError("План устарел; повторите предварительный просмотр.")
            if plan.conflicts:
                raise CatalogBackfillError(
                    "Есть конфликтующие роли: " + ", ".join(plan.conflicts)
                )
            for code in plan.missing:
                catalog_role = catalog.find(code)
                assert catalog_role is not None
                await _add_catalog_role(session, project, actor.id, catalog, catalog_role)
            return plan

    @staticmethod
    async def _catalog_rows(
        session: AsyncSession, project_id: int
    ) -> list[tuple[ProjectRole, ProjectRoleVersion | None]]:
        rows = await session.execute(
            select(ProjectRole, ProjectRoleVersion)
            .outerjoin(ProjectRoleVersion)
            .where(ProjectRole.project_id == project_id)
        )
        return list(rows.all())

    @staticmethod
    async def _owned_project(
        session: AsyncSession,
        identity: TelegramIdentity,
        project_code: str,
        *,
        lock: bool = False,
    ) -> tuple[Project, User]:
        actor = await session.scalar(
            select(User).where(User.telegram_user_id == identity.telegram_user_id)
        )
        if actor is None or not actor.is_active:
            raise AccessDeniedError("Пользователь не зарегистрирован.")
        if await session.get(UserSystemRole, (actor.id, "admin")) is None:
            raise AccessDeniedError("Доступно только администратору проекта.")
        query = select(Project).where(Project.code == normalize_project_code(project_code))
        if lock:
            query = query.with_for_update()
        project = await session.scalar(query)
        if project is None or project.created_by_user_id != actor.id:
            raise AccessDeniedError("Проект не найден среди ваших проектов.")
        return project, actor

    async def list_projects(self, identity: TelegramIdentity) -> list[Project]:
        async with self._session_factory() as session:
            actor = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if actor is None or not actor.is_active:
                return []
            superadmin = await session.get(UserSystemRole, (actor.id, "superadmin"))
            if superadmin is not None:
                rows = await session.scalars(select(Project).order_by(Project.created_at.desc()))
                return list(rows)
            admin = await session.get(UserSystemRole, (actor.id, "admin"))
            if admin is not None:
                query = select(Project)
                query = query.where(Project.created_by_user_id == actor.id)
                rows = await session.scalars(query.order_by(Project.created_at.desc()))
                return list(rows)
            rows = await session.scalars(
                select(Project)
                .join_from(Project, ProjectParticipant)
                .where(ProjectParticipant.user_id == actor.id)
                .order_by(Project.created_at.desc())
            )
            return list(rows)
