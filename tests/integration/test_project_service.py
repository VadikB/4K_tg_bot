import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.application.assessments import AssessmentError, AssessmentService, AssessmentSpecDraft
from app.application.participants import (
    InvitationError,
    ParticipantIdentityNotReadyError,
    ParticipantService,
)
from app.application.projects import (
    AccessDeniedError,
    CatalogBackfillError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)
from app.application.roles import RoleDraft, RoleError, RoleService
from app.db import session_factory
from app.integrations.agent4k import (
    Agent4KChannelActionError,
    Agent4KUnavailableError,
    ChannelNextAction,
    ChannelProgress,
    EducationalChannelState,
    EducationalContextPreparation,
    EducationalProgramConnection,
    EducationalProgramOption,
    PublishedRoleProfileReference,
)
from app.models import (
    AssessmentAssignment,
    AuditEvent,
    Invitation,
    ParticipantRole,
    Project,
    ProjectAssessmentContextSnapshot,
    ProjectAssessmentSpec,
    ProjectParticipant,
    ProjectRole,
    ProjectRoleVersion,
    RoleProfileBinding,
    StudentChannelInputBinding,
    User,
    UserSystemRole,
)
from app.role_catalog import load_role_catalog
from tests.synthetic_semester import evaluate_bot_readback, load_package

pytestmark = pytest.mark.integration


class PublishedRoleAdapter:
    async def get_published_role_profile(self, *, version_id: int):
        return PublishedRoleProfileReference(
            id=version_id,
            code="specialist_expert",
            version=1,
            methodology_version="1.1",
            checksum="a" * 64,
        )

    async def resolve_participant(self, *, email: str, display_name: str):
        raise AssertionError("participant endpoint must not be called")

    async def issue_next_case(self, *, cycle_id: str, idempotency_key: str):
        raise AssertionError("case endpoint must not be called")

    async def prepare_educational_context(self, *, snapshot: dict, checksum: str):
        return EducationalContextPreparation(
            operation_id="educational-context:7",
            status="awaiting_admission",
            organization_id=31,
            assignment_id=41,
            assignment_ref=str(snapshot["assignment_ref"]),
            reasons=("PROGRAM_NOT_CONNECTED",),
            cycle_id=None,
        )

    async def list_educational_programs(self, *, assignment_ref: str):
        return (
            EducationalProgramOption(
                id=55,
                code="student-4k",
                version="1.0",
                name="Студенческая оценка",
                checksum="c" * 64,
            ),
        )

    async def connect_educational_program(
        self, *, assignment_ref: str, program_definition_id: int, operation_id: str
    ):
        return EducationalProgramConnection(
            program_definition_id=program_definition_id,
            program_code="student-4k",
            program_version="1.0",
            status="connected",
        )


class SyntheticChannelAdapter(PublishedRoleAdapter):
    def __init__(self) -> None:
        self.read_refs: list[str] = []
        self.action_calls: list[dict[str, object]] = []
        self.fail_next_action = False
        self.stale_next_action = False
        self.pause_action: tuple[asyncio.Event, asyncio.Event] | None = None

    async def read_educational_channel_state(self, *, assignment_ref: str):
        self.read_refs.append(assignment_ref)
        return EducationalChannelState(
            assignment_ref=assignment_ref,
            cycle_id=f"cycle:{assignment_ref}",
            state="action_required",
            revision=3,
            next_action=ChannelNextAction(
                action_id=f"action:{assignment_ref}",
                action_type="case_continue",
                participant_payload=None,
                trace=None,
                input={"kind": "confirm"},
            ),
            progress=ChannelProgress(
                status="active", completed=0, required=3, remaining=3,
                next_available_at=None,
            ),
        )

    async def apply_educational_channel_action(self, **kwargs: object):
        self.action_calls.append(kwargs)
        if self.pause_action is not None:
            started, released = self.pause_action
            started.set()
            await released.wait()
            self.pause_action = None
        if self.stale_next_action:
            self.stale_next_action = False
            raise Agent4KChannelActionError("STALE_CHANNEL_REVISION")
        if self.fail_next_action:
            self.fail_next_action = False
            raise Agent4KUnavailableError("synthetic timeout")
        assignment_ref = str(kwargs["assignment_ref"])
        return EducationalChannelState(
            assignment_ref=assignment_ref,
            cycle_id=f"cycle:{assignment_ref}",
            state="action_required",
            revision=4,
            next_action=None,
            progress=ChannelProgress(
                status="active", completed=0, required=3, remaining=3,
                next_available_at=None,
            ),
        )


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
        course_external_id="tba-2026-mba01",
        course="Технологии бизнес-аналитики",
        cohort="МБА-01",
        business_problem="Нет воспроизводимого прогноза",
        expected_result="Модель и аналитический отчёт",
        description="Учебный проект CRISP-DM",
        timezone="Europe/Moscow",
        starts_on=date(2026, 11, 10),
        ends_on=date(2026, 12, 20),
    )


async def create_legacy_project(database_url: str) -> tuple[ProjectService, TelegramIdentity]:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001, 1002))
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    draft = sample_draft()
    async with factory.begin() as session:
        actor = await session.scalar(
            select(User).where(User.telegram_user_id == admin.telegram_user_id)
        )
        assert actor is not None
        session.add(
            Project(
                code=draft.code,
                name=draft.name,
                course_external_id=draft.course_external_id,
                course=draft.course,
                cohort=draft.cohort,
                business_problem=draft.business_problem,
                expected_result=draft.expected_result,
                description=draft.description,
                timezone=draft.timezone,
                starts_on=draft.starts_on,
                ends_on=draft.ends_on,
                created_by_user_id=actor.id,
            )
        )
    return projects, admin


async def test_catalog_backfill_is_previewed_atomic_and_idempotent(database_url: str) -> None:
    projects, admin = await create_legacy_project(database_url)
    factory = session_factory(database_url)
    plan = await projects.preview_catalog_backfill(admin, project_code="TBA-2026-G01")
    assert set(plan.missing) == {role.code for role in load_role_catalog().roles}
    assert plan.existing == ()
    assert plan.conflicts == ()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProjectRole)) == 0
    with pytest.raises(CatalogBackfillError, match="устарел"):
        await projects.apply_catalog_backfill(
            admin, project_code="TBA-2026-G01", expected_fingerprint="wrong"
        )
    applied = await projects.apply_catalog_backfill(
        admin, project_code="TBA-2026-G01", expected_fingerprint=plan.fingerprint
    )
    assert applied == plan
    after = await projects.preview_catalog_backfill(admin, project_code="TBA-2026-G01")
    assert after.missing == ()
    assert len(after.existing) == 5
    await projects.apply_catalog_backfill(
        admin, project_code="TBA-2026-G01", expected_fingerprint=after.fingerprint
    )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProjectRoleVersion)) == 5


async def test_catalog_backfill_rejects_conflicts_and_foreign_admin(database_url: str) -> None:
    projects, admin = await create_legacy_project(database_url)
    factory = session_factory(database_url)
    roles = RoleService(factory)
    before = await projects.preview_catalog_backfill(admin, project_code="TBA-2026-G01")
    await roles.create_draft(
        admin,
        project_code="TBA-2026-G01",
        draft=sample_role("business_analyst", "Прежняя бизнес-роль"),
    )
    plan = await projects.preview_catalog_backfill(admin, project_code="TBA-2026-G01")
    assert plan.conflicts == ("business_analyst",)
    with pytest.raises(CatalogBackfillError, match="устарел"):
        await projects.apply_catalog_backfill(
            admin, project_code="TBA-2026-G01", expected_fingerprint=before.fingerprint
        )
    with pytest.raises(CatalogBackfillError, match="конфликтующие"):
        await projects.apply_catalog_backfill(
            admin, project_code="TBA-2026-G01", expected_fingerprint=plan.fingerprint
        )
    other_admin = TelegramIdentity(1002, "Другой администратор")
    await projects.ensure_actor(other_admin)
    with pytest.raises(AccessDeniedError, match="ваших проектов"):
        await projects.preview_catalog_backfill(
            other_admin, project_code="TBA-2026-G01"
        )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProjectRole)) == 1


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
        event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "created"))
        assert event is not None
        assert event.action == "created"
        assert event.payload_json == {"code": "TBA-2026-G01", "status": "draft"}
        versions = list(await session.scalars(select(ProjectRoleVersion)))
        catalog = load_role_catalog()
        assert len(versions) == len(catalog.roles) == 5
        assert all(version.status == "published" for version in versions)
        assert all(version.agent4k_role_profile_version_id is None for version in versions)
        assert all(
            version.source_json["catalog_checksum"] == catalog.sha256
            for version in versions
        )


async def test_project_list_shows_owners_only_and_all_to_superadmin(database_url: str) -> None:
    service = ProjectService(
        session_factory(database_url),
        bootstrap_admin_ids=(1001, 1002),
        superadmin_ids=(9009,),
    )
    first_admin = TelegramIdentity(1001, "Первый преподаватель")
    second_admin = TelegramIdentity(1002, "Второй преподаватель")
    superadmin = TelegramIdentity(9009, "Суперадминистратор")
    student = TelegramIdentity(2002, "Студент")
    for identity in (first_admin, second_admin, superadmin, student):
        await service.ensure_actor(identity)
    await service.create_project(first_admin, sample_draft())
    await service.create_project(
        second_admin,
        replace(sample_draft(), code="TBA-2026-G02", name="Второй проект"),
    )
    await service.create_project(
        superadmin,
        replace(sample_draft(), code="TBA-2026-G03", name="Третий проект"),
    )

    assert [item.code for item in await service.list_projects(first_admin)] == [
        "TBA-2026-G01"
    ]
    assert [item.code for item in await service.list_projects(second_admin)] == [
        "TBA-2026-G02"
    ]
    assert {item.code for item in await service.list_projects(superadmin)} == {
        "TBA-2026-G01", "TBA-2026-G02", "TBA-2026-G03"
    }
    factory = session_factory(database_url)
    async with factory() as session:
        superadmin_user = await session.scalar(
            select(User).where(User.telegram_user_id == 9009)
        )
        assert superadmin_user is not None
        assert await session.get(UserSystemRole, (superadmin_user.id, "superadmin"))
    restarted_service = ProjectService(factory, bootstrap_admin_ids=())
    assert await restarted_service.is_superadmin(superadmin)
    assert {item.code for item in await restarted_service.list_projects(superadmin)} == {
        "TBA-2026-G01", "TBA-2026-G02", "TBA-2026-G03"
    }
    assert await service.list_projects(student) == []


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
        participant_email=" Student@Example.EDU ",
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
        assert member.invited_telegram_user_id is None
        assert member.email == "student@example.edu"
        assert member.agent4k_user_id is None

    with pytest.raises(InvitationError, match="уже использовано"):
        await participants.accept_invitation(student, token=secret.token)


async def test_telegram_id_invitation_is_bound_to_intended_account(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001, 1002))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    other_admin = TelegramIdentity(1002, "Другой преподаватель")
    student = TelegramIdentity(2002, "Студент", "student")
    stranger = TelegramIdentity(3003, "Посторонний")
    await projects.ensure_actor(admin)
    await projects.ensure_actor(other_admin)
    await projects.create_project(admin, sample_draft())
    with pytest.raises(AccessDeniedError, match="ваших проектов"):
        await participants.create_telegram_invitation(
            other_admin, project_code="TBA-2026-G01",
            participant_name="Иванов Иван Иванович",
            participant_email="studentwithoutat", telegram_user_id=2002,
        )
    secret = await participants.create_telegram_invitation(
        admin, project_code="TBA-2026-G01",
        participant_name="Иванов Иван Иванович",
        participant_email="StudentWithoutAt", telegram_user_id=2002,
    )
    with pytest.raises(ValueError, match="email уже добавлен"):
        await participants.create_telegram_invitation(
            admin, project_code="TBA-2026-G01",
            participant_name="Иванов Иван Иванович",
            participant_email="studentwithoutat", telegram_user_id=3003,
        )
    with pytest.raises(ValueError, match="Telegram ID уже добавлен"):
        await participants.create_telegram_invitation(
            admin, project_code="TBA-2026-G01",
            participant_name="Иванов Иван Иванович",
            participant_email="another@example.edu", telegram_user_id=2002,
        )
    with pytest.raises(InvitationError, match="другому Telegram ID"):
        await participants.accept_invitation(stranger, token=secret.token)
    async with factory() as session:
        member = await session.scalar(select(ProjectParticipant))
        invitation = await session.scalar(select(Invitation))
        assert member is not None and member.user_id is None
        assert member.display_name == "Иванов Иван Иванович"
        assert member.email == "studentwithoutat"
        assert member.invited_telegram_user_id == 2002
        assert invitation is not None and invitation.used_at is None
        assert invitation.token_hash != secret.token
    await participants.accept_invitation(student, token=secret.token)
    with pytest.raises(InvitationError, match="уже использовано"):
        await participants.accept_invitation(student, token=secret.token)
    async with factory() as session:
        member = await session.scalar(select(ProjectParticipant))
        assert member is not None and member.status == "active"
        assert member.display_name == "Иванов Иван Иванович"
        assert member.email == "studentwithoutat"
        assert member.invited_telegram_user_id == 2002
    with pytest.raises(ParticipantIdentityNotReadyError, match="не подключена"):
        await participants.link_my_agent4k_identity(
            student, project_code="TBA-2026-G01", adapter=PublishedRoleAdapter()
        )


async def test_telegram_id_migration_preserves_legacy_and_blocks_data_loss(
    database_url: str,
) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    config = AlembicConfig("alembic.ini")
    config.attributes["database_url_override"] = database_url
    await asyncio.to_thread(command.downgrade, config, "0010_role_profile_bindings")
    await asyncio.to_thread(command.upgrade, config, "head")
    async with factory() as session:
        legacy = await session.scalar(select(ProjectParticipant))
        assert legacy is not None and legacy.email == "student@example.edu"
        assert legacy.invited_telegram_user_id is None
    await participants.create_telegram_invitation(
        admin, project_code="TBA-2026-G01",
        participant_name="Петров Пётр Петрович",
        participant_email="other@example.edu", telegram_user_id=2002,
    )
    with pytest.raises(RuntimeError, match="Telegram ID invitations exist"):
        await asyncio.to_thread(command.downgrade, config, "0010_role_profile_bindings")
    async with factory() as session:
        rows = list(await session.scalars(select(ProjectParticipant)))
        assert len(rows) == 2
        assert any(row.invited_telegram_user_id == 2002 for row in rows)


async def test_feedback_recipient_requires_active_project_membership(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    student = TelegramIdentity(2002, "Студент", "student")
    stranger = TelegramIdentity(3003, "Посторонний")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    await projects.ensure_actor(stranger)
    invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    with pytest.raises(AccessDeniedError):
        await participants.feedback_recipient(student, project_code="TBA-2026-G01")
    await participants.accept_invitation(student, token=invitation.token)
    recipient = await participants.feedback_recipient(student, project_code="tba-2026-g01")
    assert recipient.teacher_telegram_user_id == 1001
    assert recipient.participant_name == "Студент"
    with pytest.raises(AccessDeniedError):
        await participants.feedback_recipient(stranger, project_code="TBA-2026-G01")
    async with factory.begin() as session:
        member = await session.scalar(select(ProjectParticipant))
        assert member is not None
        member.status = "inactive"
    with pytest.raises(AccessDeniedError):
        await participants.feedback_recipient(student, project_code="TBA-2026-G01")
    async with factory.begin() as session:
        member = await session.scalar(select(ProjectParticipant))
        assert member is not None
        member.status = "active"
        creator = await session.scalar(select(User).where(User.telegram_user_id == 1001))
        assert creator is not None
        admin_role = await session.get(UserSystemRole, (creator.id, "admin"))
        assert admin_role is not None
        await session.delete(admin_role)
    with pytest.raises(AccessDeniedError):
        await participants.feedback_recipient(student, project_code="TBA-2026-G01")


async def test_legacy_participant_keeps_existing_4k_link_without_sending_email(
    database_url: str,
) -> None:
    class Adapter:
        async def resolve_participant(self, *, email: str, display_name: str):
            raise AssertionError("participant email must stay in bot database")

        async def issue_next_case(self, *, cycle_id: str, idempotency_key: str):
            raise AssertionError("case endpoint must not be called")

    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    student = TelegramIdentity(2002, "Студент", "student")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Ожидаемый студент",
        participant_email="student@example.edu",
    )
    await participants.accept_invitation(student, token=invitation.token)
    adapter = Adapter()

    with pytest.raises(ParticipantIdentityNotReadyError, match="не подключена"):
        await participants.link_my_agent4k_identity(
            student,
            project_code="TBA-2026-G01",
            adapter=adapter,
        )
    async with factory.begin() as session:
        member = await session.scalar(select(ProjectParticipant))
        assert member is not None
        assert member.agent4k_user_id is None
        member.agent4k_user_id = 42
        member.agent4k_linked_at = datetime.now(UTC)

    repeated = await participants.link_my_agent4k_identity(
        student,
        project_code="TBA-2026-G01",
        adapter=adapter,
    )

    assert repeated.agent4k_user_id == 42 and repeated.created is False
    async with factory() as session:
        member = await session.scalar(select(ProjectParticipant))
        assert member is not None and member.agent4k_user_id == 42
        assert member.agent4k_linked_at is not None


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
        participant_email="student@example.edu",
        now=issued_at,
    )

    with pytest.raises(InvitationError, match="истёк"):
        await participants.accept_invitation(
            TelegramIdentity(2002, "Студент"),
            token=secret.token,
            now=issued_at + timedelta(hours=2),
        )


async def test_participant_email_is_unique_per_project(database_url: str) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    await projects.create_project(admin, sample_draft("TBA-2026-G02"))

    await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    with pytest.raises(ValueError, match="уже добавлен"):
        await participants.create_invitation(
            admin,
            project_code="TBA-2026-G01",
            participant_name="Дубликат",
            participant_email="STUDENT@example.edu",
        )
    second = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G02",
        participant_name="Тот же студент",
        participant_email="student@example.edu",
    )
    assert second.project_code == "TBA-2026-G02"


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
        agent4k_role_profile_version_id=17,
        agent4k_role_profile_checksum="a" * 64,
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
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    student = TelegramIdentity(2002, "Студент", "student")
    await participants.accept_invitation(student, token=invitation.token)

    for code, name in (
        ("business_analyst", "Бизнес-аналитик"),
        ("data_researcher", "Исследователь данных"),
    ):
        created = await roles.create_draft(
            admin, project_code="TBA-2026-G01", draft=sample_role(code, name)
        )
        assert created.status == "draft"
        published = await roles.publish(
            admin,
            project_code="TBA-2026-G01",
            role_code=code,
            adapter=PublishedRoleAdapter(),
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
        role_code="data_researcher",
    )
    assert first.is_primary is True
    assert second.is_primary is False
    mine = await roles.list_my_roles(student)
    assert [(item.role_code, item.is_primary) for item in mine] == [
        ("business_analyst", True),
        ("data_researcher", False),
    ]

    async with factory() as session:
        assigned = list(await session.scalars(select(ParticipantRole)))
        assert len(assigned) == 2
        assert sum(item.is_primary for item in assigned) == 1


async def test_catalog_role_can_be_assigned_before_4k_mapping_but_not_assessed(
    database_url: str,
) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    roles = RoleService(factory)
    assessments = AssessmentService(factory)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    student = TelegramIdentity(2002, "Студент", "student")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    await participants.accept_invitation(student, token=invitation.token)
    assigned = await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="business_analyst",
    )
    assert assigned.role_version == 1
    assert [item.role_code for item in await roles.list_my_roles(student)] == [
        "business_analyst"
    ]
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")
    with pytest.raises(AssessmentError, match="ожидает сопоставления"):
        await assessments.assign(
            admin,
            project_code="TBA-2026-G01",
            participant_id=invitation.participant_id,
            role_code="business_analyst",
        )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AssessmentAssignment)) == 0


async def test_catalog_binding_is_verified_versioned_and_pinned_to_assessment(
    database_url: str,
) -> None:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001, 1002))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    roles = RoleService(factory)
    assessments = AssessmentService(factory)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="business_analyst",
    )
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")

    other_admin = TelegramIdentity(1002, "Другой администратор")
    await projects.ensure_actor(other_admin)
    with pytest.raises(AccessDeniedError, match="владелец проекта"):
        await roles.publish_role_profile_binding(
            other_admin,
            project_code="TBA-2026-G01",
            role_code="business_analyst",
            agent4k_role_profile_version_id=17,
            agent4k_role_profile_checksum="a" * 64,
            adapter=PublishedRoleAdapter(),
        )
    with pytest.raises(RoleError, match="не совпадает"):
        await roles.publish_role_profile_binding(
            admin,
            project_code="TBA-2026-G01",
            role_code="business_analyst",
            agent4k_role_profile_version_id=17,
            agent4k_role_profile_checksum="b" * 64,
            adapter=PublishedRoleAdapter(),
        )
    class UnavailableRoleAdapter(PublishedRoleAdapter):
        async def get_published_role_profile(self, *, version_id: int):
            raise Agent4KUnavailableError("synthetic outage")

    with pytest.raises(Agent4KUnavailableError, match="synthetic outage"):
        await roles.publish_role_profile_binding(
            admin,
            project_code="TBA-2026-G01",
            role_code="business_analyst",
            agent4k_role_profile_version_id=17,
            agent4k_role_profile_checksum="a" * 64,
            adapter=UnavailableRoleAdapter(),
        )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RoleProfileBinding)) == 0
    first = await roles.publish_role_profile_binding(
        admin,
        project_code="TBA-2026-G01",
        role_code="business_analyst",
        agent4k_role_profile_version_id=17,
        agent4k_role_profile_checksum="a" * 64,
        adapter=PublishedRoleAdapter(),
    )
    assert first.binding_version == 1
    assert await roles.publish_role_profile_binding(
        admin,
        project_code="TBA-2026-G01",
        role_code="business_analyst",
        agent4k_role_profile_version_id=17,
        agent4k_role_profile_checksum="a" * 64,
        adapter=PublishedRoleAdapter(),
    ) == first
    assigned = await assessments.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="business_analyst",
    )
    async with factory() as session:
        original = await session.scalar(
            select(ProjectRoleVersion)
            .join(ProjectRole)
            .where(ProjectRole.code == "business_analyst")
        )
        assignment = await session.get(AssessmentAssignment, assigned.id)
        assert original is not None and assignment is not None
        assert original.agent4k_role_profile_version_id is None
        assert assignment.project_role_version_id == original.id
        assert assignment.role_profile_binding_id is not None

    second = await roles.publish_role_profile_binding(
        admin,
        project_code="TBA-2026-G01",
        role_code="business_analyst",
        agent4k_role_profile_version_id=18,
        agent4k_role_profile_checksum="a" * 64,
        adapter=PublishedRoleAdapter(),
    )
    assert second.binding_version == 2
    another_invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Другой студент",
        participant_email="other-student@example.edu",
    )
    await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=another_invitation.participant_id,
        role_code="business_analyst",
    )
    another_assessment = await assessments.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=another_invitation.participant_id,
        role_code="business_analyst",
    )
    async with factory() as session:
        old_assignment = await session.get(AssessmentAssignment, assigned.id)
        new_assignment = await session.get(AssessmentAssignment, another_assessment.id)
        assert old_assignment is not None and new_assignment is not None
        assert old_assignment.role_profile_binding_id != new_assignment.role_profile_binding_id
        old_binding = await session.get(RoleProfileBinding, old_assignment.role_profile_binding_id)
        new_binding = await session.get(RoleProfileBinding, new_assignment.role_profile_binding_id)
        assert old_binding is not None and new_binding is not None
        assert old_binding.agent4k_role_profile_version_id == 17
        assert new_binding.agent4k_role_profile_version_id == 18
    async with factory.begin() as session:
        participant = await session.get(ProjectParticipant, invitation.participant_id)
        assert participant is not None
        participant.agent4k_user_id = 42001
        participant.agent4k_linked_at = datetime.now(UTC)
    context = await assessments.publish_context_snapshot(admin, assignment_id=assigned.id)
    async with factory() as session:
        saved = await session.get(ProjectAssessmentContextSnapshot, context.id)
        assert saved is not None
        assert saved.snapshot_json["role"]["agent4k_role_profile_version_id"] == 17
        assert await session.scalar(select(func.count()).select_from(RoleProfileBinding)) == 2

    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            binding = await session.scalar(select(RoleProfileBinding))
            assert binding is not None
            binding.agent4k_role_profile_version_id = 99
    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            assignment = await session.get(AssessmentAssignment, assigned.id)
            assert assignment is not None
            assignment.role_profile_binding_id = new_binding.id
    config = AlembicConfig("alembic.ini")
    config.attributes["database_url_override"] = database_url
    with pytest.raises(RuntimeError, match="published role profile bindings"):
        await asyncio.to_thread(command.downgrade, config, "0009_channel_input_bindings")
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RoleProfileBinding)) == 2


async def test_empty_role_binding_migration_can_downgrade_and_upgrade(
    database_url: str,
) -> None:
    config = AlembicConfig("alembic.ini")
    config.attributes["database_url_override"] = database_url
    await asyncio.to_thread(command.downgrade, config, "0009_channel_input_bindings")
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT to_regclass('public.role_profile_bindings')")
        )
        assert result.scalar_one() is None
    await engine.dispose()
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT to_regclass('public.role_profile_bindings')")
        )
        assert result.scalar_one() == "role_profile_bindings"
    await engine.dispose()


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
    await roles.publish(
        admin,
        project_code="TBA-2026-G01",
        role_code="business_analyst",
        adapter=PublishedRoleAdapter(),
    )

    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            version = await session.scalar(select(ProjectRoleVersion))
            assert version is not None
            version.definition_json = {"changed": True}

    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            version = await session.scalar(select(ProjectRoleVersion))
            assert version is not None
            version.agent4k_role_profile_version_id = 99


async def assessment_fixture(database_url: str) -> tuple[
    AssessmentService, TelegramIdentity, TelegramIdentity, int
]:
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    roles = RoleService(factory)
    assessments = AssessmentService(factory)
    admin = TelegramIdentity(1001, "Преподаватель", "teacher")
    student = TelegramIdentity(2002, "Студент", "student")
    await projects.ensure_actor(admin)
    await projects.create_project(admin, sample_draft())
    invitation = await participants.create_invitation(
        admin,
        project_code="TBA-2026-G01",
        participant_name="Студент",
        participant_email="student@example.edu",
    )
    await participants.accept_invitation(student, token=invitation.token)
    await roles.create_draft(
        admin,
        project_code="TBA-2026-G01",
        draft=sample_role("business_analyst", "Бизнес-аналитик"),
    )
    await roles.publish(
        admin,
        project_code="TBA-2026-G01",
        role_code="business_analyst",
        adapter=PublishedRoleAdapter(),
    )
    await roles.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=invitation.participant_id,
        role_code="business_analyst",
    )
    return assessments, admin, student, invitation.participant_id


def sample_spec() -> AssessmentSpecDraft:
    return AssessmentSpecDraft(
        assessment_configuration_ref="agent4k:configuration:standard-4k:v1",
        assessment_configuration_checksum="a" * 64,
        methodology_ref="competencies_4k:1.1",
        required_case_count=8,
        available_from=date(2026, 11, 10),
        available_until=date(2026, 12, 20),
        result_recipient_policy="participant_and_instructor",
    )


async def test_published_spec_assigns_exact_role_and_exposes_progress(
    database_url: str,
) -> None:
    assessments, admin, student, participant_id = await assessment_fixture(database_url)
    created = await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    assert created.runtime_admission == "pending_agent4k_verification"
    published = await assessments.publish_spec(admin, project_code="TBA-2026-G01")
    assert published.status == "published"
    assignment = await assessments.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=participant_id,
        role_code="business_analyst",
    )
    assert assignment.status == "assigned"
    assert assignment.runtime_connected is False
    assert assignment.remaining_cases == 8
    progress = await assessments.my_progress(student)
    assert len(progress) == 1
    assert progress[0].role_code == "business_analyst"
    assert progress[0].remaining_cases == 8

    factory = session_factory(database_url)
    async with factory() as session:
        stored = await session.scalar(select(AssessmentAssignment))
        assert stored is not None
        assert stored.external_cycle_id is None


async def test_synthetic_semester_multi_project_role_assignment_readback(
    database_url: str,
) -> None:
    package = load_package()
    scenario = next(
        item
        for item in package["scenarios"]["scenarios"]
        if item["id"] == "multi-project-multi-role-isolation"
    )
    role_sources = {item["code"]: item for item in package["roles"]["roles"]}
    project_codes = {
        "project-demand": "SYNTH-DEMAND",
        "project-segmentation": "SYNTH-SEGMENTATION",
    }
    factory = session_factory(database_url)
    projects = ProjectService(factory, bootstrap_admin_ids=(1001,))
    participants = ParticipantService(factory, invitation_ttl_hours=168)
    roles = RoleService(factory)
    assessments = AssessmentService(factory)
    admin = TelegramIdentity(1001, "Синтетический преподаватель", "synthetic_teacher")
    student = TelegramIdentity(2002, "Синтетический студент", "synthetic_student")
    await projects.ensure_actor(admin)
    participant_ids = {}
    for project_ref, project_code in project_codes.items():
        draft = sample_draft(project_code)
        draft = replace(draft, name=project_ref)
        await projects.create_project(admin, draft)
        invitation = await participants.create_invitation(
            admin,
            project_code=project_code,
            participant_name="Синтетический студент",
            participant_email="synthetic-student-01@example.test",
        )
        await participants.accept_invitation(student, token=invitation.token)
        participant_ids[project_ref] = invitation.participant_id

    assignments_by_fixture_ref = {}
    for expected in scenario["assignments"]:
        project_code = project_codes[expected["project_ref"]]
        source = role_sources[expected["role_code"]]
        await roles.create_draft(
            admin,
            project_code=project_code,
            draft=RoleDraft(
                code=source["code"], name=source["name"], mission=source["name"],
                responsibilities=tuple(source["responsibilities"]),
                typical_tasks=tuple(source["responsibilities"]),
                expected_outputs=("Синтетический артефакт",),
                interactions=tuple(source["interacts_with"]),
                crisp_dm_stages=tuple(source["crisp_dm_phases"]),
                agent4k_role_profile_version_id=17,
                agent4k_role_profile_checksum="a" * 64,
            ),
        )
        await roles.publish(
            admin, project_code=project_code, role_code=source["code"],
            adapter=PublishedRoleAdapter(),
        )
        await roles.assign(
            admin, project_code=project_code,
            participant_id=participant_ids[expected["project_ref"]], role_code=source["code"],
        )

    for project_ref, project_code in project_codes.items():
        await assessments.create_spec_draft(admin, project_code=project_code, draft=sample_spec())
        await assessments.publish_spec(admin, project_code=project_code)
        async with factory.begin() as session:
            participant = await session.get(ProjectParticipant, participant_ids[project_ref])
            assert participant is not None
            participant.agent4k_user_id = 42001
            participant.agent4k_linked_at = datetime.now(UTC)

    for expected in scenario["assignments"]:
        assigned = await assessments.assign(
            admin,
            project_code=project_codes[expected["project_ref"]],
            participant_id=participant_ids[expected["project_ref"]],
            role_code=expected["role_code"],
        )
        snapshot = await assessments.publish_context_snapshot(admin, assignment_id=assigned.id)
        assignments_by_fixture_ref[expected["ref"]] = snapshot.assignment_ref

    observed = {"assignments": []}
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    AssessmentAssignment,
                    ProjectAssessmentContextSnapshot,
                    ProjectParticipant,
                    Project,
                    ProjectRole,
                )
                .join(
                    ProjectAssessmentContextSnapshot,
                    ProjectAssessmentContextSnapshot.assessment_assignment_id
                    == AssessmentAssignment.id,
                )
                .join(
                    ProjectParticipant,
                    ProjectParticipant.id == AssessmentAssignment.participant_id,
                )
                .join(Project, Project.id == ProjectParticipant.project_id)
                .join(
                    ProjectRoleVersion,
                    ProjectRoleVersion.id == AssessmentAssignment.project_role_version_id,
                )
                .join(ProjectRole, ProjectRole.id == ProjectRoleVersion.project_role_id)
            )
        ).all()
    fixture_by_external = {value: key for key, value in assignments_by_fixture_ref.items()}
    project_ref_by_code = {value: key for key, value in project_codes.items()}
    for _, context, _, project, role in rows:
        observed["assignments"].append({
            "fixture_assignment_ref": fixture_by_external[context.assignment_ref],
            "assignment_ref": context.assignment_ref,
            "project_ref": project_ref_by_code[project.code],
            "participant_ref": "student-01",
            "role_code": role.code,
        })
    result = evaluate_bot_readback(scenario, observed)
    assert result["status"] == "passed", result

    channel_adapter = SyntheticChannelAdapter()
    channel_assignments = await assessments.my_channel_assignments(student)
    assert len(channel_assignments) == 3
    assert len({item.assignment_ref for item in channel_assignments}) == 3
    states = [
        await assessments.read_my_channel_state(
            student, assignment_id=item.assignment_id, adapter=channel_adapter,
        )
        for item in channel_assignments
    ]
    assert {state.assignment_ref for state in states} == {
        item.assignment_ref for item in channel_assignments
    }
    selected = channel_assignments[0]
    applied = await assessments.apply_my_channel_action(
        student,
        assignment_id=selected.assignment_id,
        action_id=f"action:{selected.assignment_ref}",
        expected_revision=3,
        action_input={"kind": "confirm"},
        idempotency_key="synthetic-channel-action",
        adapter=channel_adapter,
    )
    assert applied.assignment_ref == selected.assignment_ref
    assert channel_adapter.action_calls[0]["assignment_ref"] == selected.assignment_ref
    text_assignment = channel_assignments[1]
    await assessments.bind_my_channel_text_action(
        student,
        assignment_id=text_assignment.assignment_id,
        action_id=f"text-action:{text_assignment.assignment_ref}",
        expected_revision=7,
        idempotency_key="synthetic-text-action",
    )
    submitted = await assessments.submit_my_pending_channel_text(
        student,
        text="  Синтетический ответ, который нельзя сохранять  ",
        telegram_chat_id=2002,
        telegram_message_id=501,
        adapter=channel_adapter,
    )
    assert submitted is not None
    assert submitted.assignment_id == text_assignment.assignment_id
    assert channel_adapter.action_calls[1]["action_input"] == {
        "kind": "text",
        "text": "  Синтетический ответ, который нельзя сохранять  ",
    }
    async with factory() as session:
        binding = await session.scalar(select(StudentChannelInputBinding))
        assert binding is not None
        assert binding.status == "completed"
        assert binding.telegram_message_id == 501
        assert binding.payload_checksum is not None
        stored = json.dumps({
            "assignment_ref": binding.assignment_ref,
            "action_id": binding.action_id,
            "idempotency_key": binding.idempotency_key,
        }, ensure_ascii=False)
        assert "Синтетический ответ" not in stored
    retry_assignment = channel_assignments[2]
    await assessments.bind_my_channel_text_action(
        student,
        assignment_id=retry_assignment.assignment_id,
        action_id=f"text-action:{retry_assignment.assignment_ref}",
        expected_revision=9,
        idempotency_key="synthetic-text-retry",
    )
    channel_adapter.fail_next_action = True
    with pytest.raises(AssessmentError, match="тот же ответ"):
        await assessments.submit_my_pending_channel_text(
            student,
            text="Повторяемый ответ",
            telegram_chat_id=2002,
            telegram_message_id=502,
            adapter=channel_adapter,
        )
    calls_after_timeout = len(channel_adapter.action_calls)
    with pytest.raises(AssessmentError, match="того же ответа"):
        await assessments.submit_my_pending_channel_text(
            student,
            text="Подменённый ответ",
            telegram_chat_id=2002,
            telegram_message_id=503,
            adapter=channel_adapter,
        )
    with pytest.raises(AssessmentError, match="исходном чате"):
        await assessments.submit_my_pending_channel_text(
            student,
            text="Повторяемый ответ",
            telegram_chat_id=9999,
            telegram_message_id=504,
            adapter=channel_adapter,
        )
    assert len(channel_adapter.action_calls) == calls_after_timeout
    async with factory.begin() as session:
        crashed = await session.scalar(
            select(StudentChannelInputBinding).where(
                StudentChannelInputBinding.action_id
                == f"text-action:{retry_assignment.assignment_ref}"
            )
        )
        assert crashed is not None and crashed.status == "pending"
        crashed.status = "sending"
        crashed.attempt_started_at = datetime.now(UTC) - timedelta(minutes=6)
    retried = await assessments.submit_my_pending_channel_text(
        student,
        text="Повторяемый ответ",
        telegram_chat_id=2002,
        telegram_message_id=502,
        adapter=channel_adapter,
    )
    assert retried is not None
    assert channel_adapter.action_calls[-2]["idempotency_key"] == (
        channel_adapter.action_calls[-1]["idempotency_key"]
    )
    await assessments.bind_my_channel_text_action(
        student,
        assignment_id=selected.assignment_id,
        action_id="slow-action",
        expected_revision=10,
        idempotency_key="synthetic-slow-action",
    )
    started, released = asyncio.Event(), asyncio.Event()
    channel_adapter.pause_action = (started, released)
    first_send = asyncio.create_task(assessments.submit_my_pending_channel_text(
        student,
        text="Одновременный ответ",
        telegram_chat_id=2002,
        telegram_message_id=505,
        adapter=channel_adapter,
    ))
    await asyncio.wait_for(started.wait(), timeout=5)
    with pytest.raises(AssessmentError, match="уже отправляется"):
        await assessments.submit_my_pending_channel_text(
            student,
            text="Одновременный ответ",
            telegram_chat_id=2002,
            telegram_message_id=505,
            adapter=channel_adapter,
        )
    released.set()
    assert await first_send is not None
    await assessments.bind_my_channel_text_action(
        student,
        assignment_id=selected.assignment_id,
        action_id="stale-action",
        expected_revision=11,
        idempotency_key="synthetic-stale-action",
    )
    channel_adapter.stale_next_action = True
    with pytest.raises(AssessmentError, match="устарело"):
        await assessments.submit_my_pending_channel_text(
            student,
            text="Устаревший ответ",
            telegram_chat_id=2002,
            telegram_message_id=506,
            adapter=channel_adapter,
        )
    async with factory() as session:
        stale_binding = await session.scalar(
            select(StudentChannelInputBinding).where(
                StudentChannelInputBinding.action_id == "stale-action"
            )
        )
        assert stale_binding is not None and stale_binding.status == "stale"
    with pytest.raises(AccessDeniedError, match="недоступно"):
        await assessments.read_my_channel_state(
            admin, assignment_id=selected.assignment_id, adapter=channel_adapter,
        )


async def test_publishes_immutable_context_without_contact_identity(
    database_url: str,
) -> None:
    assessments, admin, _, participant_id = await assessment_fixture(database_url)
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")
    assignment = await assessments.assign(
        admin,
        project_code="TBA-2026-G01",
        participant_id=participant_id,
        role_code="business_analyst",
    )
    factory = session_factory(database_url)
    async with factory.begin() as session:
        participant = await session.get(ProjectParticipant, participant_id)
        assert participant is not None
        participant.agent4k_user_id = 42001
        participant.agent4k_linked_at = datetime.now(UTC)

    published = await assessments.publish_context_snapshot(
        admin, assignment_id=assignment.id
    )
    repeated = await assessments.publish_context_snapshot(admin, assignment_id=assignment.id)
    assert repeated == published
    assert published.assignment_ref == f"edu:4k-tg-bot:p1:a{assignment.id}"

    async with factory() as session:
        stored = await session.scalar(select(ProjectAssessmentContextSnapshot))
        assert stored is not None
        assert stored.snapshot_json["participant"] == {
            "local_ref": f"participant:{participant_id}",
            "agent4k_user_id": 42001,
        }
        serialized = json.dumps(stored.snapshot_json, ensure_ascii=False).lower()
        assert "email" not in serialized
        assert "telegram" not in serialized
        assert "student@example.edu" not in serialized
        assert stored.snapshot_json["role"]["agent4k_role_profile_version_id"] == 17
        assert stored.snapshot_json["assessment_spec"]["version"] == 1

    preparation = await assessments.prepare_external_context(
        admin, assignment_id=assignment.id, adapter=PublishedRoleAdapter()
    )
    assert preparation.status == "awaiting_admission"
    assert preparation.reasons == ("PROGRAM_NOT_CONNECTED",)
    programs = await assessments.list_compatible_programs(
        admin, assignment_id=assignment.id, adapter=PublishedRoleAdapter()
    )
    assert programs[0].id == 55
    connected = await assessments.connect_compatible_program(
        admin,
        assignment_id=assignment.id,
        program_definition_id=55,
        adapter=PublishedRoleAdapter(),
    )
    assert connected.program_code == "student-4k"

    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            stored = await session.scalar(select(ProjectAssessmentContextSnapshot))
            assert stored is not None
            stored.snapshot_json = {"changed": True}


async def test_assessment_rejects_role_not_assigned_to_participant(database_url: str) -> None:
    assessments, admin, _, participant_id = await assessment_fixture(database_url)
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")

    with pytest.raises(AssessmentError, match="не назначена"):
        await assessments.assign(
            admin,
            project_code="TBA-2026-G01",
            participant_id=participant_id,
            role_code="data_researcher",
        )


async def test_published_assessment_spec_is_immutable(database_url: str) -> None:
    assessments, admin, _, _ = await assessment_fixture(database_url)
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")

    factory = session_factory(database_url)
    with pytest.raises(DBAPIError, match="immutable"):
        async with factory.begin() as session:
            spec = await session.scalar(select(ProjectAssessmentSpec))
            assert spec is not None
            spec.snapshot_json = {"changed": True}
