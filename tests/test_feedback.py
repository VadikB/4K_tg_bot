from types import SimpleNamespace

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.application.participants import FeedbackRecipient
from app.application.projects import AccessDeniedError
from app.bot import bot_commands, feedback, feedback_text, help_command, start


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeMessage:
    def __init__(self, text: str = "", *, chat_type: str = "private") -> None:
        self.text = text
        self.chat = SimpleNamespace(type=chat_type)
        self.from_user = SimpleNamespace(
            id=2002, username="student", full_name="Студент"
        )
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.current: object = None

    async def clear(self) -> None:
        self.data = {}
        self.current = None

    async def update_data(self, **kwargs: str) -> None:
        self.data.update(kwargs)

    async def set_state(self, value: object) -> None:
        self.current = value

    async def get_data(self) -> dict[str, str]:
        return self.data


class FakeParticipantService:
    def __init__(self) -> None:
        self.allowed = True
        self.calls = 0

    async def feedback_recipient(self, identity, *, project_code: str):
        self.calls += 1
        assert identity.telegram_user_id == 2002
        if not self.allowed or project_code != "TBA-2026-G01":
            raise AccessDeniedError("Проект недоступен для отправки отзыва.")
        return FeedbackRecipient(project_code, "Студент", 1001)


async def test_feedback_menu_and_help_match_working_command() -> None:
    commands = [item.command for item in bot_commands()]
    assert "feedback" in commands
    assert "new_role" not in commands
    message = FakeMessage()
    await help_command(message)  # type: ignore[arg-type]
    assert "/feedback PROJECT_CODE" in message.answers[0]
    assert "/roles — фиксированные роли" in message.answers[0]
    assert "/new_role" not in message.answers[0]
    admin_service = SimpleNamespace(ensure_actor=lambda _: None)

    async def ensure_actor(_):
        return object(), True

    async def is_superadmin(_):
        return False

    admin_service.ensure_actor = ensure_actor
    admin_service.is_superadmin = is_superadmin
    await start(  # type: ignore[arg-type]
        message, SimpleNamespace(args=None), admin_service, SimpleNamespace(), SimpleNamespace()
    )
    assert "/feedback PROJECT_CODE" in message.answers[1]
    assert "/roles — фиксированные роли" in message.answers[1]
    assert "/new_role" not in message.answers[1]
    assert "администратор проекта" in message.answers[1]
    assert "/projects — мои проекты" in message.answers[1]

    async def superadmin(_):
        return True

    admin_service.is_superadmin = superadmin
    superadmin_message = FakeMessage()
    await start(  # type: ignore[arg-type]
        superadmin_message,
        SimpleNamespace(args=None),
        admin_service,
        SimpleNamespace(),
        SimpleNamespace(),
    )
    assert "суперадминистратор" in superadmin_message.answers[0]
    assert "/projects — все проекты" in superadmin_message.answers[0]


async def test_feedback_sends_only_to_project_teacher() -> None:
    message = FakeMessage("/feedback TBA-2026-G01")
    state = FakeState()
    service = FakeParticipantService()
    await feedback(  # type: ignore[arg-type]
        message, SimpleNamespace(args="TBA-2026-G01"), state, service
    )
    assert state.data == {"project_code": "TBA-2026-G01"}
    text_message = FakeMessage("Удобный формат проекта")
    await feedback_text(text_message, state, service)  # type: ignore[arg-type]
    assert service.calls == 2
    assert text_message.bot.sent == [
        (1001, "Отзыв участника проекта TBA-2026-G01 (Студент):\n\nУдобный формат проекта")
    ]
    assert text_message.answers == ["Отзыв отправлен преподавателю проекта."]
    assert state.data == {}


async def test_feedback_rejects_group_and_nonmember() -> None:
    state = FakeState()
    service = FakeParticipantService()
    group = FakeMessage(chat_type="group")
    await feedback(  # type: ignore[arg-type]
        group, SimpleNamespace(args="TBA-2026-G01"), state, service
    )
    assert service.calls == 0
    assert state.data == {}
    service.allowed = False
    private = FakeMessage()
    await feedback(  # type: ignore[arg-type]
        private, SimpleNamespace(args="TBA-2026-G01"), state, service
    )
    assert state.data == {}
    assert "недоступен" in private.answers[0]


async def test_feedback_rechecks_membership_before_delivery() -> None:
    message = FakeMessage("/feedback TBA-2026-G01")
    state = FakeState()
    service = FakeParticipantService()
    await feedback(  # type: ignore[arg-type]
        message, SimpleNamespace(args="TBA-2026-G01"), state, service
    )
    service.allowed = False
    reply = FakeMessage("Отзыв")
    await feedback_text(reply, state, service)  # type: ignore[arg-type]
    assert reply.bot.sent == []
    assert state.data == {}
    assert "не отправлен" in reply.answers[0]


async def test_feedback_rejects_oversize_text() -> None:
    state = FakeState()
    state.data = {"project_code": "TBA-2026-G01"}
    service = FakeParticipantService()
    reply = FakeMessage("a" * 3001)
    await feedback_text(reply, state, service)  # type: ignore[arg-type]
    assert reply.bot.sent == []
    assert service.calls == 0
    assert state.data == {"project_code": "TBA-2026-G01"}


async def test_feedback_does_not_claim_delivery_after_telegram_error() -> None:
    class FailingBot(FakeBot):
        async def send_message(self, chat_id: int, text: str) -> None:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=text), message="blocked"
            )

    state = FakeState()
    state.data = {"project_code": "TBA-2026-G01"}
    reply = FakeMessage("Отзыв")
    reply.bot = FailingBot()
    await feedback_text(reply, state, FakeParticipantService())  # type: ignore[arg-type]
    assert "не удалось подтвердить" in reply.answers[0]
    assert state.data == {}
