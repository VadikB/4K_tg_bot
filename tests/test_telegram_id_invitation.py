from datetime import UTC, datetime
from types import SimpleNamespace

from app.application.participants import ParticipantIdentityNotReadyError
from app.bot import (
    ParticipantWizard,
    add_participant,
    participant_display_name,
    participant_email,
    participant_project_choice,
    participant_project_text,
    participant_telegram_user_id,
    router,
    start,
)


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.current: str | None = None

    async def clear(self) -> None:
        self.data = {}
        self.current = None

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, value: object) -> None:
        self.current = value.state

    async def get_data(self) -> dict[str, object]:
        return self.data

    async def get_state(self) -> str | None:
        return self.current


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.bot = object()
        self.chat = SimpleNamespace(type="private")
        self.from_user = SimpleNamespace(id=1001, username="teacher", full_name="Преподаватель")
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def edit_reply_markup(self, **kwargs: object) -> None:
        self.markups.append(kwargs.get("reply_markup"))


class FakeCallback:
    def __init__(self, message: FakeMessage, data: str) -> None:
        self.message = message
        self.from_user = message.from_user
        self.data = data
        self.alerts: list[str | None] = []

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.alerts.append(text)


class FakeProjectService:
    def __init__(self) -> None:
        self.projects = [
            SimpleNamespace(code="TBA-2026-G01", name="Учебный проект", created_by_user_id=7)
        ]

    async def ensure_actor(self, _identity):
        return SimpleNamespace(id=7), True

    async def list_projects(self, _identity):
        return self.projects


class FakeParticipantService:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def create_telegram_invitation(self, identity, **kwargs):
        assert identity.telegram_user_id == 1001
        self.kwargs = kwargs
        return SimpleNamespace(
            project_code="TBA-2026-G01",
            token="test-token",
            expires_at=datetime(2026, 11, 24, tzinfo=UTC),
        )


async def test_invitation_wizard_collects_name_email_and_telegram_id(monkeypatch) -> None:
    monkeypatch.setattr("app.bot.Message", FakeMessage)

    async def fake_start_link(_bot, _token, *, encode):
        assert encode is False
        return "https://t.me/testbot?start=test-token"

    monkeypatch.setattr("app.bot.create_start_link", fake_start_link)
    state = FakeState()
    service = FakeParticipantService()
    start = FakeMessage("/add_participant")
    projects = FakeProjectService()
    await add_participant(start, state, projects)  # type: ignore[arg-type]
    assert start.answers == ["Выберите проект для приглашения:"]
    assert start.markups[0].inline_keyboard[0][0].text == "TBA-2026-G01 — Учебный проект"
    assert state.current == ParticipantWizard.project_code.state
    project = FakeCallback(start, f"ap:{state.data['token']}:project:0")
    await participant_project_choice(project, state, projects)  # type: ignore[arg-type]
    assert start.answers[-1] == "Введите ФИО участника:"
    assert project.alerts == [None]
    name = FakeMessage("Иванов Иван Иванович")
    await participant_display_name(name, state)  # type: ignore[arg-type]
    assert name.answers == ["Введите email участника:"]
    email = FakeMessage(" student-without-at ")
    await participant_email(email, state)  # type: ignore[arg-type]
    assert email.answers == ["Введите числовой Telegram ID участника:"]
    invalid = FakeMessage("@student")
    await participant_telegram_user_id(invalid, state, service)  # type: ignore[arg-type]
    assert service.kwargs == {}
    assert "числовой Telegram ID" in invalid.answers[0]
    identifier = FakeMessage("2002")
    await participant_telegram_user_id(identifier, state, service)  # type: ignore[arg-type]
    assert service.kwargs == {
        "project_code": "TBA-2026-G01",
        "participant_name": "Иванов Иван Иванович",
        "participant_email": "student-without-at",
        "telegram_user_id": 2002,
    }
    assert "https://t.me/testbot?start=test-token" in identifier.answers[0]
    assert state.data == {}


async def test_invitation_project_selection_rechecks_access(monkeypatch) -> None:
    monkeypatch.setattr("app.bot.Message", FakeMessage)
    state = FakeState()
    service = FakeProjectService()
    message = FakeMessage("/add_participant")
    await add_participant(message, state, service)  # type: ignore[arg-type]
    token = state.data["token"]
    service.projects = []
    callback = FakeCallback(message, f"ap:{token}:project:0")
    await participant_project_choice(callback, state, service)  # type: ignore[arg-type]
    assert message.answers[-1] == "Проект больше недоступен для приглашения."
    assert state.data == {}


async def test_invitation_project_requires_button() -> None:
    state = FakeState()
    message = FakeMessage("TBA-2026-G01")
    await participant_project_text(message, state)  # type: ignore[arg-type]
    assert message.answers == ["Выберите проект кнопкой в сообщении выше или /cancel."]
    assert "project_code" not in state.data


async def test_invitation_wizard_does_not_consume_commands() -> None:
    names = {
        "participant_project_text",
        "participant_display_name",
        "participant_email",
        "participant_telegram_user_id",
    }
    for handler in router.message.handlers:
        if handler.callback.__name__ in names:
            text_filter = handler.filters[1]
            assert not await text_filter.call(SimpleNamespace(text="/assign_role"))
            assert await text_filter.call(SimpleNamespace(text="Иванов Иван"))


async def test_id_invitation_start_does_not_promise_email_based_4k_retry() -> None:
    class PendingIdentityService:
        async def accept_invitation(self, _identity, *, token: str):
            assert token == "test-token"
            return SimpleNamespace(code="TBA-2026-G01", name="Проект")

        async def link_my_agent4k_identity(self, _identity, **_kwargs):
            raise ParticipantIdentityNotReadyError("Связь с 4К по Telegram ID ещё не подключена.")

    message = FakeMessage("/start test-token")
    await start(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args="test-token"),
        SimpleNamespace(),
        PendingIdentityService(),
        SimpleNamespace(),
    )
    assert "Вы подключены к проекту" in message.answers[0]
    assert "/get_case" in message.answers[0]
    assert "Оценка 4К пока недоступна" in message.answers[1]
    assert "/link_4k" not in message.answers[1]


async def test_existing_participant_sees_get_case_on_start() -> None:
    class ExistingParticipantProjectService:
        async def ensure_actor(self, _identity):
            return object(), False

        async def list_projects(self, _identity):
            return [SimpleNamespace(code="TBA-2026-G01")]

    message = FakeMessage("/start")
    await start(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args=None),
        ExistingParticipantProjectService(),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    assert "Вы вошли как участник проекта" in message.answers[0]
    assert "/get_case" in message.answers[0]
