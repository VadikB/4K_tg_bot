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
from app.integrations.agent4k import DisabledAgent4KAdapter, HttpAgent4KAdapter


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
    agent4k_adapter = (
        HttpAgent4KAdapter(
            base_url=settings.agent4k_api_url,
            token=settings.agent4k_api_token,
        )
        if settings.agent4k_integration_mode.value == "http"
        else DisabledAgent4KAdapter()
    )
    try:
        await build_dispatcher(
            project_service,
            participant_service,
            role_service,
            assessment_service,
            agent4k_adapter,
            settings.default_project_timezone,
        ).start_polling(bot)
    finally:
        if isinstance(agent4k_adapter, HttpAgent4KAdapter):
            await agent4k_adapter.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())

