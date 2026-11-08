import hashlib
import unicodedata
from datetime import date
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.utils.deep_linking import create_start_link

from app.application.assessments import AssessmentError, AssessmentService, AssessmentSpecDraft
from app.application.participants import InvitationError, ParticipantService
from app.application.projects import (
    AccessDeniedError,
    DuplicateProjectCodeError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)
from app.application.roles import RoleDraft, RoleError, RoleService, parse_items
from app.integrations.agent4k import Agent4KPort, Agent4KUnavailableError

router = Router()


class ProjectWizard(StatesGroup):
    name = State()
    course = State()
    cohort = State()
    business_problem = State()
    expected_result = State()
    description = State()
    dates = State()


class ParticipantWizard(StatesGroup):
    project_code = State()
    display_name = State()
    email = State()


class RoleWizard(StatesGroup):
    project_code = State()
    code = State()
    name = State()
    mission = State()
    responsibilities = State()
    typical_tasks = State()
    expected_outputs = State()
    interactions = State()
    agent4k_role_profile_version_id = State()
    agent4k_role_profile_checksum = State()
    crisp_dm_stages = State()


class AssessmentSpecWizard(StatesGroup):
    project_code = State()
    configuration_ref = State()
    configuration_checksum = State()
    methodology_ref = State()
    required_case_count = State()
    period = State()
    recipient_policy = State()


def identity_from_message(message: Message) -> TelegramIdentity:
    if message.from_user is None:
        raise AccessDeniedError("Telegram не передал идентификатор пользователя.")
    return TelegramIdentity(
        telegram_user_id=message.from_user.id,
        telegram_username=message.from_user.username,
        display_name=message.from_user.full_name,
    )


def parse_optional_dates(value: str) -> tuple[date | None, date | None]:
    normalized = value.strip()
    if normalized == "-":
        return None, None
    parts = normalized.split()
    if len(parts) != 2:
        raise ValueError("Введите две даты в формате ДД.ММ.ГГГГ или '-'.")
    try:
        parsed = [date.fromisoformat("-".join(reversed(item.split(".")))) for item in parts]
        starts_on, ends_on = parsed
    except ValueError as exc:
        raise ValueError("Введите корректные даты в формате ДД.ММ.ГГГГ.") from exc
    return starts_on, ends_on


def parse_project_timezone(value: str) -> str:
    timezone_name = value.strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Неизвестный часовой пояс IANA.") from exc
    return timezone_name


def parse_required_answer(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Поле «{field_name}» не может быть пустым.")
    if len(normalized) > 4000:
        raise ValueError(f"Поле «{field_name}» не должно превышать 4000 символов.")
    return normalized


def generate_project_code() -> str:
    return f"PRJ-{uuid4().hex[:12].upper()}"


def generate_course_external_id(course_name: str) -> str:
    canonical_name = " ".join(
        unicodedata.normalize("NFKC", course_name).casefold().split()
    )
    digest = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()[:16]
    return f"course-{digest}"


@router.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject,
    project_service: ProjectService,
    participant_service: ParticipantService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if command.args:
        try:
            project = await participant_service.accept_invitation(
                identity_from_message(message), token=command.args
            )
        except (InvitationError, AccessDeniedError) as exc:
            await message.answer(f"Не удалось принять приглашение: {exc}")
            return
        await message.answer(
            f"Вы подключены к проекту {project.code} — {project.name}.\n"
            "Используйте /projects для просмотра карточки."
        )
        try:
            await participant_service.link_my_agent4k_identity(
                identity_from_message(message),
                project_code=project.code,
                adapter=agent4k_adapter,
            )
        except (Agent4KUnavailableError, ValueError, AccessDeniedError, RuntimeError):
            await message.answer(
                "Связь с 4К пока не создана. Проект доступен; повторите позже командой /link_4k."
            )
        return
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if is_admin:
        await message.answer(
            "Вы вошли как администратор.\n"
            "/new_project — создать проект\n"
            "/projects — список проектов\n"
            "/add_participant — пригласить участника\n"
            "/new_role — создать CRISP-DM-роль"
        )
    else:
        await message.answer(
            "Добро пожаловать в учебный контур 4К. "
            "Для подключения к проекту используйте персональную ссылку преподавателя."
        )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n"
        "/start — подключение к боту\n"
        "/projects — мои проекты\n"
        "/new_project — создать проект (администратор)\n"
        "/add_participant — пригласить участника (администратор)\n"
        "/participants CODE — участники проекта (администратор)\n"
        "/new_role — создать draft роли (администратор)\n"
        "/publish_role PROJECT ROLE — опубликовать роль\n"
        "/roles PROJECT — версии ролей\n"
        "/assign_role PROJECT PARTICIPANT_ID ROLE — назначить роль\n"
        "/my_roles — мои роли в проектах\n"
        "/new_spec — создать спецификацию оценки\n"
        "/publish_spec PROJECT — опубликовать спецификацию\n"
        "/specs PROJECT — версии спецификации\n"
        "/assign_assessment PROJECT PARTICIPANT_ID ROLE — назначить оценку\n"
        "/publish_context ASSIGNMENT_ID — зафиксировать контекст назначения\n"
        "/prepare_cycle ASSIGNMENT_ID — проверить admission и подготовку Cycle\n"
        "/admission_programs ASSIGNMENT_ID — совместимые программы 4К\n"
        "/connect_program ASSIGNMENT_ID PROGRAM_ID — подключить программу\n"
        "/progress — прогресс оценки\n"
        "/case — получить или продолжить кейс\n"
        "/cancel — отменить текущий диалог"
    )


@router.message(Command("new_project"))
async def new_project(
    message: Message,
    state: FSMContext,
    project_service: ProjectService,
    default_project_timezone: str,
) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Создавать проекты может только администратор.")
        return
    await state.clear()
    try:
        timezone_name = parse_project_timezone(default_project_timezone)
    except ValueError:
        await message.answer("Проект не начат: неверен DEFAULT_PROJECT_TIMEZONE.")
        return
    await state.update_data(code=generate_project_code(), timezone=timezone_name)
    await state.set_state(ProjectWizard.name)
    await message.answer("Название проекта:")


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Диалог отменён.")


@router.message(ProjectWizard.name, F.text)
async def project_name(message: Message, state: FSMContext) -> None:
    try:
        name = parse_required_answer(message.text or "", "Название проекта")
    except ValueError as exc:
        await message.answer(f"Ответ не принят: {exc}\nВведите название проекта:")
        return
    await state.update_data(name=name)
    await state.set_state(ProjectWizard.course)
    await message.answer("Название курса:")


@router.message(ProjectWizard.course, F.text)
async def project_course(message: Message, state: FSMContext) -> None:
    try:
        course = parse_required_answer(message.text or "", "Название курса")
    except ValueError as exc:
        await message.answer(f"Ответ не принят: {exc}\nВведите название курса:")
        return
    await state.update_data(
        course=course,
        course_external_id=generate_course_external_id(course),
    )
    await state.set_state(ProjectWizard.cohort)
    await message.answer("Поток или учебная группа; '-' если не требуется:")


@router.message(ProjectWizard.cohort, F.text)
async def project_cohort(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "-":
        cohort = None
    else:
        try:
            cohort = parse_required_answer(text, "Поток или учебная группа")
        except ValueError as exc:
            await message.answer(
                f"Ответ не принят: {exc}\nВведите группу или '-' если она не требуется:"
            )
            return
    await state.update_data(cohort=cohort)
    await state.set_state(ProjectWizard.business_problem)
    await message.answer("Опишите бизнес-проблему:")


@router.message(ProjectWizard.business_problem, F.text)
async def project_problem(message: Message, state: FSMContext) -> None:
    try:
        value = parse_required_answer(message.text or "", "Бизнес-проблема")
    except ValueError as exc:
        await message.answer(f"Ответ не принят: {exc}\nОпишите бизнес-проблему:")
        return
    await state.update_data(business_problem=value)
    await state.set_state(ProjectWizard.expected_result)
    await message.answer("Какой результат должен получить проект?")


@router.message(ProjectWizard.expected_result, F.text)
async def project_result(message: Message, state: FSMContext) -> None:
    try:
        value = parse_required_answer(message.text or "", "Ожидаемый результат")
    except ValueError as exc:
        await message.answer(
            f"Ответ не принят: {exc}\nКакой результат должен получить проект?"
        )
        return
    await state.update_data(expected_result=value)
    await state.set_state(ProjectWizard.description)
    await message.answer("Краткое описание проекта:")


@router.message(ProjectWizard.description, F.text)
async def project_description(message: Message, state: FSMContext) -> None:
    try:
        value = parse_required_answer(message.text or "", "Описание проекта")
    except ValueError as exc:
        await message.answer(
            f"Ответ не принят: {exc}\nВведите краткое описание проекта:"
        )
        return
    await state.update_data(description=value)
    await state.set_state(ProjectWizard.dates)
    await message.answer("Даты начала и завершения: ДД.ММ.ГГГГ ДД.ММ.ГГГГ или '-':")


@router.message(ProjectWizard.dates, F.text)
async def project_dates(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    try:
        starts_on, ends_on = parse_optional_dates(message.text or "")
        data: dict[str, Any] = await state.get_data()
        draft = ProjectDraft(**data, starts_on=starts_on, ends_on=ends_on)
        project = await project_service.create_project(identity_from_message(message), draft)
    except (ValueError, DuplicateProjectCodeError, AccessDeniedError) as exc:
        await message.answer(f"Проект не создан: {exc}\nИсправьте даты или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"Проект создан.\n"
        f"{project.code} — {project.name}\n"
        f"Статус: {project.status}"
    )


@router.message(Command("projects"))
async def projects(message: Message, project_service: ProjectService) -> None:
    await project_service.ensure_actor(identity_from_message(message))
    items = await project_service.list_projects(identity_from_message(message))
    if not items:
        await message.answer("Доступных проектов пока нет.")
        return
    cards = [
        f"{item.code} — {item.name}\nКурс: {item.course}\nСтатус: {item.status}"
        for item in items
    ]
    await message.answer("\n\n".join(cards))


@router.message(Command("add_participant"))
async def add_participant(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Приглашать участников может только администратор.")
        return
    await state.clear()
    await state.set_state(ParticipantWizard.project_code)
    await message.answer("Введите код проекта:")


@router.message(ParticipantWizard.project_code, F.text)
async def participant_project_code(message: Message, state: FSMContext) -> None:
    await state.update_data(project_code=message.text)
    await state.set_state(ParticipantWizard.display_name)
    await message.answer("Введите имя участника для списка проекта:")


@router.message(ParticipantWizard.display_name, F.text)
async def participant_display_name(
    message: Message, state: FSMContext
) -> None:
    await state.update_data(display_name=message.text)
    await state.set_state(ParticipantWizard.email)
    await message.answer("Введите email участника:")


@router.message(ParticipantWizard.email, F.text)
async def participant_email(
    message: Message, state: FSMContext, participant_service: ParticipantService
) -> None:
    data: dict[str, Any] = await state.get_data()
    try:
        invitation = await participant_service.create_invitation(
            identity_from_message(message),
            project_code=str(data["project_code"]),
            participant_name=str(data["display_name"]),
            participant_email=message.text or "",
        )
        if message.bot is None:
            raise RuntimeError("Telegram bot context is unavailable")
        link = await create_start_link(message.bot, invitation.token, encode=False)
    except (ValueError, AccessDeniedError) as exc:
        await message.answer(f"Приглашение не создано: {exc}\nИсправьте email или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"Участник добавлен в проект {invitation.project_code}.\n"
        f"Одноразовая ссылка действует до {invitation.expires_at:%d.%m.%Y %H:%M %Z}:\n"
        f"{link}\n\nПередайте ссылку только этому участнику."
    )


@router.message(Command("participants"))
async def participants(
    message: Message, command: CommandObject, participant_service: ParticipantService
) -> None:
    if not command.args:
        await message.answer("Укажите код: /participants TBA-2026-G01")
        return
    try:
        items = await participant_service.list_participants(
            identity_from_message(message), project_code=command.args
        )
    except (ValueError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if not items:
        await message.answer("В проекте пока нет участников.")
        return
    lines = [
        f"{item.display_name} — {item.status}"
        f" ({'Telegram подключён' if item.telegram_connected else 'ожидает входа'}; "
        f"{'email задан' if item.email_configured else 'email не задан'}; "
        f"{'4К подключён' if item.agent4k_connected else '4К ожидает'})"
        for item in items
    ]
    await message.answer("\n".join(lines))


@router.message(Command("link_4k"))
async def link_4k(
    message: Message,
    command: CommandObject,
    participant_service: ParticipantService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if not command.args:
        await message.answer("Укажите код проекта: /link_4k TBA-2026-G01")
        return
    try:
        await participant_service.link_my_agent4k_identity(
            identity_from_message(message),
            project_code=command.args,
            adapter=agent4k_adapter,
        )
    except (ValueError, AccessDeniedError, Agent4KUnavailableError, RuntimeError) as exc:
        await message.answer(f"Связь с 4К не создана: {exc}")
        return
    await message.answer("Связь участника с 4К активна.")


@router.message(Command("new_role"))
async def new_role(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Создавать роли может только администратор.")
        return
    await state.clear()
    await state.set_state(RoleWizard.project_code)
    await message.answer("Код проекта для новой роли:")


@router.message(RoleWizard.project_code, F.text)
async def role_project(message: Message, state: FSMContext) -> None:
    await state.update_data(project_code=message.text)
    await state.set_state(RoleWizard.code)
    await message.answer("Машинный код роли, например business_analyst:")


@router.message(RoleWizard.code, F.text)
async def role_code(message: Message, state: FSMContext) -> None:
    await state.update_data(code=message.text)
    await state.set_state(RoleWizard.name)
    await message.answer("Название роли:")


@router.message(RoleWizard.name, F.text)
async def role_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(RoleWizard.mission)
    await message.answer("Миссия роли в проекте:")


@router.message(RoleWizard.mission, F.text)
async def role_mission(message: Message, state: FSMContext) -> None:
    await state.update_data(mission=message.text)
    await state.set_state(RoleWizard.responsibilities)
    await message.answer("Зоны ответственности; разделяйте пункты ';':")


@router.message(RoleWizard.responsibilities, F.text)
async def role_responsibilities(message: Message, state: FSMContext) -> None:
    await state.update_data(responsibilities=message.text or "")
    await state.set_state(RoleWizard.typical_tasks)
    await message.answer("Типовые задачи; разделяйте пункты ';':")


@router.message(RoleWizard.typical_tasks, F.text)
async def role_tasks(message: Message, state: FSMContext) -> None:
    await state.update_data(typical_tasks=message.text or "")
    await state.set_state(RoleWizard.expected_outputs)
    await message.answer("Ожидаемые артефакты/результаты; разделяйте пункты ';':")


@router.message(RoleWizard.expected_outputs, F.text)
async def role_outputs(message: Message, state: FSMContext) -> None:
    await state.update_data(expected_outputs=message.text or "")
    await state.set_state(RoleWizard.interactions)
    await message.answer("Рабочие взаимодействия; разделяйте пункты ';':")


@router.message(RoleWizard.interactions, F.text)
async def role_interactions(message: Message, state: FSMContext) -> None:
    await state.update_data(interactions=message.text or "")
    await state.set_state(RoleWizard.agent4k_role_profile_version_id)
    await message.answer("ID опубликованной RoleProfileVersion в 4К:")


@router.message(RoleWizard.agent4k_role_profile_version_id, F.text)
async def role_agent4k_version_id(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value.isdigit() or int(value) <= 0:
        await message.answer("Введите положительный числовой ID версии роли 4К или /cancel.")
        return
    await state.update_data(agent4k_role_profile_version_id=int(value))
    await state.set_state(RoleWizard.agent4k_role_profile_checksum)
    await message.answer("SHA-256 checksum опубликованной версии роли 4К:")


@router.message(RoleWizard.agent4k_role_profile_checksum, F.text)
async def role_agent4k_checksum(message: Message, state: FSMContext) -> None:
    await state.update_data(agent4k_role_profile_checksum=message.text)
    await state.set_state(RoleWizard.crisp_dm_stages)
    await message.answer(
        "Стадии CRISP-DM через ';': business_understanding; data_understanding; "
        "data_preparation; modeling; evaluation; deployment"
    )


@router.message(RoleWizard.crisp_dm_stages, F.text)
async def role_stages(
    message: Message, state: FSMContext, role_service: RoleService
) -> None:
    data: dict[str, Any] = await state.get_data()
    try:
        project_code = str(data.pop("project_code"))
        draft = RoleDraft(
            code=str(data["code"]),
            name=str(data["name"]),
            mission=str(data["mission"]),
            responsibilities=parse_items(str(data["responsibilities"])),
            typical_tasks=parse_items(str(data["typical_tasks"])),
            expected_outputs=parse_items(str(data["expected_outputs"])),
            interactions=parse_items(str(data["interactions"])),
            crisp_dm_stages=parse_items(message.text or ""),
            agent4k_role_profile_version_id=int(data["agent4k_role_profile_version_id"]),
            agent4k_role_profile_checksum=str(data["agent4k_role_profile_checksum"]),
        )
        result = await role_service.create_draft(
            identity_from_message(message), project_code=project_code, draft=draft
        )
    except (ValueError, RoleError, AccessDeniedError) as exc:
        await message.answer(f"Роль не создана: {exc}\nИсправьте стадии или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"Draft роли создан: {result.code} v{result.version}.\n"
        f"Checksum: {result.checksum}\n"
        f"Опубликовать: /publish_role {project_code} {result.code}"
    )


@router.message(Command("publish_role"))
async def publish_role(
    message: Message,
    command: CommandObject,
    role_service: RoleService,
    agent4k_adapter: Agent4KPort,
) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /publish_role PROJECT_CODE ROLE_CODE")
        return
    try:
        result = await role_service.publish(
            identity_from_message(message),
            project_code=parts[0],
            role_code=parts[1],
            adapter=agent4k_adapter,
        )
    except (RoleError, AccessDeniedError, Agent4KUnavailableError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(f"Роль {result.code} v{result.version} опубликована.")


@router.message(Command("roles"))
async def roles(
    message: Message, command: CommandObject, role_service: RoleService
) -> None:
    if not command.args:
        await message.answer("Формат: /roles PROJECT_CODE")
        return
    try:
        items = await role_service.list_roles(
            identity_from_message(message), project_code=command.args
        )
    except (RoleError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if not items:
        await message.answer("У проекта пока нет ролей.")
        return
    await message.answer(
        "\n".join(f"{item.code} v{item.version} — {item.status}" for item in items)
    )


@router.message(Command("assign_role"))
async def assign_role(
    message: Message, command: CommandObject, role_service: RoleService
) -> None:
    parts = (command.args or "").split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Формат: /assign_role PROJECT_CODE PARTICIPANT_ID ROLE_CODE")
        return
    try:
        result = await role_service.assign(
            identity_from_message(message),
            project_code=parts[0],
            participant_id=int(parts[1]),
            role_code=parts[2],
        )
    except (RoleError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    suffix = "основная" if result.is_primary else "дополнительная"
    action = "назначена" if result.created else "уже была назначена"
    await message.answer(
        f"Роль {result.role_code} v{result.role_version} {action}; {suffix}."
    )


@router.message(Command("my_roles"))
async def my_roles(message: Message, role_service: RoleService) -> None:
    items = await role_service.list_my_roles(identity_from_message(message))
    if not items:
        await message.answer("Вам пока не назначены проектные роли.")
        return
    await message.answer(
        "\n".join(
            f"{item.project_code}: {item.role_name} v{item.role_version}"
            f" ({'основная' if item.is_primary else 'дополнительная'})"
            for item in items
        )
    )


@router.message(Command("new_spec"))
async def new_spec(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Создавать спецификации может только администратор.")
        return
    await state.clear()
    await state.set_state(AssessmentSpecWizard.project_code)
    await message.answer("Код проекта:")


@router.message(AssessmentSpecWizard.project_code, F.text)
async def spec_project(message: Message, state: FSMContext) -> None:
    await state.update_data(project_code=message.text)
    await state.set_state(AssessmentSpecWizard.configuration_ref)
    await message.answer("Точная ссылка/ID опубликованной AssessmentConfiguration 4К:")


@router.message(AssessmentSpecWizard.configuration_ref, F.text)
async def spec_configuration(message: Message, state: FSMContext) -> None:
    await state.update_data(assessment_configuration_ref=message.text)
    await state.set_state(AssessmentSpecWizard.configuration_checksum)
    await message.answer("SHA-256 этой конфигурации (64 hex-символа):")


@router.message(AssessmentSpecWizard.configuration_checksum, F.text)
async def spec_configuration_checksum(message: Message, state: FSMContext) -> None:
    await state.update_data(assessment_configuration_checksum=message.text)
    await state.set_state(AssessmentSpecWizard.methodology_ref)
    await message.answer("Ссылка/версия методологии:")


@router.message(AssessmentSpecWizard.methodology_ref, F.text)
async def spec_methodology(message: Message, state: FSMContext) -> None:
    await state.update_data(methodology_ref=message.text)
    await state.set_state(AssessmentSpecWizard.required_case_count)
    await message.answer("Сколько кейсов должен пройти участник?")


@router.message(AssessmentSpecWizard.required_case_count, F.text)
async def spec_case_count(message: Message, state: FSMContext) -> None:
    await state.update_data(required_case_count=message.text)
    await state.set_state(AssessmentSpecWizard.period)
    await message.answer("Период: ДД.ММ.ГГГГ ДД.ММ.ГГГГ или '-':")


@router.message(AssessmentSpecWizard.period, F.text)
async def spec_period(message: Message, state: FSMContext) -> None:
    try:
        available_from, available_until = parse_optional_dates(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(
        available_from=available_from,
        available_until=available_until,
    )
    await state.set_state(AssessmentSpecWizard.recipient_policy)
    await message.answer(
        "Получатели результата: participant, instructor или participant_and_instructor:"
    )


@router.message(AssessmentSpecWizard.recipient_policy, F.text)
async def spec_recipient_policy(
    message: Message, state: FSMContext, assessment_service: AssessmentService
) -> None:
    data: dict[str, Any] = await state.get_data()
    try:
        project_code = str(data.pop("project_code"))
        draft = AssessmentSpecDraft(
            assessment_configuration_ref=str(data["assessment_configuration_ref"]),
            assessment_configuration_checksum=str(data["assessment_configuration_checksum"]),
            methodology_ref=str(data["methodology_ref"]),
            required_case_count=int(str(data["required_case_count"])),
            available_from=data["available_from"],
            available_until=data["available_until"],
            result_recipient_policy=(message.text or "").strip(),
        )
        result = await assessment_service.create_spec_draft(
            identity_from_message(message), project_code=project_code, draft=draft
        )
    except (ValueError, AssessmentError, AccessDeniedError) as exc:
        await message.answer(f"Спецификация не создана: {exc}\nИсправьте значение или /cancel.")
        return
    await state.clear()
    await message.answer(
        f"Draft спецификации v{result.version} создан.\n"
        f"Кейсов: {result.required_case_count}\n"
        f"Checksum: {result.checksum}\n"
        f"Runtime: {result.runtime_admission}\n"
        f"Опубликовать локальный snapshot: /publish_spec {project_code}"
    )


@router.message(Command("publish_spec"))
async def publish_spec(
    message: Message, command: CommandObject, assessment_service: AssessmentService
) -> None:
    if not command.args:
        await message.answer("Формат: /publish_spec PROJECT_CODE")
        return
    try:
        result = await assessment_service.publish_spec(
            identity_from_message(message), project_code=command.args
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        f"Локальная спецификация v{result.version} опубликована неизменяемо.\n"
        f"Runtime 4К: {result.runtime_admission}."
    )


@router.message(Command("specs"))
async def specs(
    message: Message, command: CommandObject, assessment_service: AssessmentService
) -> None:
    if not command.args:
        await message.answer("Формат: /specs PROJECT_CODE")
        return
    try:
        items = await assessment_service.list_specs(
            identity_from_message(message), project_code=command.args
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if not items:
        await message.answer("У проекта нет спецификаций оценки.")
        return
    await message.answer(
        "\n".join(
            f"v{item.version} — {item.status}; кейсов {item.required_case_count}; "
            f"runtime {item.runtime_admission}"
            for item in items
        )
    )


@router.message(Command("assign_assessment"))
async def assign_assessment(
    message: Message, command: CommandObject, assessment_service: AssessmentService
) -> None:
    parts = (command.args or "").split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer(
            "Формат: /assign_assessment PROJECT_CODE PARTICIPANT_ID ROLE_CODE"
        )
        return
    try:
        result = await assessment_service.assign(
            identity_from_message(message),
            project_code=parts[0],
            participant_id=int(parts[1]),
            role_code=parts[2],
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        f"Оценка назначена: {result.project_code}, роль {result.role_code} "
        f"v{result.role_version}, спецификация v{result.spec_version}.\n"
        "Cycle 4К ещё не создан.\n"
        f"Зафиксировать контекст: /publish_context {result.id}"
    )


@router.message(Command("publish_context"))
async def publish_context(
    message: Message, command: CommandObject, assessment_service: AssessmentService
) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /publish_context ASSIGNMENT_ID")
        return
    try:
        result = await assessment_service.publish_context_snapshot(
            identity_from_message(message), assignment_id=int(command.args.strip())
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "Контекст назначения опубликован неизменяемо.\n"
        f"Assignment ref: {result.assignment_ref}\n"
        f"Checksum: {result.checksum}"
    )


@router.message(Command("progress"))
async def progress(message: Message, assessment_service: AssessmentService) -> None:
    items = await assessment_service.my_progress(identity_from_message(message))
    if not items:
        await message.answer("Вам пока не назначена оценка.")
        return
    await message.answer(
        "\n\n".join(
            f"{item.project_code}, роль {item.role_code} v{item.role_version}\n"
            f"Пройдено: {item.completed_cases} из {item.required_cases}\n"
            f"Осталось: {item.remaining_cases}\n"
            f"Статус: {item.status}; Cycle 4К: "
            f"{'создан' if item.runtime_connected else 'ожидает интеграции'}"
            for item in items
        )
    )


@router.message(Command("prepare_cycle"))
async def prepare_cycle(
    message: Message,
    command: CommandObject,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /prepare_cycle ASSIGNMENT_ID")
        return
    try:
        result = await assessment_service.prepare_external_context(
            identity_from_message(message),
            assignment_id=int(command.args.strip()),
            adapter=agent4k_adapter,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if result.status == "prepared":
        await message.answer(f"Cycle 4К подготовлен: {result.cycle_id}")
        return
    if result.status == "preparing":
        await message.answer(
            "Admission выполнен. Подготовка Cycle поставлена в очередь 4К.\n"
            f"Operation: {result.operation_id}\n"
            "Повторите команду позже для проверки результата."
        )
        return
    instructions = {
        "PROGRAM_NOT_CONNECTED": (
            f"выберите программу: /admission_programs {result.assignment_id}"
        ),
        "QUESTIONNAIRE_NOT_CONFIRMED": "подтвердите анкету проекта в 4К",
        "PERSONALIZED_PROFILE_NOT_CONFIRMED": (
            "участнику нужно подтвердить профиль после назначения программы"
        ),
        "ASSIGNMENT_NOT_ACTIVE": "создайте active assignment в админке 4К",
        "CYCLE_PREPARATION_FAILED": "проверьте admission и повторите подготовку",
    }
    reasons = "\n".join(
        f"• {reason}: {instructions.get(reason, 'проверьте настройку в 4К')}"
        for reason in result.reasons
    )
    await message.answer(
        "Контекст зарегистрирован в 4К и ожидает admission.\n"
        f"Operation: {result.operation_id}\nПричины:\n{reasons or 'не указаны'}"
    )


@router.message(Command("admission_programs"))
async def admission_programs(
    message: Message,
    command: CommandObject,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /admission_programs ASSIGNMENT_ID")
        return
    try:
        programs = await assessment_service.list_compatible_programs(
            identity_from_message(message),
            assignment_id=int(command.args.strip()),
            adapter=agent4k_adapter,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if not programs:
        await message.answer(
            "Совместимых опубликованных программ нет. "
            "Нужна публикация AssessmentProgram с тем же assignment_ref и ролью."
        )
        return
    await message.answer(
        "Совместимые программы:\n"
        + "\n".join(
            f"{item.id}: {item.name} ({item.code} v{item.version})"
            for item in programs
        )
        + "\n\nПодключение: /connect_program ASSIGNMENT_ID PROGRAM_ID"
    )


@router.message(Command("connect_program"))
async def connect_program(
    message: Message,
    command: CommandObject,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        await message.answer("Формат: /connect_program ASSIGNMENT_ID PROGRAM_ID")
        return
    try:
        connected = await assessment_service.connect_compatible_program(
            identity_from_message(message),
            assignment_id=int(parts[0]),
            program_definition_id=int(parts[1]),
            adapter=agent4k_adapter,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        f"Программа {connected.program_code} v{connected.program_version} подключена.\n"
        f"Повторите: /prepare_cycle {parts[0]}"
    )


@router.message(Command("case"))
async def not_connected_yet(message: Message) -> None:
    await message.answer("Функция станет доступна после подключения проекта администратором.")


def build_dispatcher(
    project_service: ProjectService,
    participant_service: ParticipantService,
    role_service: RoleService,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
    default_project_timezone: str,
) -> Dispatcher:
    dispatcher = Dispatcher(
        project_service=project_service,
        participant_service=participant_service,
        role_service=role_service,
        assessment_service=assessment_service,
        agent4k_adapter=agent4k_adapter,
        default_project_timezone=default_project_timezone,
    )
    dispatcher.include_router(router)
    return dispatcher

