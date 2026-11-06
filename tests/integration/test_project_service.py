import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.application.assessments import AssessmentError, AssessmentService, AssessmentSpecDraft
from app.application.participants import InvitationError, ParticipantService
from app.application.projects import (
    AccessDeniedError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)
from app.application.roles import RoleDraft, RoleService
from app.db import session_factory
from app.integrations.agent4k import (
    EducationalContextPreparation,
    EducationalProgramConnection,
    EducationalProgramOption,
    ParticipantIdentityLink,
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
    ProjectRoleVersion,
    User,
)

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
        assert member.email == "student@example.edu"
        assert member.agent4k_user_id is None

    with pytest.raises(InvitationError, match="уже использовано"):
        await participants.accept_invitation(student, token=secret.token)


async def test_participant_links_to_agent4k_idempotently(database_url: str) -> None:
    class Adapter:
        calls = 0

        async def resolve_participant(self, *, email: str, display_name: str):
            self.calls += 1
            assert email == "student@example.edu"
            assert display_name == "Студент"
            return ParticipantIdentityLink(agent4k_user_id=42, status="provisioned")

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

    first = await participants.link_my_agent4k_identity(
        student,
        project_code="TBA-2026-G01",
        adapter=adapter,
    )
    repeated = await participants.link_my_agent4k_identity(
        student,
        project_code="TBA-2026-G01",
        adapter=adapter,
    )

    assert first.agent4k_user_id == 42 and first.created is True
    assert repeated.agent4k_user_id == 42 and repeated.created is False
    assert adapter.calls == 1
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

    for code, name in (("business_analyst", "Бизнес-аналитик"), ("data_scientist", "DS")):
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
    factory = session_factory(database_url)
    roles = RoleService(factory)
    await roles.create_draft(
        admin,
        project_code="TBA-2026-G01",
        draft=sample_role("data_scientist", "Data Scientist"),
    )
    await roles.publish(
        admin,
        project_code="TBA-2026-G01",
        role_code="data_scientist",
        adapter=PublishedRoleAdapter(),
    )
    await assessments.create_spec_draft(
        admin, project_code="TBA-2026-G01", draft=sample_spec()
    )
    await assessments.publish_spec(admin, project_code="TBA-2026-G01")

    with pytest.raises(AssessmentError, match="не назначена"):
        await assessments.assign(
            admin,
            project_code="TBA-2026-G01",
            participant_id=participant_id,
            role_code="data_scientist",
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
