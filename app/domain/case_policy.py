from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CaseDecisionCode(StrEnum):
    ISSUE_NEW = "issue_new"
    CONTINUE_ACTIVE = "continue_active"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    ASSIGNMENT_COMPLETE = "assignment_complete"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True)
class CaseDecision:
    code: CaseDecisionCode
    remaining_cases: int


def local_date(now: datetime, timezone_name: str) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown project timezone") from exc
    return now.astimezone(timezone).date()


def decide_case_request(
    *,
    required_case_count: int,
    completed_case_count: int,
    has_active_case: bool,
    delivered_dates: set[date],
    timezone_name: str,
    now: datetime | None = None,
    available_from: datetime | None = None,
    available_until: datetime | None = None,
) -> CaseDecision:
    if required_case_count <= 0 or completed_case_count < 0:
        raise ValueError("case counters must be valid")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if available_from and current < available_from:
        return CaseDecision(CaseDecisionCode.NOT_AVAILABLE, required_case_count)
    if available_until and current > available_until:
        return CaseDecision(
            CaseDecisionCode.NOT_AVAILABLE,
            max(required_case_count - completed_case_count, 0),
        )
    remaining = max(required_case_count - completed_case_count, 0)
    if remaining == 0:
        return CaseDecision(CaseDecisionCode.ASSIGNMENT_COMPLETE, 0)
    if has_active_case:
        return CaseDecision(CaseDecisionCode.CONTINUE_ACTIVE, remaining)
    if local_date(current, timezone_name) in delivered_dates:
        return CaseDecision(CaseDecisionCode.DAILY_LIMIT_REACHED, remaining)
    return CaseDecision(CaseDecisionCode.ISSUE_NEW, remaining)

