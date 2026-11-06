from datetime import UTC, date, datetime

import pytest

from app.domain.case_policy import (
    CaseDecisionCode,
    decide_case_request,
    local_date,
)

NOW = datetime(2026, 11, 6, 21, 30, tzinfo=UTC)


def test_project_timezone_defines_delivery_date() -> None:
    assert local_date(NOW, "Europe/Moscow") == date(2026, 11, 7)


def test_active_case_is_continued_without_new_delivery() -> None:
    decision = decide_case_request(
        required_case_count=8,
        completed_case_count=2,
        has_active_case=True,
        delivered_dates={date(2026, 11, 7)},
        timezone_name="Europe/Moscow",
        now=NOW,
    )
    assert decision.code is CaseDecisionCode.CONTINUE_ACTIVE
    assert decision.remaining_cases == 6


def test_second_case_on_same_local_date_is_rejected() -> None:
    decision = decide_case_request(
        required_case_count=8,
        completed_case_count=2,
        has_active_case=False,
        delivered_dates={date(2026, 11, 7)},
        timezone_name="Europe/Moscow",
        now=NOW,
    )
    assert decision.code is CaseDecisionCode.DAILY_LIMIT_REACHED


def test_new_case_can_be_issued_on_next_date() -> None:
    decision = decide_case_request(
        required_case_count=8,
        completed_case_count=2,
        has_active_case=False,
        delivered_dates={date(2026, 11, 6)},
        timezone_name="Europe/Moscow",
        now=NOW,
    )
    assert decision.code is CaseDecisionCode.ISSUE_NEW


def test_complete_assignment_has_zero_remaining() -> None:
    decision = decide_case_request(
        required_case_count=8,
        completed_case_count=8,
        has_active_case=False,
        delivered_dates=set(),
        timezone_name="Europe/Moscow",
        now=NOW,
    )
    assert decision.code is CaseDecisionCode.ASSIGNMENT_COMPLETE
    assert decision.remaining_cases == 0


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        local_date(datetime(2026, 11, 6), "Europe/Moscow")

