from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserSystemRole(Base):
    __tablename__ = "user_system_roles"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    course_external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    course: Mapped[str] = mapped_column(String(255))
    cohort: Mapped[str | None] = mapped_column(String(128))
    business_problem: Mapped[str] = mapped_column(Text)
    expected_result: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class ProjectStage(Base, TimestampMixin):
    __tablename__ = "project_stages"
    __table_args__ = (UniqueConstraint("project_id", "stage", name="uq_project_stage"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    expected_artifacts_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft")


class ProjectParticipant(Base, TimestampMixin):
    __tablename__ = "project_participants"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_participant"),
        UniqueConstraint("project_id", "email", name="uq_project_participant_email"),
        CheckConstraint(
            "user_id IS NOT NULL OR status = 'invited'",
            name="ck_project_participant_identity",
        ),
        CheckConstraint(
            "agent4k_user_id IS NOT NULL OR agent4k_linked_at IS NULL",
            name="ck_project_participant_agent4k_link",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    agent4k_user_id: Mapped[int | None] = mapped_column(BigInteger)
    agent4k_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="invited")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectRole(Base, TimestampMixin):
    __tablename__ = "project_roles"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_project_role_code"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))


class ProjectRoleVersion(Base, TimestampMixin):
    __tablename__ = "project_role_versions"
    __table_args__ = (
        UniqueConstraint("project_role_id", "version", name="uq_role_version"),
        CheckConstraint(
            "(agent4k_role_profile_version_id IS NULL AND "
            "agent4k_role_profile_checksum IS NULL) OR "
            "(agent4k_role_profile_version_id > 0 AND "
            "agent4k_role_profile_checksum ~ '^[0-9a-f]{64}$')",
            name="ck_project_role_agent4k_mapping",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_role_id: Mapped[int] = mapped_column(
        ForeignKey("project_roles.id", ondelete="RESTRICT")
    )
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), default="draft")
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    agent4k_role_profile_version_id: Mapped[int | None] = mapped_column(BigInteger)
    agent4k_role_profile_checksum: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ParticipantRole(Base):
    __tablename__ = "project_participant_roles"
    __table_args__ = (
        Index(
            "uq_participant_primary_role",
            "participant_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("project_participants.id", ondelete="CASCADE"), primary_key=True
    )
    project_role_version_id: Mapped[int] = mapped_column(
        ForeignKey("project_role_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectAssessmentSpec(Base, TimestampMixin):
    __tablename__ = "project_assessment_specs"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_project_spec_version"),
        CheckConstraint("required_case_count > 0", name="ck_spec_required_case_count"),
        CheckConstraint("daily_case_limit = 1", name="ck_spec_daily_case_limit"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), default="draft")
    assessment_configuration_ref: Mapped[str] = mapped_column(String(255))
    assessment_configuration_checksum: Mapped[str] = mapped_column(String(64))
    methodology_ref: Mapped[str] = mapped_column(String(255))
    required_case_count: Mapped[int]
    daily_case_limit: Mapped[int] = mapped_column(default=1)
    timezone: Mapped[str] = mapped_column(String(64))
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_recipient_policy: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssessmentAssignment(Base, TimestampMixin):
    __tablename__ = "assessment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "project_assessment_spec_id",
            "project_role_version_id",
            name="uq_assignment_scope",
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("project_participants.id", ondelete="RESTRICT")
    )
    project_assessment_spec_id: Mapped[int] = mapped_column(
        ForeignKey("project_assessment_specs.id", ondelete="RESTRICT")
    )
    project_role_version_id: Mapped[int] = mapped_column(
        ForeignKey("project_role_versions.id", ondelete="RESTRICT")
    )
    external_cycle_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="assigned")
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectAssessmentContextSnapshot(Base):
    __tablename__ = "project_assessment_context_snapshots"
    __table_args__ = (
        UniqueConstraint("assessment_assignment_id", name="uq_context_snapshot_assignment"),
        CheckConstraint("status = 'published'", name="ck_context_snapshot_status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    assessment_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_assignments.id", ondelete="RESTRICT")
    )
    assignment_ref: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="published")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))
    published_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CaseDelivery(Base, TimestampMixin):
    __tablename__ = "case_deliveries"
    __table_args__ = (
        UniqueConstraint("assessment_assignment_id", "delivery_date", name="uq_daily_delivery"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    assessment_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_assignments.id", ondelete="RESTRICT")
    )
    external_case_id: Mapped[str | None] = mapped_column(String(255))
    external_session_id: Mapped[str | None] = mapped_column(String(255))
    delivery_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="reserved")
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_participant_id: Mapped[int] = mapped_column(
        ForeignKey("project_participants.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

