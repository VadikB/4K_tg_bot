import pytest

from app.application.participants import ParticipantService, invitation_token_hash


def test_invitation_hash_does_not_reveal_token() -> None:
    token = "private-one-time-token"
    digest = invitation_token_hash(token)
    assert token not in digest
    assert len(digest) == 64


def test_invitation_ttl_has_safe_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and 720"):
        ParticipantService(object(), invitation_ttl_hours=0)  # type: ignore[arg-type]
