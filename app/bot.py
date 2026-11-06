from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def start(message: Message) -> None:
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
        "/progress — прогресс оценки\n"
        "/case — получить или продолжить кейс"
    )


@router.message(Command("projects", "progress", "case"))
async def not_connected_yet(message: Message) -> None:
    await message.answer("Функция станет доступна после подключения проекта администратором.")


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher

