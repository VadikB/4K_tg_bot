import hashlib
import json
import unicodedata
from datetime import date
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.deep_linking import create_start_link

from app.application.assessments import AssessmentError, AssessmentService, AssessmentSpecDraft
from app.application.participants import (
    InvitationError,
    ParticipantIdentityNotReadyError,
    ParticipantService,
    normalize_email,
)
from app.application.projects import (
    AccessDeniedError,
    DuplicateProjectCodeError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)
from app.application.roles import RoleError, RoleService, RoleView
from app.integrations.agent4k import (
    Agent4KPort,
    Agent4KUnavailableError,
    EducationalChannelState,
)
from app.role_catalog import load_role_catalog

router = Router()
TELEGRAM_TEXT_CHUNK_SIZE = 3500


def bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Войти и показать основные команды"),
        BotCommand(command="help", description="Показать полный список команд"),
        BotCommand(command="new_project", description="Создать учебный проект"),
        BotCommand(command="projects", description="Показать доступные проекты"),
        BotCommand(command="my_projects", description="Мои учебные проекты"),
        BotCommand(command="add_participant", description="Пригласить участника"),
        BotCommand(command="participants", description="Список участников проекта"),
        BotCommand(command="feedback", description="Отправить отзыв преподавателю"),
        BotCommand(command="roles", description="Пять ролей CRISP-DM"),
        BotCommand(command="map_role", description="Связать роль с профилем оценки 4К"),
        BotCommand(command="assign_role", description="Назначить роль участнику"),
        BotCommand(command="my_roles", description="Мои роли в проектах"),
        BotCommand(command="new_spec", description="Настроить оценку проекта"),
        BotCommand(command="specs", description="Список спецификаций проекта"),
        BotCommand(command="publish_spec", description="Опубликовать спецификацию"),
        BotCommand(command="assign_assessment", description="Назначить оценку"),
        BotCommand(command="publish_context", description="Зафиксировать контекст оценки"),
        BotCommand(command="prepare_cycle", description="Подготовить цикл оценки 4К"),
        BotCommand(command="admission_programs", description="Совместимые программы 4К"),
        BotCommand(command="connect_program", description="Подключить программу 4К"),
        BotCommand(command="progress", description="Показать прогресс оценки"),
        BotCommand(command="get_case", description="Получить или продолжить кейс"),
        BotCommand(command="case", description="Получить или продолжить кейс"),
        BotCommand(command="cancel", description="Отменить текущий диалог"),
    ]


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
    telegram_user_id = State()


class FeedbackWizard(StatesGroup):
    text = State()


class AssignRoleWizard(StatesGroup):
    project = State()
    participant = State()
    role = State()


CHOICE_PAGE_SIZE = 8


def choice_keyboard(
    items: list[tuple[str, str]], token: str, stage: str, page: int = 0, *, prefix: str = "ar"
) -> InlineKeyboardMarkup:
    start = page * CHOICE_PAGE_SIZE
    rows = [
        [InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{token}:{stage}:{index}")]
        for index, (label, _) in enumerate(items[start : start + CHOICE_PAGE_SIZE], start)
    ]
    navigation = []
    if page:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад", callback_data=f"{prefix}:{token}:{stage}:p{page - 1}"
            )
        )
    if start + CHOICE_PAGE_SIZE < len(items):
        navigation.append(
            InlineKeyboardButton(
                text="Далее →", callback_data=f"{prefix}:{token}:{stage}:p{page + 1}"
            )
        )
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)


class AssessmentSpecWizard(StatesGroup):
    project_code = State()
    configuration = State()
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
    canonical_name = " ".join(unicodedata.normalize("NFKC", course_name).casefold().split())
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
            "Используйте /projects для просмотра карточки, "
            f"/feedback {project.code} — для отзыва преподавателю.\n"
            "После назначения оценки: /get_case — получить или продолжить кейс."
        )
        try:
            await participant_service.link_my_agent4k_identity(
                identity_from_message(message),
                project_code=project.code,
                adapter=agent4k_adapter,
            )
        except ParticipantIdentityNotReadyError:
            await message.answer(
                "Участие в проекте активно. Оценка 4К пока недоступна; "
                "преподаватель сообщит, когда можно начать."
            )
        except (Agent4KUnavailableError, ValueError, AccessDeniedError, RuntimeError):
            await message.answer("Связь с 4К пока не создана. Участие в проекте сохранено.")
        return
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if is_admin:
        superadmin = await project_service.is_superadmin(identity_from_message(message))
        title = (
            "Вы вошли как суперадминистратор."
            if superadmin
            else "Вы вошли как администратор проекта."
        )
        await message.answer(
            f"{title}\n"
            "/new_project — создать проект\n"
            f"/projects — {'все проекты' if superadmin else 'мои проекты'}\n"
            "/add_participant — пригласить участника\n"
            "/participants PROJECT_CODE — список участников\n"
            "/roles — фиксированные роли CRISP-DM\n"
            "/feedback PROJECT_CODE — отправить отзыв преподавателю\n"
            "/help — полный список команд"
        )
    else:
        projects = await project_service.list_projects(identity_from_message(message))
        if projects:
            await message.answer(
                "Вы вошли как участник проекта.\n"
                "/projects — мои проекты\n"
                "/my_roles — мои роли\n"
                "/get_case — получить или продолжить кейс после назначения оценки\n"
                "/progress — прогресс оценки\n"
                "/feedback PROJECT_CODE — отправить отзыв преподавателю\n"
                "/help — полный список команд"
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
        "/projects — доступные проекты\n"
        "/my_projects — мои учебные проекты\n"
        "/new_project — создать проект (администратор)\n"
        "/add_participant — пригласить участника (администратор)\n"
        "/participants CODE — участники проекта (администратор)\n"
        "/feedback PROJECT_CODE — отправить отзыв преподавателю проекта\n"
        "/roles — фиксированные роли (без кода проекта)\n"
        "/roles PROJECT — версии проекта (необязательно)\n"
        "/map_role PROJECT ROLE PROFILE_ID CHECKSUM — сопоставить с 4К\n"
        "/assign_role — выбрать проект, участника и роль\n"
        "/my_roles [PROJECT] — мои роли в проектах\n"
        "/new_spec — выбрать конфигурацию 4К и настроить оценку проекта\n"
        "/publish_spec PROJECT — опубликовать спецификацию\n"
        "/specs PROJECT — версии спецификации\n"
        "/assign_assessment PROJECT PARTICIPANT_ID ROLE — назначить оценку\n"
        "/publish_context ASSIGNMENT_ID — зафиксировать контекст назначения\n"
        "/prepare_cycle ASSIGNMENT_ID — проверить admission и подготовку Cycle\n"
        "/admission_programs ASSIGNMENT_ID — совместимые программы 4К\n"
        "/connect_program ASSIGNMENT_ID PROGRAM_ID — подключить программу\n"
        "/progress [ASSIGNMENT_ID] — канонический прогресс 4К\n"
        "/get_case [ASSIGNMENT_ID] — получить или продолжить кейс\n"
        "/case [ASSIGNMENT_ID] — прежнее имя команды\n"
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
async def cancel(
    message: Message, state: FSMContext, assessment_service: AssessmentService
) -> None:
    if message.chat.type != "private":
        await message.answer("Этот сценарий доступен только в личном чате с ботом.")
        return
    await state.clear()
    try:
        await assessment_service.cancel_my_pending_channel_input(identity_from_message(message))
    except AssessmentError as exc:
        await message.answer(str(exc))
        return
    await message.answer("Диалог отменён.", reply_markup=ReplyKeyboardRemove())


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
        await message.answer(f"Ответ не принят: {exc}\nКакой результат должен получить проект?")
        return
    await state.update_data(expected_result=value)
    await state.set_state(ProjectWizard.description)
    await message.answer("Краткое описание проекта:")


@router.message(ProjectWizard.description, F.text)
async def project_description(message: Message, state: FSMContext) -> None:
    try:
        value = parse_required_answer(message.text or "", "Описание проекта")
    except ValueError as exc:
        await message.answer(f"Ответ не принят: {exc}\nВведите краткое описание проекта:")
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
        f"Проект создан.\n{project.code} — {project.name}\nСтатус: {project.status}"
    )


@router.message(Command("projects", "my_projects"))
async def projects(message: Message, project_service: ProjectService) -> None:
    await project_service.ensure_actor(identity_from_message(message))
    items = await project_service.list_projects(identity_from_message(message))
    if not items:
        await message.answer("Доступных проектов пока нет.")
        return
    cards = [
        f"{item.code} — {item.name}\nКурс: {item.course}\nСтатус: {item.status}" for item in items
    ]
    await message.answer("\n\n".join(cards))


@router.message(Command("add_participant"))
async def add_participant(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    if message.chat.type != "private":
        await message.answer("Приглашение участника доступно в личном чате с ботом.")
        return
    identity = identity_from_message(message)
    actor, is_admin = await project_service.ensure_actor(identity)
    if not is_admin:
        await message.answer("Приглашать участников может только администратор.")
        return
    projects = [
        item
        for item in await project_service.list_projects(identity)
        if item.created_by_user_id == actor.id
    ]
    if not projects:
        await message.answer("Нет проектов, в которые вы можете пригласить участника.")
        return
    await state.clear()
    token = uuid4().hex[:12]
    items = [(f"{item.code} — {item.name}", item.code) for item in projects]
    await state.update_data(token=token, projects=items)
    await state.set_state(ParticipantWizard.project_code)
    await message.answer(
        "Выберите проект для приглашения:",
        reply_markup=choice_keyboard(items, token, "project", prefix="ap"),
    )


@router.callback_query(F.data.startswith("ap:"))
async def participant_project_choice(
    callback: CallbackQuery, state: FSMContext, project_service: ProjectService
) -> None:
    if not isinstance(callback.message, Message) or callback.from_user is None:
        await callback.answer("Откройте личный чат с ботом.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    if (
        len(parts) != 4
        or parts[0] != "ap"
        or parts[1] != data.get("token")
        or parts[2] != "project"
        or await state.get_state() != ParticipantWizard.project_code.state
    ):
        await callback.answer("Список устарел. Начните заново: /add_participant", show_alert=True)
        return
    items = data.get("projects")
    if not isinstance(items, list):
        await callback.answer("Список устарел. Начните заново: /add_participant", show_alert=True)
        return
    selected = parts[3]
    if selected.startswith("p") and selected[1:].isascii() and selected[1:].isdecimal():
        page = int(selected[1:])
        if page * CHOICE_PAGE_SIZE >= len(items):
            await callback.answer("Страница недоступна.", show_alert=True)
            return
        await callback.message.edit_reply_markup(
            reply_markup=choice_keyboard(items, data["token"], "project", page, prefix="ap")
        )
        await callback.answer()
        return
    if not selected.isascii() or not selected.isdecimal() or int(selected) >= len(items):
        await callback.answer("Пункт недоступен.", show_alert=True)
        return
    project_code = items[int(selected)][1]
    identity = TelegramIdentity(
        telegram_user_id=callback.from_user.id,
        telegram_username=callback.from_user.username,
        display_name=callback.from_user.full_name,
    )
    try:
        actor, is_admin = await project_service.ensure_actor(identity)
        projects = await project_service.list_projects(identity)
        if not is_admin or project_code not in {
            item.code for item in projects if item.created_by_user_id == actor.id
        }:
            raise AccessDeniedError("Проект больше недоступен для приглашения.")
    except AccessDeniedError as exc:
        await state.clear()
        await callback.message.answer(str(exc))
        await callback.answer()
        return
    await state.update_data(project_code=project_code)
    await state.set_state(ParticipantWizard.display_name)
    await callback.message.answer("Введите ФИО участника:")
    await callback.answer()


@router.message(ParticipantWizard.project_code, F.text & ~F.text.startswith("/"))
async def participant_project_text(message: Message, state: FSMContext) -> None:
    await message.answer("Выберите проект кнопкой в сообщении выше или /cancel.")


@router.message(ParticipantWizard.display_name, F.text & ~F.text.startswith("/"))
async def participant_display_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 255:
        await message.answer("ФИО должно содержать от 1 до 255 символов. Повторите ввод:")
        return
    await state.update_data(display_name=name)
    await state.set_state(ParticipantWizard.email)
    await message.answer("Введите email участника:")


@router.message(ParticipantWizard.email, F.text & ~F.text.startswith("/"))
async def participant_email(message: Message, state: FSMContext) -> None:
    try:
        email = normalize_email(message.text or "")
    except ValueError as exc:
        await message.answer(f"{exc} Повторите ввод:")
        return
    await state.update_data(email=email)
    await state.set_state(ParticipantWizard.telegram_user_id)
    await message.answer("Введите числовой Telegram ID участника:")


@router.message(ParticipantWizard.telegram_user_id, F.text & ~F.text.startswith("/"))
async def participant_telegram_user_id(
    message: Message, state: FSMContext, participant_service: ParticipantService
) -> None:
    raw_id = (message.text or "").strip()
    if not raw_id.isascii() or not raw_id.isdecimal():
        await message.answer("Введите положительный числовой Telegram ID или /cancel.")
        return
    data: dict[str, Any] = await state.get_data()
    try:
        invitation = await participant_service.create_telegram_invitation(
            identity_from_message(message),
            project_code=str(data["project_code"]),
            participant_name=str(data["display_name"]),
            participant_email=str(data["email"]),
            telegram_user_id=int(raw_id),
        )
        if message.bot is None:
            raise RuntimeError("Telegram bot context is unavailable")
        link = await create_start_link(message.bot, invitation.token, encode=False)
    except (ValueError, AccessDeniedError) as exc:
        await message.answer(
            f"Приглашение не создано: {exc}\n"
            "Для исправления данных начните заново: /cancel, затем /add_participant."
        )
        return
    await state.clear()
    await message.answer(
        f"Приглашение для Telegram ID {raw_id} создано в проекте "
        f"{invitation.project_code}.\n"
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
        f"{'Telegram ID задан' if item.telegram_id_configured else 'старое приглашение'}; "
        f"{'4К подключён' if item.agent4k_connected else '4К ожидает'})"
        for item in items
    ]
    await message.answer("\n".join(lines))


@router.message(Command("feedback"))
async def feedback(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    participant_service: ParticipantService,
) -> None:
    if message.chat.type != "private":
        await message.answer("Отзыв можно отправить только в личном чате с ботом.")
        return
    if not command.args or len(command.args.split()) != 1:
        await message.answer("Укажите проект: /feedback PROJECT_CODE")
        return
    try:
        recipient = await participant_service.feedback_recipient(
            identity_from_message(message), project_code=command.args
        )
    except (ValueError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await state.update_data(project_code=recipient.project_code)
    await state.set_state(FeedbackWizard.text)
    await message.answer(
        f"Напишите отзыв преподавателю проекта {recipient.project_code} "
        "следующим сообщением (до 3000 символов). Для отмены — /cancel."
    )


@router.message(FeedbackWizard.text, F.text)
async def feedback_text(
    message: Message, state: FSMContext, participant_service: ParticipantService
) -> None:
    if message.chat.type != "private":
        return
    text = (message.text or "").strip()
    if not text or len(text) > 3000:
        await message.answer("Отзыв должен содержать от 1 до 3000 символов.")
        return
    data = await state.get_data()
    try:
        recipient = await participant_service.feedback_recipient(
            identity_from_message(message), project_code=str(data["project_code"])
        )
    except (ValueError, AccessDeniedError, KeyError) as exc:
        await state.clear()
        await message.answer(f"Отзыв не отправлен: {exc}")
        return
    if message.bot is None:
        await state.clear()
        await message.answer("Отзыв не отправлен: бот временно недоступен.")
        return
    try:
        await message.bot.send_message(
            recipient.teacher_telegram_user_id,
            f"Отзыв участника проекта {recipient.project_code} "
            f"({recipient.participant_name}):\n\n{text}",
        )
    except TelegramAPIError:
        await state.clear()
        await message.answer(
            "Доставку отзыва не удалось подтвердить. Уточните у преподавателя "
            "перед повторной отправкой."
        )
        return
    await state.clear()
    await message.answer("Отзыв отправлен преподавателю проекта.")


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


@router.message(Command("roles"))
async def roles(message: Message, command: CommandObject, role_service: RoleService) -> None:
    if not command.args:
        try:
            catalog = load_role_catalog()
        except (OSError, ValueError):
            await message.answer(
                "Справочник ролей временно недоступен. Обратитесь к администратору."
            )
            return
        await message.answer(
            "Роли CRISP-DM текущего семестра:\n"
            + "\n".join(f"{item.code} — {item.name}" for item in catalog.roles)
        )
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


@router.message(Command("map_role"))
async def map_role(
    message: Message,
    command: CommandObject,
    role_service: RoleService,
    agent4k_adapter: Agent4KPort,
) -> None:
    parts = (command.args or "").split()
    if len(parts) != 4 or not parts[2].isdigit():
        await message.answer("Формат: /map_role PROJECT_CODE ROLE_CODE PROFILE_ID CHECKSUM")
        return
    try:
        result = await role_service.publish_role_profile_binding(
            identity_from_message(message),
            project_code=parts[0],
            role_code=parts[1],
            agent4k_role_profile_version_id=int(parts[2]),
            agent4k_role_profile_checksum=parts[3],
            adapter=agent4k_adapter,
        )
    except (RoleError, AccessDeniedError, Agent4KUnavailableError) as exc:
        await message.answer(f"Сопоставление не опубликовано: {exc}")
        return
    await message.answer(
        f"Роль {result.role_code} v{result.project_role_version} связана с "
        f"RoleProfileVersion {result.agent4k_role_profile_version_id} 4К "
        f"(версия сопоставления {result.binding_version})."
    )


@router.message(Command("assign_role"))
async def assign_role(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    project_service: ProjectService,
    role_service: RoleService,
) -> None:
    parts = (command.args or "").split()
    if not parts:
        if message.chat.type != "private":
            await message.answer("Назначение роли доступно в личном чате с ботом.")
            return
        identity = identity_from_message(message)
        _, is_admin = await project_service.ensure_actor(identity)
        if not is_admin:
            await message.answer("Назначать роли может только администратор.")
            return
        projects = await project_service.list_projects(identity)
        if not projects:
            await message.answer("Доступных проектов пока нет.")
            return
        await state.clear()
        token = uuid4().hex[:12]
        items = [(f"{item.code} — {item.name}", item.code) for item in projects]
        await state.update_data(token=token, projects=items)
        await state.set_state(AssignRoleWizard.project)
        await message.answer(
            "Выберите код проекта:", reply_markup=choice_keyboard(items, token, "project")
        )
        return
    if len(parts) != 3 or not parts[1].isascii() or not parts[1].isdecimal():
        await message.answer("Используйте /assign_role для выбора из списков.")
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
    await state.clear()
    suffix = "основная" if result.is_primary else "дополнительная"
    action = "назначена" if result.created else "уже была назначена"
    await message.answer(f"Роль {result.role_code} v{result.role_version} {action}; {suffix}.")


@router.callback_query(F.data.startswith("ar:"))
async def assign_role_choice(
    callback: CallbackQuery,
    state: FSMContext,
    project_service: ProjectService,
    participant_service: ParticipantService,
    role_service: RoleService,
) -> None:
    if not isinstance(callback.message, Message) or callback.from_user is None:
        await callback.answer("Откройте личный чат с ботом.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    current = await state.get_state()
    stages = {
        "project": AssignRoleWizard.project.state,
        "participant": AssignRoleWizard.participant.state,
        "role": AssignRoleWizard.role.state,
    }
    if (
        len(parts) != 4
        or parts[0] != "ar"
        or parts[1] != data.get("token")
        or current != stages.get(parts[2])
    ):
        await callback.answer("Список устарел. Начните заново: /assign_role", show_alert=True)
        return
    stage, selected = parts[2], parts[3]
    items = data.get(f"{stage}s")
    if not isinstance(items, list):
        await callback.answer("Список устарел. Начните заново: /assign_role", show_alert=True)
        return
    if selected.startswith("p") and selected[1:].isascii() and selected[1:].isdecimal():
        page = int(selected[1:])
        if page * CHOICE_PAGE_SIZE >= len(items):
            await callback.answer("Страница недоступна.", show_alert=True)
            return
        await callback.message.edit_reply_markup(
            reply_markup=choice_keyboard(items, data["token"], stage, page)
        )
        await callback.answer()
        return
    if not selected.isascii() or not selected.isdecimal() or int(selected) >= len(items):
        await callback.answer("Пункт недоступен.", show_alert=True)
        return
    value = items[int(selected)][1]
    identity = TelegramIdentity(
        telegram_user_id=callback.from_user.id,
        telegram_username=callback.from_user.username,
        display_name=callback.from_user.full_name,
    )
    try:
        if stage == "project":
            projects = await project_service.list_projects(identity)
            if value not in {project.code for project in projects}:
                raise AccessDeniedError("Проект больше недоступен.")
            participants = await participant_service.list_participants(identity, project_code=value)
            if not participants:
                await state.clear()
                await callback.message.answer("В проекте пока нет участников.")
            else:
                choices = [
                    (f"ID {item.id} — {item.display_name}", str(item.id)) for item in participants
                ]
                await state.update_data(project_code=value, participants=choices)
                await state.set_state(AssignRoleWizard.participant)
                await callback.message.answer(
                    "Выберите ID участника:",
                    reply_markup=choice_keyboard(choices, data["token"], "participant"),
                )
        elif stage == "participant":
            participants = await participant_service.list_participants(
                identity, project_code=data["project_code"]
            )
            if value not in {str(item.id) for item in participants}:
                raise RoleError("Участник больше не доступен в проекте.")
            roles = await role_service.list_roles(identity, project_code=data["project_code"])
            catalog = load_role_catalog()
            published: dict[str, RoleView] = {}
            for item in roles:
                if item.status == "published" and catalog.find(item.code):
                    published.setdefault(item.code, item)
            if not published:
                await state.clear()
                await callback.message.answer(
                    "В проекте пока нет опубликованных ролей текущего семестра."
                )
            else:
                choices = [
                    (f"{code} — {item.name} (v{item.version})", code)
                    for code, item in published.items()
                ]
                await state.update_data(participant_id=int(value), roles=choices)
                await state.set_state(AssignRoleWizard.role)
                await callback.message.answer(
                    "Выберите код роли:",
                    reply_markup=choice_keyboard(choices, data["token"], "role"),
                )
        else:
            result = await role_service.assign(
                identity,
                project_code=data["project_code"],
                participant_id=data["participant_id"],
                role_code=value,
            )
            await state.clear()
            action = "назначена" if result.created else "уже была назначена"
            suffix = "основная" if result.is_primary else "дополнительная"
            await callback.message.answer(
                f"Роль {result.role_code} v{result.role_version} {action}; {suffix}."
            )
    except (RoleError, AccessDeniedError, ValueError, OSError) as exc:
        await state.clear()
        await callback.message.answer(f"Назначение не выполнено: {exc}")
    await callback.answer()


@router.message(Command("my_roles"))
async def my_roles(message: Message, command: CommandObject, role_service: RoleService) -> None:
    items = await role_service.list_my_roles(identity_from_message(message))
    project_code = (command.args or "").strip().upper()
    if project_code:
        items = [item for item in items if item.project_code == project_code]
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
async def new_spec(message: Message, state: FSMContext, project_service: ProjectService) -> None:
    if message.chat.type != "private":
        await message.answer("Настройка оценки доступна в личном чате с ботом.")
        return
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Настраивать оценку может только администратор.")
        return
    projects = await project_service.list_projects(identity_from_message(message))
    if not projects:
        await message.answer("Доступных проектов пока нет.")
        return
    await state.clear()
    token = uuid4().hex[:12]
    items = [(f"{item.code} — {item.name}", item.code) for item in projects]
    await state.update_data(token=token, projects=items)
    await state.set_state(AssessmentSpecWizard.project_code)
    await message.answer(
        "Выберите проект для настройки оценки:",
        reply_markup=choice_keyboard(items, token, "project", prefix="sp"),
    )


@router.callback_query(F.data.startswith("sp:"))
async def spec_choice(
    callback: CallbackQuery,
    state: FSMContext,
    project_service: ProjectService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if not isinstance(callback.message, Message) or callback.from_user is None:
        await callback.answer("Откройте личный чат с ботом.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    data = await state.get_data()
    current = await state.get_state()
    stages = {
        "project": AssessmentSpecWizard.project_code.state,
        "configuration": AssessmentSpecWizard.configuration.state,
    }
    if (
        len(parts) != 4
        or parts[1] != data.get("token")
        or current != stages.get(parts[2])
    ):
        await callback.answer("Список устарел. Начните заново: /new_spec", show_alert=True)
        return
    stage, selected = parts[2], parts[3]
    items = data.get("projects" if stage == "project" else "configurations")
    if not isinstance(items, list):
        await callback.answer("Список устарел. Начните заново: /new_spec", show_alert=True)
        return
    if selected.startswith("p") and selected[1:].isascii() and selected[1:].isdecimal():
        page = int(selected[1:])
        if page * CHOICE_PAGE_SIZE >= len(items):
            await callback.answer("Страница недоступна.", show_alert=True)
            return
        await callback.message.edit_reply_markup(
            reply_markup=choice_keyboard(items, data["token"], stage, page, prefix="sp")
        )
        await callback.answer()
        return
    if not selected.isascii() or not selected.isdecimal() or int(selected) >= len(items):
        await callback.answer("Пункт недоступен.", show_alert=True)
        return
    value = items[int(selected)][1]
    identity = TelegramIdentity(
        telegram_user_id=callback.from_user.id,
        telegram_username=callback.from_user.username,
        display_name=callback.from_user.full_name,
    )
    try:
        if stage == "project":
            projects = await project_service.list_projects(identity)
            if value not in {item.code for item in projects}:
                raise AccessDeniedError("Проект больше недоступен.")
            options = await agent4k_adapter.list_published_assessment_configurations()
            if not options:
                await state.clear()
                await callback.message.answer("В 4К пока нет опубликованных конфигураций оценки.")
            else:
                choices = [(f"{item.code} — {item.name}", str(item.id)) for item in options]
                await state.update_data(project_code=value, configurations=choices)
                await state.set_state(AssessmentSpecWizard.configuration)
                await callback.message.answer(
                    "Выберите доступную конфигурацию 4К:",
                    reply_markup=choice_keyboard(
                        choices, data["token"], "configuration", prefix="sp"
                    ),
                )
        else:
            options = await agent4k_adapter.list_published_assessment_configurations()
            option = next((item for item in options if str(item.id) == value), None)
            if option is None:
                raise AssessmentError("Конфигурация больше не доступна в 4К.")
            await state.update_data(
                assessment_configuration_ref=option.ref,
                assessment_configuration_checksum=option.reference_checksum,
                methodology_ref=option.methodology_ref,
            )
            await state.set_state(AssessmentSpecWizard.required_case_count)
            await callback.message.answer("Сколько кейсов должен пройти участник?")
    except (AccessDeniedError, AssessmentError, Agent4KUnavailableError) as exc:
        await state.clear()
        await callback.message.answer(f"Настройка оценки не выполнена: {exc}")
    await callback.answer()


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
        "Кому отправить результат оценки?\n"
        "Выберите: участнику, преподавателю или обоим.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Участнику")],
                [KeyboardButton(text="Преподавателю")],
                [KeyboardButton(text="Участнику и преподавателю")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
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
            result_recipient_policy={
                "Участнику": "participant",
                "Преподавателю": "instructor",
                "Участнику и преподавателю": "participant_and_instructor",
            }.get((message.text or "").strip(), (message.text or "").strip()),
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
        f"Опубликовать локальный snapshot: /publish_spec {project_code}",
        reply_markup=ReplyKeyboardRemove(),
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
        await message.answer("Формат: /assign_assessment PROJECT_CODE PARTICIPANT_ID ROLE_CODE")
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
async def progress(
    message: Message,
    command: CommandObject,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if message.chat.type != "private":
        await message.answer("Прогресс доступен только в личном чате с ботом.")
        return
    identity = identity_from_message(message)
    assignments = await assessment_service.my_channel_assignments(identity)
    requested = (command.args or "").strip()
    if requested:
        if not requested.isdigit():
            await message.answer("Формат: /progress [ASSIGNMENT_ID]")
            return
        assignments = [item for item in assignments if item.assignment_id == int(requested)]
    if not assignments:
        await message.answer("Нет доступных назначений с опубликованным контекстом.")
        return
    cards = []
    try:
        for item in assignments:
            state = await assessment_service.read_my_channel_state(
                identity,
                assignment_id=item.assignment_id,
                adapter=agent4k_adapter,
            )
            if state.progress is None:
                progress_text = "Прогресс пока не сформирован 4К."
            else:
                progress_text = (
                    f"Пройдено: {state.progress.completed} из {state.progress.required}\n"
                    f"Осталось: {state.progress.remaining}\n"
                    f"Статус 4К: {state.progress.status}"
                )
                if state.progress.next_available_at is not None:
                    progress_text += (
                        f"\nСледующий кейс доступен: {state.progress.next_available_at}"
                    )
            cards.append(
                f"Назначение {item.assignment_id}\n"
                f"{item.project_code} — {item.project_name}\n"
                f"Роль: {item.role_name} ({item.role_code}) v{item.role_version}\n"
                f"{progress_text}\n"
                f"Продолжить: /get_case {item.assignment_id}"
            )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await message.answer("\n\n".join(cards))


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
        + "\n".join(f"{item.id}: {item.name} ({item.code} v{item.version})" for item in programs)
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


def _channel_state_text(state: EducationalChannelState, assignment_id: int) -> str:
    next_action = getattr(state, "next_action", None)
    if next_action is None:
        return "Сейчас действий не требуется. Повторите /progress позже."
    payload = next_action.participant_payload
    lines = [f"Следующий шаг: {next_action.action_type}"]
    if payload:
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    input_kind = str(next_action.input.get("kind", ""))
    if input_kind == "text":
        lines.append("Отправьте ответ следующим сообщением или используйте /cancel.")
    elif input_kind == "confirm":
        lines.append(f"Продолжить: /get_case {assignment_id}")
    return "\n".join(lines)


async def _send_channel_state(
    message: Message, state: EducationalChannelState, assignment_id: int
) -> None:
    content = _channel_state_text(state, assignment_id)
    for start in range(0, len(content), TELEGRAM_TEXT_CHUNK_SIZE):
        await message.answer(content[start : start + TELEGRAM_TEXT_CHUNK_SIZE])


async def _bind_next_text_action(
    identity: TelegramIdentity,
    *,
    assignment_id: int,
    state: EducationalChannelState,
    assessment_service: AssessmentService,
) -> None:
    action = getattr(state, "next_action", None)
    if action is None or action.input.get("kind") != "text":
        return
    key_source = (
        f"{identity.telegram_user_id}:{assignment_id}:{action.action_id}:{state.revision}:text"
    )
    await assessment_service.bind_my_channel_text_action(
        identity,
        assignment_id=assignment_id,
        action_id=action.action_id,
        expected_revision=state.revision,
        idempotency_key="tg-text:" + hashlib.sha256(key_source.encode("utf-8")).hexdigest(),
    )


@router.message(Command("case", "get_case"))
async def case_command(
    message: Message,
    command: CommandObject,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
    state: FSMContext | None = None,
) -> None:
    if message.chat.type != "private":
        await message.answer("Кейс доступен только в личном чате с ботом.")
        return
    argument = (command.args or "").strip()
    identity = identity_from_message(message)
    if not argument:
        assignments = await assessment_service.my_channel_assignments(identity)
        if not assignments:
            await message.answer("Нет доступных назначений с опубликованным контекстом.")
            return
        if len(assignments) == 1:
            assignment_id = assignments[0].assignment_id
        else:
            await message.answer(
                "Выберите назначение:\n"
                + "\n".join(
                    f"/get_case {item.assignment_id} — {item.project_code}, {item.role_name}"
                    for item in assignments
                )
            )
            return
    elif argument.isdigit():
        assignment_id = int(argument)
    else:
        await message.answer("Формат: /get_case ASSIGNMENT_ID")
        return
    try:
        channel_state = await assessment_service.read_my_channel_state(
            identity, assignment_id=assignment_id, adapter=agent4k_adapter
        )
        action = channel_state.next_action
        if action is not None and action.input.get("kind") == "confirm":
            key_source = (
                f"{identity.telegram_user_id}:{assignment_id}:"
                f"{action.action_id}:{channel_state.revision}"
            )
            idempotency_key = "tg-case:" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()
            channel_state = await assessment_service.apply_my_channel_action(
                identity,
                assignment_id=assignment_id,
                action_id=action.action_id,
                expected_revision=channel_state.revision,
                action_input={"kind": "confirm"},
                idempotency_key=idempotency_key,
                adapter=agent4k_adapter,
            )
        await _bind_next_text_action(
            identity,
            assignment_id=assignment_id,
            state=channel_state,
            assessment_service=assessment_service,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await _send_channel_state(message, channel_state, assignment_id)


@router.message(F.text)
async def channel_text_answer(
    message: Message,
    assessment_service: AssessmentService,
    agent4k_adapter: Agent4KPort,
) -> None:
    if message.text is None:
        return
    if message.chat.type != "private":
        return
    if message.text.startswith("/"):
        return
    try:
        submitted = await assessment_service.submit_my_pending_channel_text(
            identity_from_message(message),
            text=message.text,
            telegram_chat_id=message.chat.id,
            telegram_message_id=message.message_id,
            adapter=agent4k_adapter,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    if submitted is None:
        return
    try:
        await _bind_next_text_action(
            identity_from_message(message),
            assignment_id=submitted.assignment_id,
            state=submitted.state,
            assessment_service=assessment_service,
        )
    except (AssessmentError, AccessDeniedError) as exc:
        await message.answer(str(exc))
        return
    await _send_channel_state(message, submitted.state, submitted.assignment_id)


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
