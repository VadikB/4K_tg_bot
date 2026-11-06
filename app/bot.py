from datetime import date
from typing import Any

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.application.projects import (
    AccessDeniedError,
    DuplicateProjectCodeError,
    ProjectDraft,
    ProjectService,
    TelegramIdentity,
)

router = Router()


class ProjectWizard(StatesGroup):
    code = State()
    name = State()
    course = State()
    cohort = State()
    business_problem = State()
    expected_result = State()
    description = State()
    timezone = State()
    dates = State()


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


@router.message(CommandStart())
async def start(message: Message, project_service: ProjectService) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if is_admin:
        await message.answer(
            "Вы вошли как администратор.\n"
            "/new_project — создать проект\n"
            "/projects — список проектов"
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
        "/progress — прогресс оценки\n"
        "/case — получить или продолжить кейс\n"
        "/cancel — отменить текущий диалог"
    )


@router.message(Command("new_project"))
async def new_project(
    message: Message, state: FSMContext, project_service: ProjectService
) -> None:
    _, is_admin = await project_service.ensure_actor(identity_from_message(message))
    if not is_admin:
        await message.answer("Создавать проекты может только администратор.")
        return
    await state.clear()
    await state.set_state(ProjectWizard.code)
    await message.answer("Введите короткий код проекта, например TBA-2026-G01:")


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Диалог отменён.")


@router.message(ProjectWizard.code, F.text)
async def project_code(message: Message, state: FSMContext) -> None:
    await state.update_data(code=message.text)
    await state.set_state(ProjectWizard.name)
    await message.answer("Название проекта:")


@router.message(ProjectWizard.name, F.text)
async def project_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(ProjectWizard.course)
    await message.answer("Название курса:")


@router.message(ProjectWizard.course, F.text)
async def project_course(message: Message, state: FSMContext) -> None:
    await state.update_data(course=message.text)
    await state.set_state(ProjectWizard.cohort)
    await message.answer("Поток или учебная группа; '-' если не требуется:")


@router.message(ProjectWizard.cohort, F.text)
async def project_cohort(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    await state.update_data(cohort=None if text.strip() == "-" else text)
    await state.set_state(ProjectWizard.business_problem)
    await message.answer("Опишите бизнес-проблему:")


@router.message(ProjectWizard.business_problem, F.text)
async def project_problem(message: Message, state: FSMContext) -> None:
    await state.update_data(business_problem=message.text)
    await state.set_state(ProjectWizard.expected_result)
    await message.answer("Какой результат должен получить проект?")


@router.message(ProjectWizard.expected_result, F.text)
async def project_result(message: Message, state: FSMContext) -> None:
    await state.update_data(expected_result=message.text)
    await state.set_state(ProjectWizard.description)
    await message.answer("Краткое описание проекта:")


@router.message(ProjectWizard.description, F.text)
async def project_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text)
    await state.set_state(ProjectWizard.timezone)
    await message.answer("Часовой пояс IANA, например Europe/Moscow:")


@router.message(ProjectWizard.timezone, F.text)
async def project_timezone(message: Message, state: FSMContext) -> None:
    await state.update_data(timezone=(message.text or "").strip())
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
        f"Статус: {project.status}\n"
        f"Часовой пояс: {project.timezone}"
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


@router.message(Command("progress", "case"))
async def not_connected_yet(message: Message) -> None:
    await message.answer("Функция станет доступна после подключения проекта администратором.")


def build_dispatcher(project_service: ProjectService) -> Dispatcher:
    dispatcher = Dispatcher(project_service=project_service)
    dispatcher.include_router(router)
    return dispatcher

