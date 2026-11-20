import pytest

from app.application.participants import (
    ParticipantService,
    invitation_token_hash,
    normalize_email,
    validate_telegram_user_id,
)


def test_invitation_hash_does_not_reveal_token() -> None:
    token = "private-one-time-token"
    digest = invitation_token_hash(token)
    assert token not in digest
    assert len(digest) == 64


def test_invitation_ttl_has_safe_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and 720"):
        ParticipantService(object(), invitation_ttl_hours=0)  # type: ignore[arg-type]


def test_email_is_normalized_for_bot_storage() -> None:
    assert normalize_email(" Student@Example.EDU ") == "student@example.edu"


@pytest.mark.parametrize("value", ["student", "@example.edu", "student@localhost", "a b"])
def test_email_format_is_not_validated_in_bot(value: str) -> None:
    assert normalize_email(value) == value


@pytest.mark.parametrize("value", ["", " " * 5, "x" * 321])
def test_empty_or_oversized_email_is_rejected_for_storage(value: str) -> None:
    with pytest.raises(ValueError, match="от 1 до 320"):
        normalize_email(value)


def test_telegram_user_id_must_be_positive_bigint() -> None:
    assert validate_telegram_user_id(2002) == 2002
    for value in (0, -1, True, 2**63, "2002"):
        with pytest.raises(ValueError, match="Telegram ID"):
            validate_telegram_user_id(value)  # type: ignore[arg-type]
