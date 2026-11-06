import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.projects import AccessDeniedError, TelegramIdentity, normalize_project_code
from app.application.roles import definition_checksum
from app.models import (
    AssessmentAssignment,
    AuditEvent,
    CaseDelivery,
    ParticipantRole,
    Project,
    ProjectAssessmentContextSnapshot,
    ProjectAssessmentSpec,
    ProjectParticipant,
    ProjectRole,
    ProjectRoleVersion,
    ProjectStage,
    User,
    UserSystemRole,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECIPIENT_POLICIES = frozenset({"participant", "instructor", "participant_and_instructor"})


class AssessmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssessmentSpecDraft:
    assessment_configuration_ref: str
    assessment_configuration_checksum: str
    methodology_ref: str
    required_case_count: int
    available_from: date | None
    available_until: date | None
    result_recipient_policy: str


@dataclass(frozen=True)
class AssessmentSpecView:
    project_code: str
    version: int
    status: str
    required_case_count: int
    checksum: str
    runtime_admission: str


@dataclass(frozen=True)
class AssessmentAssignmentView:
    id: int
    project_code: str
    role_code: str
    role_version: int
    spec_version: int
    status: str
    required_cases: int
    completed_cases: int
    remaining_cases: int
    has_active_case: bool
    runtime_connected: bool


@dataclass(frozen=True)
class AssessmentContextSnapshotView:
    id: int
    assignment_id: int
    assignment_ref: str
    status: str
    checksum: str


def validate_spec_draft(draft: AssessmentSpecDraft) -> AssessmentSpecDraft:
    configuration_ref = draft.assessment_configuration_ref.strip()
    methodology_ref = draft.methodology_ref.strip()
    checksum = draft.assessment_configuration_checksum.strip().lower()
    if not configuration_ref or len(configuration_ref) > 255:
        raise ValueError("Укажите ссылку на конфигурацию оценки длиной до 255 символов.")
    if not SHA256_RE.fullmatch(checksum):
        raise ValueError("Checksum конфигурации должен быть SHA-256 из 64 hex-символов.")
    if not methodology_ref or len(methodology_ref) > 255:
        raise ValueError("Укажите ссылку на версию методологии.")
    if not 1 <= draft.required_case_count <= 100:
        raise ValueError("Число кейсов должно быть от 1 до 100.")
    if draft.available_from and draft.available_until:
        if draft.available_until < draft.available_from:
            raise ValueError("Конец периода оценки не может быть раньше начала.")
    if draft.result_recipient_policy not in RECIPIENT_POLICIES:
        raise ValueError("Неизвестная политика получателей результата.")
    return AssessmentSpecDraft(
        assessment_configuration_ref=configuration_ref,
        assessment_configuration_checksum=checksum,
        methodology_ref=methodology_ref,
        required_case_count=draft.required_case_count,
        available_from=draft.available_from,
        available_until=draft.available_until,
        result_recipient_policy=draft.result_recipient_policy,
    )


async def _require_admin(session: AsyncSession, identity: TelegramIdentity) -> User:
    actor = await session.scalar(
        select(User).where(User.telegram_user_id == identity.telegram_user_id)
    )
    if actor is None or not actor.is_active:
        raise AccessDeniedError("Пользователь не зарегистрирован.")
    if await session.get(UserSystemRole, (actor.id, "admin")) is None:
        raise AccessDeniedError("Управлять оценками может только администратор.")
    return actor


async def _project(session: AsyncSession, code: str) -> Project:
    project = await session.scalar(
        select(Project).where(Project.code == normalize_project_code(code))
    )
    if project is None:
        raise AssessmentError("Проект с таким кодом не найден.")
    return project


def _period(
    draft: AssessmentSpecDraft, timezone_name: str
) -> tuple[datetime | None, datetime | None]:
    timezone = ZoneInfo(timezone_name)
    start = (
        datetime.combine(draft.available_from, time.min, timezone).astimezone(UTC)
        if draft.available_from
        else None
    )
    end = (
        datetime.combine(draft.available_until, time.max, timezone).astimezone(UTC)
        if draft.available_until
        else None
    )
    return start, end


class AssessmentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_spec_draft(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        draft: AssessmentSpecDraft,
    ) -> AssessmentSpecView:
        validated = validate_spec_draft(draft)
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            existing_draft = await session.scalar(
                select(ProjectAssessmentSpec.id).where(
                    ProjectAssessmentSpec.project_id == project.id,
                    ProjectAssessmentSpec.status == "draft",
                )
            )
            if existing_draft is not None:
                raise AssessmentError("У проекта уже есть draft спецификации.")
            latest = await session.scalar(
                select(func.max(ProjectAssessmentSpec.version)).where(
                    ProjectAssessmentSpec.project_id == project.id
                )
            )
            version = int(latest or 0) + 1
            available_from, available_until = _period(validated, project.timezone)
            snapshot = {
                "schema_version": 1,
                "kind": "project_assessment_spec",
                "project_code": project.code,
                "version": version,
                "assessment_configuration": {
                    "ref": validated.assessment_configuration_ref,
                    "checksum": validated.assessment_configuration_checksum,
                },
                "methodology_ref": validated.methodology_ref,
                "required_case_count": validated.required_case_count,
                "daily_case_limit": 1,
                "timezone": project.timezone,
                "available_from": available_from.isoformat() if available_from else None,
                "available_until": available_until.isoformat() if available_until else None,
                "result_recipient_policy": validated.result_recipient_policy,
                "runtime_admission": "pending_agent4k_verification",
            }
            checksum = definition_checksum(snapshot)
            spec = ProjectAssessmentSpec(
                project_id=project.id,
                version=version,
                status="draft",
                assessment_configuration_ref=validated.assessment_configuration_ref,
                assessment_configuration_checksum=validated.assessment_configuration_checksum,
                methodology_ref=validated.methodology_ref,
                required_case_count=validated.required_case_count,
                daily_case_limit=1,
                timezone=project.timezone,
                available_from=available_from,
                available_until=available_until,
                result_recipient_policy=validated.result_recipient_policy,
                snapshot_json=snapshot,
                checksum=checksum,
            )
            session.add(spec)
            await session.flush()
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_assessment_spec",
                    entity_id=str(spec.id),
                    action="draft_created",
                    payload_json={
                        "version": version,
                        "runtime_admission": snapshot["runtime_admission"],
                    },
                )
            )
            return AssessmentSpecView(
                project.code, version, "draft", validated.required_case_count, checksum,
                str(snapshot["runtime_admission"]),
            )

    async def publish_spec(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> AssessmentSpecView:
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            spec = await session.scalar(
                select(ProjectAssessmentSpec)
                .where(
                    ProjectAssessmentSpec.project_id == project.id,
                    ProjectAssessmentSpec.status == "draft",
                )
                .order_by(ProjectAssessmentSpec.version.desc())
                .with_for_update()
            )
            if spec is None:
                raise AssessmentError("У проекта нет draft спецификации.")
            if definition_checksum(dict(spec.snapshot_json)) != spec.checksum:
                raise AssessmentError("Checksum snapshot спецификации не совпадает.")
            spec.status = "published"
            spec.published_at = datetime.now(UTC)
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_assessment_spec",
                    entity_id=str(spec.id),
                    action="published",
                    payload_json={"version": spec.version, "runtime_admission": "pending"},
                )
            )
            return AssessmentSpecView(
                project.code,
                spec.version,
                spec.status,
                spec.required_case_count,
                spec.checksum,
                str(spec.snapshot_json["runtime_admission"]),
            )

    async def assign(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        participant_id: int,
        role_code: str,
    ) -> AssessmentAssignmentView:
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await _project(session, project_code)
            participant = await session.get(ProjectParticipant, participant_id)
            if participant is None or participant.project_id != project.id:
                raise AssessmentError("Участник не найден в этом проекте.")
            spec = await session.scalar(
                select(ProjectAssessmentSpec)
                .where(
                    ProjectAssessmentSpec.project_id == project.id,
                    ProjectAssessmentSpec.status == "published",
                )
                .order_by(ProjectAssessmentSpec.version.desc())
            )
            if spec is None:
                raise AssessmentError("У проекта нет опубликованной спецификации.")
            role_version = await session.scalar(
                select(ProjectRoleVersion)
                .join(ParticipantRole)
                .join(ProjectRole)
                .where(
                    ParticipantRole.participant_id == participant.id,
                    ProjectRole.code == role_code.strip().lower(),
                    ProjectRoleVersion.status == "published",
                )
                .order_by(ProjectRoleVersion.version.desc())
            )
            if role_version is None:
                raise AssessmentError("Участнику не назначена опубликованная версия роли.")
            assignment = await session.scalar(
                select(AssessmentAssignment).where(
                    AssessmentAssignment.participant_id == participant.id,
                    AssessmentAssignment.project_assessment_spec_id == spec.id,
                    AssessmentAssignment.project_role_version_id == role_version.id,
                )
            )
            if assignment is None:
                assignment = AssessmentAssignment(
                    participant_id=participant.id,
                    project_assessment_spec_id=spec.id,
                    project_role_version_id=role_version.id,
                    status="assigned",
                    assigned_by_user_id=actor.id,
                )
                session.add(assignment)
                await session.flush()
                session.add(
                    AuditEvent(
                        actor_user_id=actor.id,
                        project_id=project.id,
                        entity_type="assessment_assignment",
                        entity_id=str(assignment.id),
                        action="assigned",
                        payload_json={
                            "spec_version": spec.version,
                            "role_version_id": role_version.id,
                            "runtime_connected": False,
                        },
                    )
                )
            role = await session.get(ProjectRole, role_version.project_role_id)
            if role is None:
                raise AssessmentError("Проектная роль назначения не найдена.")
            return AssessmentAssignmentView(
                assignment.id, project.code, role.code, role_version.version, spec.version,
                assignment.status, spec.required_case_count, 0, spec.required_case_count,
                False, assignment.external_cycle_id is not None,
            )

    async def publish_context_snapshot(
        self, identity: TelegramIdentity, *, assignment_id: int
    ) -> AssessmentContextSnapshotView:
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            assignment = await session.scalar(
                select(AssessmentAssignment)
                .where(AssessmentAssignment.id == assignment_id)
                .with_for_update()
            )
            if assignment is None:
                raise AssessmentError("Назначение оценки не найдено.")
            existing = await session.scalar(
                select(ProjectAssessmentContextSnapshot).where(
                    ProjectAssessmentContextSnapshot.assessment_assignment_id
                    == assignment.id
                )
            )
            if existing is not None:
                if definition_checksum(dict(existing.snapshot_json)) != existing.checksum:
                    raise AssessmentError("Checksum snapshot контекста не совпадает.")
                return AssessmentContextSnapshotView(
                    existing.id,
                    assignment.id,
                    existing.assignment_ref,
                    existing.status,
                    existing.checksum,
                )
            if assignment.status not in {"assigned", "active"}:
                raise AssessmentError(
                    "Контекст можно опубликовать только для активного назначения."
                )

            participant = await session.get(ProjectParticipant, assignment.participant_id)
            spec = await session.get(
                ProjectAssessmentSpec, assignment.project_assessment_spec_id
            )
            role_version = await session.get(
                ProjectRoleVersion, assignment.project_role_version_id
            )
            if participant is None or spec is None or role_version is None:
                raise AssessmentError("Контекст назначения неполон.")
            project = await session.get(Project, participant.project_id)
            role = await session.get(ProjectRole, role_version.project_role_id)
            if project is None or role is None or spec.project_id != project.id:
                raise AssessmentError("Контекст назначения противоречив.")
            if participant.agent4k_user_id is None:
                raise AssessmentError("Участник ещё не связан с пользователем 4К.")
            if not project.course_external_id:
                raise AssessmentError("У проекта отсутствует идентификатор курса.")
            if spec.status != "published":
                raise AssessmentError("Спецификация оценки не опубликована.")
            if role_version.status != "published":
                raise AssessmentError("Версия проектной роли не опубликована.")
            if (
                role_version.agent4k_role_profile_version_id is None
                or role_version.agent4k_role_profile_checksum is None
            ):
                raise AssessmentError("Проектная роль не связана с RoleProfileVersion 4К.")

            stages = list(
                await session.scalars(
                    select(ProjectStage)
                    .where(ProjectStage.project_id == project.id)
                    .order_by(ProjectStage.id)
                )
            )
            assignment_ref = f"edu:4k-tg-bot:p{project.id}:a{assignment.id}"
            snapshot = {
                "schema_version": 1,
                "kind": "educational_project_assessment_context",
                "assignment_ref": assignment_ref,
                "course": {
                    "external_id": project.course_external_id,
                    "name": project.course,
                    "cohort": project.cohort,
                },
                "project": {
                    "local_ref": f"project:{project.id}",
                    "code": project.code,
                    "name": project.name,
                    "business_problem": project.business_problem,
                    "expected_result": project.expected_result,
                    "description": project.description,
                    "timezone": project.timezone,
                    "stages": [
                        {
                            "stage": stage.stage,
                            "description": stage.description,
                            "expected_artifacts": list(stage.expected_artifacts_json),
                            "status": stage.status,
                        }
                        for stage in stages
                    ],
                },
                "participant": {
                    "local_ref": f"participant:{participant.id}",
                    "agent4k_user_id": participant.agent4k_user_id,
                },
                "role": {
                    "code": role.code,
                    "name": role.name,
                    "project_role_version": role_version.version,
                    "project_role_checksum": role_version.checksum,
                    "definition": dict(role_version.definition_json),
                    "agent4k_role_profile_version_id": (
                        role_version.agent4k_role_profile_version_id
                    ),
                    "agent4k_role_profile_checksum": (
                        role_version.agent4k_role_profile_checksum
                    ),
                },
                "assessment_spec": {
                    "version": spec.version,
                    "checksum": spec.checksum,
                    "assessment_configuration_ref": spec.assessment_configuration_ref,
                    "assessment_configuration_checksum": (
                        spec.assessment_configuration_checksum
                    ),
                    "methodology_ref": spec.methodology_ref,
                    "required_case_count": spec.required_case_count,
                    "daily_case_limit": spec.daily_case_limit,
                    "timezone": spec.timezone,
                    "available_from": (
                        spec.available_from.isoformat() if spec.available_from else None
                    ),
                    "available_until": (
                        spec.available_until.isoformat() if spec.available_until else None
                    ),
                    "result_recipient_policy": spec.result_recipient_policy,
                },
            }
            checksum = definition_checksum(snapshot)
            context = ProjectAssessmentContextSnapshot(
                assessment_assignment_id=assignment.id,
                assignment_ref=assignment_ref,
                status="published",
                snapshot_json=snapshot,
                checksum=checksum,
                published_by_user_id=actor.id,
            )
            session.add(context)
            await session.flush()
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_assessment_context_snapshot",
                    entity_id=str(context.id),
                    action="published",
                    payload_json={
                        "assignment_id": assignment.id,
                        "assignment_ref": assignment_ref,
                        "checksum": checksum,
                    },
                )
            )
            return AssessmentContextSnapshotView(
                context.id, assignment.id, assignment_ref, context.status, checksum
            )

    async def my_progress(self, identity: TelegramIdentity) -> list[AssessmentAssignmentView]:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_user_id == identity.telegram_user_id)
            )
            if user is None or not user.is_active:
                return []
            rows = (
                await session.execute(
                    select(
                        AssessmentAssignment,
                        Project,
                        ProjectAssessmentSpec,
                        ProjectRole,
                        ProjectRoleVersion,
                    )
                    .join(
                        ProjectParticipant,
                        ProjectParticipant.id == AssessmentAssignment.participant_id,
                    )
                    .join(Project, Project.id == ProjectParticipant.project_id)
                    .join(
                        ProjectAssessmentSpec,
                        ProjectAssessmentSpec.id
                        == AssessmentAssignment.project_assessment_spec_id,
                    )
                    .join(
                        ProjectRoleVersion,
                        ProjectRoleVersion.id == AssessmentAssignment.project_role_version_id,
                    )
                    .join(ProjectRole, ProjectRole.id == ProjectRoleVersion.project_role_id)
                    .where(ProjectParticipant.user_id == user.id)
                    .order_by(Project.code, AssessmentAssignment.id)
                )
            ).all()
            result = []
            for assignment, project, spec, role, role_version in rows:
                completed = int(
                    await session.scalar(
                        select(func.count()).select_from(CaseDelivery).where(
                            CaseDelivery.assessment_assignment_id == assignment.id,
                            CaseDelivery.status == "completed",
                        )
                    )
                    or 0
                )
                active = bool(
                    await session.scalar(
                        select(func.count()).select_from(CaseDelivery).where(
                            CaseDelivery.assessment_assignment_id == assignment.id,
                            CaseDelivery.status.in_(("reserved", "issued")),
                        )
                    )
                )
                result.append(
                    AssessmentAssignmentView(
                        assignment.id,
                        project.code,
                        role.code,
                        role_version.version,
                        spec.version,
                        assignment.status,
                        spec.required_case_count,
                        completed,
                        max(spec.required_case_count - completed, 0),
                        active,
                        assignment.external_cycle_id is not None,
                    )
                )
            return result

    async def list_specs(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> list[AssessmentSpecView]:
        async with self._session_factory() as session:
            await _require_admin(session, identity)
            project = await _project(session, project_code)
            rows = await session.scalars(
                select(ProjectAssessmentSpec)
                .where(ProjectAssessmentSpec.project_id == project.id)
                .order_by(ProjectAssessmentSpec.version.desc())
            )
            return [
                AssessmentSpecView(
                    project.code,
                    spec.version,
                    spec.status,
                    spec.required_case_count,
                    spec.checksum,
                    str(spec.snapshot_json["runtime_admission"]),
                )
                for spec in rows
            ]
