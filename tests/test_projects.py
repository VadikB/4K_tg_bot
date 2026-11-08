from datetime import date

import pytest

from app.application.projects import (
    ProjectDraft,
    normalize_project_code,
    validate_project_draft,
)
from app.bot import (
    generate_course_external_id,
    generate_project_code,
    parse_optional_dates,
    parse_project_timezone,
    parse_required_answer,
)


def draft(**overrides: object) -> ProjectDraft:
    values: dict[str, object] = {
        "code": "tba 2026",
        "name": "Прогноз спроса",
        "course_external_id": "tba-2026-mba01",
        "course": "Технологии бизнес-аналитики",
        "cohort": "МБА-01",
        "business_problem": "Нет достоверного прогноза",
        "expected_result": "Воспроизводимая модель",
        "description": "Учебный проект",
        "timezone": "Europe/Moscow",
        "starts_on": date(2026, 11, 10),
        "ends_on": date(2026, 12, 20),
    }
    values.update(overrides)
    return ProjectDraft(**values)  # type: ignore[arg-type]


def test_project_code_is_normalized() -> None:
    assert normalize_project_code(" tba 2026 ") == "TBA-2026"
    assert validate_project_draft(draft()).code == "TBA-2026"


def test_course_external_id_is_required_and_normalized() -> None:
    result = validate_project_draft(draft(course_external_id=" TBA 2026:MBA01 "))
    assert result.course_external_id == "tba-2026:mba01"


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        validate_project_draft(draft(timezone="Mars/Olympus"))


def test_reversed_dates_are_rejected() -> None:
    with pytest.raises(ValueError, match="завершения"):
        validate_project_draft(
            draft(starts_on=date(2026, 12, 20), ends_on=date(2026, 11, 10))
        )


def test_optional_dates_parser() -> None:
    assert parse_optional_dates("-") == (None, None)
    assert parse_optional_dates("10.11.2026 20.12.2026") == (
        date(2026, 11, 10),
        date(2026, 12, 20),
    )


def test_invalid_dates_are_rejected() -> None:
    with pytest.raises(ValueError, match="корректные даты"):
        parse_optional_dates("31.02.2026 20.12.2026")


def test_project_timezone_parser_accepts_iana_name() -> None:
    assert parse_project_timezone(" Europe/Moscow ") == "Europe/Moscow"


def test_project_timezone_parser_rejects_utc_offset() -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        parse_project_timezone("+3")


def test_required_answer_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="не может быть пустым"):
        parse_required_answer("   ", "Название проекта")


def test_generated_project_code_matches_domain_format() -> None:
    code = generate_project_code()
    assert code.startswith("PRJ-")
    assert len(code) == 16
    assert validate_project_draft(draft(code=code)).code == code


def test_course_external_id_is_stable_for_normalized_name() -> None:
    assert generate_course_external_id(" Технологии  бизнес-аналитики ") == (
        generate_course_external_id("технологии бизнес-аналитики")
    )

