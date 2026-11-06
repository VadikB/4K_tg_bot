import pytest

from app.application.roles import (
    RoleDraft,
    definition_checksum,
    parse_items,
    validate_role_draft,
)


def role_draft(**overrides: object) -> RoleDraft:
    values: dict[str, object] = {
        "code": "business analyst",
        "name": "Бизнес-аналитик",
        "mission": "Формализовать бизнес-задачу",
        "responsibilities": ("Собрать требования",),
        "typical_tasks": ("Провести интервью",),
        "expected_outputs": ("Описание бизнес-задачи",),
        "interactions": ("Заказчик", "Data Scientist"),
        "crisp_dm_stages": ("business_understanding", "data_understanding"),
    }
    values.update(overrides)
    return RoleDraft(**values)  # type: ignore[arg-type]


def test_role_code_and_stages_are_normalized() -> None:
    result = validate_role_draft(role_draft())
    assert result.code == "business-analyst"
    assert result.crisp_dm_stages == ("business_understanding", "data_understanding")


def test_unknown_crisp_dm_stage_is_rejected() -> None:
    with pytest.raises(ValueError, match="Неизвестные стадии"):
        validate_role_draft(role_draft(crisp_dm_stages=("analysis",)))


def test_semicolon_items_are_trimmed() -> None:
    assert parse_items("Первый; Второй ;") == ("Первый", "Второй")


def test_definition_checksum_is_canonical() -> None:
    first = definition_checksum({"name": "Роль", "version": 1})
    second = definition_checksum({"version": 1, "name": "Роль"})
    assert first == second
    assert len(first) == 64
