import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.application.participants import InvitationError, ParticipantService
from app.application.projects import (
    AccessDeniedError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)
from app.application.roles import RoleDraft, RoleService
from app.db import session_factory
from app.models import (
    AuditEvent,
    Invitation,
    ParticipantRole,
    Project,
    ProjectParticipant,
    ProjectRoleVersion,
    User,
)

pytestmark = pytest.mark.integration


def isolated_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    database = make_url(value).database or ""
    if "test" not in database.lower() and "pytest" not in database.lower():
        pytest.fail("TEST_DATABASE_URL must contain test or pytest in the database name")
    return value


@pytest.fixture
async def database_url() -> str:
    value = isolated_database_url()
    engine = create_async_engine(value)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    config = AlembicConfig("alembic.ini")
    config.attributes["database_url_override"] = value
    await asyncio.to_thread(command.upgrade, config, "head")
    yield value


def sample_draft(code: str = "TBA-2026-G01") -> ProjectDraft:
    return ProjectDraft(
        code=code,
        name="Прогноз спроса",
        course="Технологии бизнес-аналитики",
        cohort="МБА-01",
        business_problem="Нет воспроизводимого прогноза",
        expected_result="Модель и аналитический отчёт",
        description="Учебный проект CRISP-DM",
        timezone="Europe/Moscow",
        starts_on=date(2026, 11, 10),
        ends_on=date(2026, 12, 20),
    )


async def test_bootstrap_admin_creates_project_and_audit(database_url: str) -> None:
    service = ProjectService(session_factory(database_url), bootstrap_admin_ids=(1001,))
    identity = TelegramIdentity(1001, "Преподаватель", "teacher")
    _, is_admin = await service.ensure_actor(identity)
    assert is_admin is True

    project = await service.create_project(identity, sample_draft())
    assert project.code == "TBA-2026-G01"
    assert [item.code for item in await service.list_projects(identity)] == ["TBA-2026-G01"]

    factory = session_factory(database_url)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 1
        event = await session.scalar(select(AuditEvent))
        assert event is not None
        assert event.action == "created"
        assert event.payload_json == {"code": "TBA-2026-G01", "status": "draft"}


async def test_participant_cannot_create_project(database_url: str) -> None:
    service = ProjectService(session_factory(database_url), bootstrap_admin_ids=())
    identity = TelegramIdentity(2002, "Студент", "student")
    _, is_admin = await service.ensure_actor(identity)
    assert is_admin is False

    with pytest.raises(AccessDeniedError, match="только администратор"):
        await service.create_project(identity, sample_draft())


async def test_one_time_invitation_connects_telegram_identity(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    student = TelegramIdentity(2002, "Студент", "student")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())

    secret = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Ожидаемый студент",
    )
    project = await participants.accept_invitation(student, token=secret.token)
    assert project.code == "TBA-2026-G01"
    assert [item.code for item in await projects.list_projects(student)] == ["TBA-2026-G01"]

    async with factory() as session:
        invitation = await session.scalar(select(Invitation))
        member = await session.scalar(select(ProjectParticipant))
        user = await session.scalar(select(User).where(User.telegram_user_id == 2002))
        assert invitation is not None and invitation.used_at is not None
        assert invitation.token_hash != secret.token
        assert member is not None and member.user_id == user.id
        assert member.status == "active"
        assert member.display_name == "Студент"

    with pytest.raises(InvitationError, match="уже использовано"):
        await participants.accept_invitation(student, token=secret.token)


async def test_expired_invitation_is_rejected(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=1)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    issued_at = datetime(2026, 11, 6, 10, tzinfo=UTC)
    secret = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        now=issued_at,
    )

    with pytest.raises(InvitationError, match="истёк"):
        await participants.accept_invitation(
            TelegramIdentity(2002, "Студент"),
            token=secret.token,
            now=issued_at + timedelta(hours=2),
        )


def sample_role(code: str, name: str) -> RoleDraft:
    return RoleDraft(
        code=code,
        name=name,
        mission=f"Миссия: {name}",
        responsibilities=("Отвечать за результат",),
        typical_tasks=("Выполнить задачу",),
        expected_outputs=("Артефакт проекта",),
        interactions=("Команда проекта",),
        crisp_dm_stages=("business_understanding", "data_understanding"),
    )


async def test_participant_can_have_multiple_versioned_roles(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    roles = RoleService(factory)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    invitation = await participants.create_invitation(
        admin, project_code="TBA-2026-G01", participant_name="Студент"
    )
    student = TelegramIdentity(2002, "Студент", "student")
    await participants.accept_invitation(student, token=invitation.token)

    for code, name in (("business_analyst", "Бизнес-аналитик"), ("data_scientist", "DS")):
        created = await roles.create_draft(
            admin, project_code="TBA-2026-G01", draft=sample_role(code, name)
        )
        assert created.status == "draft"
        published = await roles.publish(
            admin, project_code="TBA-2026-G01", role_code=code
        )
        assert published.status == "published"

    first = await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="business_analyst",
    )
    second = await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="data_scientist",
    )
    assert first.is_primary is True
    assert second.is_primary is False
    mine = await roles.list_my_roles(student)
    assert [(item.role_code, item.is_primary) for item in mine] == [
        ("business_analyst", True),
        ("data_scientist", False),
    ]

    async with factory() as session:
        assigned = list(await session.scalars(select(ParticipantRole)))
        assert len(assigned) == 2
        assert sum(item.is_primary for item in assigned) == 1


async def test_published_role_content_is_immutable(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    roles = RoleService(factory)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    await roles.create_draft(
        admin,
        project_code="TBA-2026-G01",
        draft=sample_role("business_analyst", "Бизнес-аналитик"),
    )
    await roles.publish(admin, project_code="TBA-2026-G01", role_code="business_analyst")

    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            version = await session.scalar(select(ProjectRoleVersion))
            assert version is not None
            version.definition_json = {"changed": True}
