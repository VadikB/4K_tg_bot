import pytest

from app.config import IntegrationMode, Settings


def test_admin_ids_are_parsed_from_csv() -> None:
    settings = Settings(
        telegram_bot_token="token",
        bootstrap_admin_telegram_ids="10, 20",  # type: ignore[arg-type]
    )
    assert settings.bootstrap_admin_telegram_ids == (10, 20)


def test_http_mode_requires_endpoint_and_token() -> None:
    settings = Settings(
        telegram_bot_token="token",
        agent4k_integration_mode=IntegrationMode.HTTP,
    )
    with pytest.raises(ValueError, match="HTTP integration"):
        settings.validate_runtime()


def test_mock_mode_is_blocked_in_production() -> None:
    settings = Settings(
        app_env="production",
        telegram_bot_token="token",
        agent4k_integration_mode=IntegrationMode.MOCK,
    )
    with pytest.raises(ValueError, match="Mock integration"):
        settings.validate_runtime()

