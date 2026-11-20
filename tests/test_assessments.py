from datetime import date

import pytest

from app.application.assessments import AssessmentSpecDraft, validate_spec_draft


def spec_draft(**overrides: object) -> AssessmentSpecDraft:
    values: dict[str, object] = {
        "assessment_configuration_ref": "agent4k:configuration:standard-4k:v1",
        "assessment_configuration_checksum": "a" * 64,
        "methodology_ref": "competencies_4k:1.1",
        "required_case_count": 8,
        "available_from": date(2026, 11, 10),
        "available_until": date(2026, 12, 20),
        "result_recipient_policy": "participant_and_instructor",
    }
    values.update(overrides)
    return AssessmentSpecDraft(**values)  # type: ignore[arg-type]


def test_valid_spec_normalizes_checksum() -> None:
    result = validate_spec_draft(
        spec_draft(assessment_configuration_checksum="A" * 64)
    )
    assert result.assessment_configuration_checksum == "a" * 64


def test_invalid_configuration_checksum_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        validate_spec_draft(spec_draft(assessment_configuration_checksum="not-a-checksum"))


def test_case_count_is_bounded() -> None:
    with pytest.raises(ValueError, match="от 1 до 100"):
        validate_spec_draft(spec_draft(required_case_count=0))


def test_result_recipient_policy_is_closed() -> None:
    with pytest.raises(ValueError, match="политика"):
        validate_spec_draft(spec_draft(result_recipient_policy="everyone"))
