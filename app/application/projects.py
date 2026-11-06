import re
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, Project, ProjectParticipant, User, UserSystemRole

PROJECT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
EXTERNAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{2,127}$")


class AccessDeniedError(RuntimeError):
    pass


class DuplicateProjectCodeError(RuntimeError):
    pass


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


class ProjectService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        bootstrap_admin_ids: tuple[int, ...],
    ) -> None:
        self._session_factory = session_factory
        self._bootstrap_admin_ids = frozenset(bootstrap_admin_ids)

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
            if identity.telegram_user_id in self._bootstrap_admin_ids and role is None:
                session.add(UserSystemRole(user_id=user.id, role="admin"))
                return user, True
            return user, role is not None

    async def create_project(self, identity: TelegramIdentity, draft: ProjectDraft) -> Project:
        validated = validate_project_draft(draft)
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

    async def list_projects(self, identity: TelegramIdentity) -> list[Project]:
        async with self._session_factory() as session:
            actor = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if actor is None or not actor.is_active:
                return []
            admin = await session.get(UserSystemRole, (actor.id, "admin"))
            if admin is not None:
                rows = await session.scalars(select(Project).order_by(Project.created_at.desc()))
                return list(rows)
            rows = await session.scalars(
                select(Project)
                .join_from(Project, ProjectParticipant)
                .where(ProjectParticipant.user_id == actor.id)
                .order_by(Project.created_at.desc())
            )
            return list(rows)
