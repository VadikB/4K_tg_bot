import pytest

from app.application.participants import (
    ParticipantService,
    invitation_token_hash,
    normalize_email,
)


def test_invitation_hash_does_not_reveal_token() -> None:
    token = "private-one-time-token"
    digest = invitation_token_hash(token)
    assert token not in digest
    assert len(digest) == 64


def test_invitation_ttl_has_safe_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and 720"):
        ParticipantService(object(), invitation_ttl_hours=0)  # type: ignore[arg-type]


def test_email_is_normalized_for_identity_link() -> None:
    assert normalize_email(" Student@Example.EDU ") == "student@example.edu"


@pytest.mark.parametrize("value", ["", "student", "@example.edu", "student@localhost"])
def test_invalid_participant_email_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="корректный email"):
        normalize_email(value)
