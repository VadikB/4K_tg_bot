from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationMode(StrEnum):
    DISABLED = "disabled"
    MOCK = "mock"
    HTTP = "http"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    telegram_bot_token: str = ""
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/4k_tg_bot"
    agent4k_api_url: str = ""
    agent4k_api_token: str = ""
    agent4k_organization_ref: str = ""
    agent4k_integration_mode: IntegrationMode = IntegrationMode.DISABLED
    bootstrap_admin_telegram_ids: tuple[int, ...] = ()
    superadmin_telegram_ids: tuple[int, ...] = ()
    default_project_timezone: str = "Europe/Moscow"
    invitation_ttl_hours: int = 168

    @field_validator("bootstrap_admin_telegram_ids", "superadmin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(int(item.strip()) for item in value.split(",") if item.strip())
        return value

    def validate_runtime(self) -> None:
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required to start the bot")
        if self.agent4k_integration_mode is IntegrationMode.HTTP:
            if not self.agent4k_api_url or not self.agent4k_api_token:
                raise ValueError("HTTP integration requires AGENT4K_API_URL and AGENT4K_API_TOKEN")
            if self.app_env == "production":
                endpoint = urlsplit(self.agent4k_api_url)
                if (
                    endpoint.scheme != "https"
                    or endpoint.hostname != "test.4k-assistant.ru"
                    or endpoint.port not in {None, 443}
                    or endpoint.username is not None
                    or endpoint.password is not None
                    or endpoint.path not in {"", "/"}
                    or endpoint.query
                    or endpoint.fragment
                ):
                    raise ValueError(
                        "Production bot HTTP integration must target the 4K test stand"
                    )
        if self.agent4k_integration_mode is IntegrationMode.MOCK:
            if self.app_env not in {"local", "test"}:
                raise ValueError("Mock integration is allowed only in local and test environments")
            endpoint = urlsplit(self.agent4k_api_url)
            if endpoint.scheme != "http" or endpoint.hostname not in {
                "127.0.0.1", "localhost", "::1",
            }:
                raise ValueError("Mock integration requires a loopback HTTP AGENT4K_API_URL")
        if not 1 <= self.invitation_ttl_hours <= 720:
            raise ValueError("INVITATION_TTL_HOURS must be between 1 and 720")
