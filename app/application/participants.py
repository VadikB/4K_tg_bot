import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.projects import AccessDeniedError, TelegramIdentity, normalize_project_code
from app.integrations.agent4k import Agent4KPort
from app.models import (
    AuditEvent,
    Invitation,
    Project,
    ProjectParticipant,
    User,
    UserSystemRole,
)


class InvitationError(RuntimeError):
    pass


class ParticipantIdentityNotReadyError(ValueError):
    pass


@dataclass(frozen=True)
class InvitationSecret:
    participant_id: int
    project_code: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class ParticipantView:
    id: int
    display_name: str
    status: str
    telegram_connected: bool
    telegram_id_configured: bool
    email_configured: bool
    agent4k_connected: bool


@dataclass(frozen=True)
class ParticipantLinkView:
    participant_id: int
    agent4k_user_id: int
    created: bool


@dataclass(frozen=True)
class FeedbackRecipient:
    project_code: str
    participant_name: str
    teacher_telegram_user_id: int


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not email or len(email) > 320:
        raise ValueError("Email участника должен содержать от 1 до 320 символов.")
    return email


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_telegram_user_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValueError("Введите положительный числовой Telegram ID участника.")
    return value


async def _load_actor(session: AsyncSession, identity: TelegramIdentity) -> User:
    actor = await session.scalar(
        select(User).where(User.telegram_user_id == identity.telegram_user_id)
    )
    if actor is None or not actor.is_active:
        raise AccessDeniedError("Пользователь не зарегистрирован.")
    return actor


async def _require_admin(session: AsyncSession, identity: TelegramIdentity) -> User:
    actor = await _load_actor(session, identity)
    if await session.get(UserSystemRole, (actor.id, "admin")) is None:
        raise AccessDeniedError("Управлять участниками может только администратор.")
    return actor


class ParticipantService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        invitation_ttl_hours: int,
    ) -> None:
        if not 1 <= invitation_ttl_hours <= 720:
            raise ValueError("invitation_ttl_hours must be between 1 and 720")
        self._session_factory = session_factory
        self._invitation_ttl = timedelta(hours=invitation_ttl_hours)

    async def link_assessment_subject(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        participant_id: int,
        organization_ref: str,
        adapter: Agent4KPort,
    ) -> str:
        if not organization_ref:
            raise ParticipantIdentityNotReadyError("Не настроен тестовый контур 4К.")
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await session.scalar(
                select(Project).where(
                    Project.code == normalize_project_code(project_code),
                    Project.created_by_user_id == actor.id,
                )
            )
            if project is None:
                raise AccessDeniedError("Проект недоступен.")
            participant = await session.scalar(
                select(ProjectParticipant)
                .where(
                    ProjectParticipant.id == participant_id,
                    ProjectParticipant.project_id == project.id,
                    ProjectParticipant.status == "active",
                )
                .with_for_update()
            )
            if participant is None:
                raise AccessDeniedError("Участник недоступен.")
            existing_subject = participant.external_subject_ref is not None
            if not existing_subject:
                participant.external_subject_ref = str(uuid4())
            subject = participant.external_subject_ref
            assert subject is not None
            if existing_subject and participant.agent4k_linked_at is not None:
                return subject
        # Commit the random key BEFORE HTTP; a timeout always reuses this key.
        await adapter.resolve_subject(
            external_subject_ref=subject, organization_ref=organization_ref
        )
        async with self._session_factory.begin() as session:
            await _require_admin(session, identity)
            participant = await session.get(ProjectParticipant, participant_id)
            if participant is None or participant.external_subject_ref != subject:
                raise ParticipantIdentityNotReadyError("Связь участника изменилась.")
            if participant.agent4k_linked_at is None:
                participant.agent4k_linked_at = datetime.now(UTC)
                session.add(
                    AuditEvent(
                        actor_user_id=actor.id,
                        project_id=project.id,
                        entity_type="project_participant",
                        entity_id=str(participant_id),
                        action="opaque_subject_linked",
                        payload_json={"organization_ref": organization_ref},
                    )
                )
        return subject

    async def feedback_recipient(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> FeedbackRecipient:
        async with self._session_factory() as session:
            actor = await _load_actor(session, identity)
            row = await session.execute(
                select(Project.code, ProjectParticipant.display_name, User.telegram_user_id)
                .join(ProjectParticipant, ProjectParticipant.project_id == Project.id)
                .join(User, User.id == Project.created_by_user_id)
                .join(UserSystemRole, UserSystemRole.user_id == User.id)
                .where(
                    Project.code == normalize_project_code(project_code),
                    ProjectParticipant.user_id == actor.id,
                    ProjectParticipant.status == "active",
                    User.is_active,
                    UserSystemRole.role == "admin",
                )
            )
            recipient = row.one_or_none()
            if recipient is None:
                raise AccessDeniedError("Проект недоступен для отправки отзыва.")
            return FeedbackRecipient(*recipient)

    async def create_invitation(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        participant_name: str,
        participant_email: str,
        now: datetime | None = None,
    ) -> InvitationSecret:
        name = participant_name.strip()
        if not name or len(name) > 255:
            raise ValueError("Имя участника должно содержать от 1 до 255 символов.")
        email = normalize_email(participant_email)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        token = secrets.token_urlsafe(32)
        token_hash = invitation_token_hash(token)
        expires_at = current + self._invitation_ttl
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await session.scalar(
                select(Project).where(Project.code == normalize_project_code(project_code))
            )
            if project is None:
                raise ValueError("Проект с таким кодом не найден.")
            existing_email = await session.scalar(
                select(ProjectParticipant.id).where(
                    ProjectParticipant.project_id == project.id,
                    ProjectParticipant.email == email,
                )
            )
            if existing_email is not None:
                raise ValueError("Участник с таким email уже добавлен в проект.")
            participant = ProjectParticipant(
                project_id=project.id,
                user_id=None,
                display_name=name,
                email=email,
                status="invited",
            )
            session.add(participant)
            await session.flush()
            session.add(
                Invitation(
                    project_participant_id=participant.id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    created_by_user_id=actor.id,
                )
            )
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_participant",
                    entity_id=str(participant.id),
                    action="invited",
                    payload_json={"status": "invited", "email_configured": True},
                )
            )
            return InvitationSecret(participant.id, project.code, token, expires_at)

    async def create_telegram_invitation(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        participant_name: str,
        participant_email: str,
        telegram_user_id: int,
        now: datetime | None = None,
    ) -> InvitationSecret:
        name = participant_name.strip()
        if not name or len(name) > 255:
            raise ValueError("ФИО участника должно содержать от 1 до 255 символов.")
        email = normalize_email(participant_email)
        invited_id = validate_telegram_user_id(telegram_user_id)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        token = secrets.token_urlsafe(32)
        async with self._session_factory.begin() as session:
            actor = await _require_admin(session, identity)
            project = await session.scalar(
                select(Project).where(Project.code == normalize_project_code(project_code))
            )
            if project is None or project.created_by_user_id != actor.id:
                raise AccessDeniedError("Проект не найден среди ваших проектов.")
            existing_email = await session.scalar(
                select(ProjectParticipant.id).where(
                    ProjectParticipant.project_id == project.id,
                    ProjectParticipant.email == email,
                )
            )
            if existing_email is not None:
                raise ValueError("Участник с таким email уже добавлен в проект.")
            existing = await session.scalar(
                select(ProjectParticipant.id)
                .outerjoin(User, User.id == ProjectParticipant.user_id)
                .where(
                    ProjectParticipant.project_id == project.id,
                    or_(
                        ProjectParticipant.invited_telegram_user_id == invited_id,
                        User.telegram_user_id == invited_id,
                    ),
                )
            )
            if existing is not None:
                raise ValueError("Участник с таким Telegram ID уже добавлен в проект.")
            participant = ProjectParticipant(
                project_id=project.id,
                user_id=None,
                display_name=name,
                invited_telegram_user_id=invited_id,
                email=email,
                status="invited",
            )
            session.add(participant)
            await session.flush()
            session.add(
                Invitation(
                    project_participant_id=participant.id,
                    token_hash=invitation_token_hash(token),
                    expires_at=current + self._invitation_ttl,
                    created_by_user_id=actor.id,
                )
            )
            session.add(
                AuditEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    entity_type="project_participant",
                    entity_id=str(participant.id),
                    action="invited",
                    payload_json={
                        "status": "invited",
                        "telegram_id_configured": True,
                        "email_configured": True,
                    },
                )
            )
            return InvitationSecret(
                participant.id, project.code, token, current + self._invitation_ttl
            )

    async def accept_invitation(
        self,
        identity: TelegramIdentity,
        *,
        token: str,
        now: datetime | None = None,
    ) -> Project:
        if not token or len(token) > 256:
            raise InvitationError("Некорректное приглашение.")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        async with self._session_factory.begin() as session:
            invitation = await session.scalar(
                select(Invitation)
                .where(Invitation.token_hash == invitation_token_hash(token))
                .with_for_update()
            )
            if invitation is None:
                raise InvitationError("Приглашение не найдено.")
            if invitation.used_at is not None:
                raise InvitationError("Приглашение уже использовано.")
            if invitation.expires_at <= current:
                raise InvitationError("Срок действия приглашения истёк.")
            participant = await session.get(
                ProjectParticipant, invitation.project_participant_id, with_for_update=True
            )
            if participant is None or participant.status != "invited":
                raise InvitationError("Приглашение больше не активно.")
            if (
                participant.invited_telegram_user_id is not None
                and participant.invited_telegram_user_id != identity.telegram_user_id
            ):
                raise InvitationError("Приглашение предназначено другому Telegram ID.")
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
            elif not user.is_active:
                raise AccessDeniedError("Учётная запись отключена.")
            existing = await session.scalar(
                select(ProjectParticipant.id).where(
                    ProjectParticipant.project_id == participant.project_id,
                    ProjectParticipant.user_id == user.id,
                )
            )
            if existing is not None and existing != participant.id:
                raise InvitationError("Вы уже являетесь участником этого проекта.")
            participant.user_id = user.id
            if participant.invited_telegram_user_id is None:
                participant.display_name = identity.display_name
            participant.status = "active"
            participant.joined_at = current
            invitation.used_at = current
            project = await session.get(Project, participant.project_id)
            if project is None:
                raise InvitationError("Проект приглашения не найден.")
            session.add(
                AuditEvent(
                    actor_user_id=user.id,
                    project_id=project.id,
                    entity_type="project_participant",
                    entity_id=str(participant.id),
                    action="invitation_accepted",
                    payload_json={"status": "active"},
                )
            )
            return project

    async def list_participants(
        self, identity: TelegramIdentity, *, project_code: str
    ) -> list[ParticipantView]:
        async with self._session_factory() as session:
            await _require_admin(session, identity)
            project = await session.scalar(
                select(Project).where(Project.code == normalize_project_code(project_code))
            )
            if project is None:
                raise ValueError("Проект с таким кодом не найден.")
            rows = await session.scalars(
                select(ProjectParticipant)
                .where(ProjectParticipant.project_id == project.id)
                .order_by(ProjectParticipant.created_at)
            )
            return [
                ParticipantView(
                    id=item.id,
                    display_name=item.display_name,
                    status=item.status,
                    telegram_connected=item.user_id is not None,
                    telegram_id_configured=item.invited_telegram_user_id is not None,
                    email_configured=item.email is not None,
                    agent4k_connected=(
                        item.agent4k_user_id is not None
                        or (
                            item.external_subject_ref is not None
                            and item.agent4k_linked_at is not None
                        )
                    ),
                )
                for item in rows
            ]

    async def link_my_agent4k_identity(
        self,
        identity: TelegramIdentity,
        *,
        project_code: str,
        adapter: Agent4KPort,
        now: datetime | None = None,
    ) -> ParticipantLinkView:
        del adapter
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        normalized_code = normalize_project_code(project_code)
        async with self._session_factory() as session:
            user = await _load_actor(session, identity)
            participant = await session.scalar(
                select(ProjectParticipant)
                .join(Project, Project.id == ProjectParticipant.project_id)
                .where(
                    Project.code == normalized_code,
                    ProjectParticipant.user_id == user.id,
                    ProjectParticipant.status == "active",
                )
            )
            if participant is None:
                raise AccessDeniedError("Активное участие в проекте не найдено.")
            if participant.agent4k_user_id is not None:
                return ParticipantLinkView(
                    participant.id,
                    participant.agent4k_user_id,
                    False,
                )
            raise ParticipantIdentityNotReadyError(
                "Связь с 4К по непрозрачному ключу ещё не подключена."
            )
