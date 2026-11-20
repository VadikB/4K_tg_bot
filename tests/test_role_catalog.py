import json
from types import SimpleNamespace

import pytest

from app.application.roles import RoleProfileBindingView
from app.bot import map_role, roles
from app.role_catalog import load_role_catalog


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(
            id=1001, username="teacher", full_name="Преподаватель"
        )
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def test_semester_catalog_has_five_checksum_verified_roles() -> None:
    catalog = load_role_catalog()
    assert catalog.version == "2026.1"
    assert [role.code for role in catalog.roles] == [
        "business_analyst", "data_researcher", "data_engineer", "ml_engineer", "validator",
    ]
    assert all(role.description and role.interactions for role in catalog.roles)


def test_catalog_rejects_tampered_content(tmp_path, monkeypatch) -> None:
    from app import role_catalog

    manifest = json.loads((role_catalog.PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "roles.json").write_text('{"schema_version":1,"roles":[]}', encoding="utf-8")
    monkeypatch.setattr(role_catalog, "PACKAGE", tmp_path)
    with pytest.raises(ValueError, match="ROLE_CATALOG_CHECKSUM_INVALID"):
        load_role_catalog()


async def test_roles_without_project_shows_shared_catalog() -> None:
    message = FakeMessage()
    await roles(message, SimpleNamespace(args=None), SimpleNamespace())  # type: ignore[arg-type]
    assert "Формат: /roles PROJECT_CODE" not in message.answers[0]
    assert "Бизнес-аналитик" in message.answers[0]
    assert "Валидатор" in message.answers[0]


async def test_map_role_passes_exact_reference_and_shows_version() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def publish_role_profile_binding(self, identity, **kwargs):
            self.kwargs = kwargs
            assert identity.telegram_user_id == 1001
            return RoleProfileBindingView("business_analyst", 1, 2, 17, "a" * 64)

    service = FakeService()
    message = FakeMessage()
    adapter = object()
    await map_role(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args=f"PRJ-1 business_analyst 17 {'a' * 64}"),
        service,
        adapter,
    )
    assert service.kwargs["agent4k_role_profile_version_id"] == 17
    assert service.kwargs["agent4k_role_profile_checksum"] == "a" * 64
    assert service.kwargs["adapter"] is adapter
    assert "версия сопоставления 2" in message.answers[0]
    assert "a" * 64 not in message.answers[0]
