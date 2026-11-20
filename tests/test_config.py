import pytest

from app.config import IntegrationMode, Settings
from app.integrations.agent4k import DisabledAgent4KAdapter, HttpAgent4KAdapter
from app.main import make_agent4k_adapter


def test_admin_ids_are_parsed_from_csv() -> None:
    settings = Settings(
        telegram_bot_token="token",
        bootstrap_admin_telegram_ids="10, 20",  # type: ignore[arg-type]
        superadmin_telegram_ids="30, 40",  # type: ignore[arg-type]
    )
    assert settings.bootstrap_admin_telegram_ids == (10, 20)
    assert settings.superadmin_telegram_ids == (30, 40)


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


def test_mock_mode_requires_loopback_stub() -> None:
    for url in ("", "https://127.0.0.1:8000", "http://agent4k.example", "http://0.0.0.0"):
        settings = Settings(
            app_env="test", telegram_bot_token="token",
            agent4k_integration_mode=IntegrationMode.MOCK,
            agent4k_api_url=url,
        )
        with pytest.raises(ValueError, match="loopback HTTP"):
            settings.validate_runtime()
    settings = Settings(
        app_env="test", telegram_bot_token="token",
        agent4k_integration_mode=IntegrationMode.MOCK,
        agent4k_api_url="http://127.0.0.1:8000",
    )
    settings.validate_runtime()


async def test_adapter_selection_follows_integration_mode() -> None:
    disabled = make_agent4k_adapter(Settings(agent4k_integration_mode=IntegrationMode.DISABLED))
    assert isinstance(disabled, DisabledAgent4KAdapter)
    mock = make_agent4k_adapter(Settings(
        agent4k_integration_mode=IntegrationMode.MOCK,
        agent4k_api_url="http://127.0.0.1:8000",
    ))
    assert isinstance(mock, HttpAgent4KAdapter)
    await mock.close()

