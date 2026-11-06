import asyncio
import logging

from aiogram import Bot

from app.application.assessments import AssessmentService
from app.application.participants import ParticipantService
from app.application.projects import ProjectService
from app.application.roles import RoleService
from app.bot import build_dispatcher
from app.config import Settings
from app.db import session_factory


async def run() -> None:
    settings = Settings()
    settings.validate_runtime()
    logging.basicConfig(level=settings.log_level)
    bot = Bot(token=settings.telegram_bot_token)
    project_service = ProjectService(
        session_factory(settings.database_url),
        bootstrap_admin_ids=settings.bootstrap_admin_telegram_ids,
    )
    participant_service = ParticipantService(
        session_factory(settings.database_url),
        invitation_ttl_hours=settings.invitation_ttl_hours,
    )
    role_service = RoleService(session_factory(settings.database_url))
    assessment_service = AssessmentService(session_factory(settings.database_url))
    try:
        await build_dispatcher(
            project_service, participant_service, role_service, assessment_service
        ).start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())

