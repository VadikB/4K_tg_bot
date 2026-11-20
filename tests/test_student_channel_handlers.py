from dataclasses import replace
from types import SimpleNamespace

from aiogram.filters import Command

from app.application.assessments import StudentChannelAssignmentView, SubmittedChannelInput
from app.bot import (
    bot_commands,
    case_command,
    channel_text_answer,
    progress,
    router,
)
from app.integrations.agent4k import (
    ChannelNextAction,
    ChannelProgress,
    EducationalChannelState,
)


def channel_state(*, revision: int = 3, text_action: bool = True) -> EducationalChannelState:
    return EducationalChannelState(
        assignment_ref="edu:4k-tg-bot:p1:a7",
        cycle_id="cycle-7",
        state="action_required",
        revision=revision,
        next_action=ChannelNextAction(
            action_id="action-7",
            action_type="case_turn",
            participant_payload={"title": "Ситуация"},
            trace={"private": "must not be rendered"},
            input={"kind": "text" if text_action else "confirm"},
        ),
        progress=ChannelProgress(
            status="active",
            completed=0,
            required=3,
            remaining=3,
            next_available_at=None,
        ),
    )


def test_channel_renders_public_text_without_transport_metadata() -> None:
    from app.bot import _channel_state_text

    state = channel_state()
    action = state.next_action
    assert action is not None
    consent = replace(state, next_action=replace(
        action, action_type="acquaintance_consent", input={"kind": "confirm"},
        participant_payload={"purpose": "Цель проекта", "consent_text": "Текст согласия",
                             "consent_version": 1},
    ))
    text = _channel_state_text(consent, 7)
    assert "Цель: Цель проекта" in text and "Текст согласия" in text
    assert "consent_version" not in text and "acquaintance_consent" not in text
    case = replace(state, next_action=replace(action,
        participant_payload={"title": "Кейс", "introduction": "Описание ситуации",
                             "case_id": "technical-id"},
        trace={"private": "hidden", "turns": [
            {"speaker_type": "character", "content_text": "Реплика персонажа"}]},
    ))
    text = _channel_state_text(case, 7)
    assert "Описание ситуации" in text and "Реплика персонажа" in text
    assert "technical-id" not in text and "hidden" not in text


class FakeMessage:
    def __init__(self, text: str, message_id: int = 101) -> None:
        self.text = text
        self.message_id = message_id
        self.chat = SimpleNamespace(id=2002, type="private")
        self.from_user = SimpleNamespace(
            id=2002,
            username="student",
            full_name="Студент",
        )
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markup = kwargs.get("reply_markup")

    async def edit_reply_markup(self, **kwargs) -> None:
        self.markup = kwargs.get("reply_markup")


class FakeChannelService:
    def __init__(self) -> None:
        self.bindings: list[dict[str, object]] = []
        self.submissions: list[dict[str, object]] = []
        self.read_count = 0

    async def read_my_channel_state(self, *args: object, **kwargs: object):
        self.read_count += 1
        return channel_state()

    async def bind_my_channel_text_action(self, *args: object, **kwargs: object):
        self.bindings.append(kwargs)

    async def submit_my_pending_channel_text(self, *args: object, **kwargs: object):
        self.submissions.append(kwargs)
        return SubmittedChannelInput(assignment_id=7, state=channel_state(revision=4))


def test_get_case_appears_in_telegram_commands_and_uses_case_handler() -> None:
    assert "get_case" in [item.command for item in bot_commands()]
    handler = next(item for item in router.message.handlers if item.callback is case_command)
    assert any(
        isinstance(item.callback, Command) and item.callback.commands == ("case", "get_case")
        for item in handler.filters
    )


async def test_case_binds_text_action_without_rendering_trace() -> None:
    message = FakeMessage("/get_case 7")
    service = FakeChannelService()
    await case_command(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args="7"),
        service,
        SimpleNamespace(),
    )
    assert service.bindings[0]["assignment_id"] == 7
    assert service.bindings[0]["action_id"] == "action-7"
    assert service.bindings[0]["expected_revision"] == 3
    assert "Ситуация" in message.answers[0]
    assert "must not be rendered" not in message.answers[0]
    assert "следующим сообщением" in message.answers[0]


async def test_text_handler_forwards_answer_transiently() -> None:
    message = FakeMessage("Мой ответ", message_id=501)
    service = FakeChannelService()
    await channel_text_answer(  # type: ignore[arg-type]
        message,
        service,
        SimpleNamespace(),
    )
    assert service.submissions[0]["text"] == "Мой ответ"
    assert service.submissions[0]["telegram_chat_id"] == 2002
    assert service.submissions[0]["telegram_message_id"] == 501
    assert service.bindings[0]["assignment_id"] == 7
    assert service.bindings[0]["expected_revision"] == 4
    assert message.answers


async def test_case_rejects_group_chat_before_reading_4k() -> None:
    message = FakeMessage("/case 7")
    message.chat.type = "group"
    service = FakeChannelService()
    await case_command(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args="7"),
        service,
        SimpleNamespace(),
    )
    assert message.answers == ["Кейс доступен только в личном чате с ботом."]
    assert service.read_count == 0
    assert not service.bindings


async def test_case_sends_long_participant_payload_in_telegram_sized_messages() -> None:
    class LongPayloadService(FakeChannelService):
        async def read_my_channel_state(self, *args: object, **kwargs: object):
            state = await super().read_my_channel_state(*args, **kwargs)
            assert state.next_action is not None
            return replace(
                state,
                next_action=replace(
                    state.next_action,
                    participant_payload={"text": "X" * 8000},
                ),
            )

    message = FakeMessage("/case 7")
    service = LongPayloadService()
    await case_command(  # type: ignore[arg-type]
        message,
        SimpleNamespace(args="7"),
        service,
        SimpleNamespace(),
    )
    assert len(message.answers) > 1
    assert all(len(part) <= 3500 for part in message.answers)
    assert sum(part.count("X") for part in message.answers) == 8000


async def test_fake_acquaintance_profile_and_first_case_flow(monkeypatch) -> None:
    import app.bot as bot_module

    monkeypatch.setattr(bot_module, "Message", FakeMessage)

    def action_state(revision: int, action_type: str, input_kind: str):
        state = channel_state(revision=revision)
        assert state.next_action is not None
        return replace(
            state,
            next_action=replace(
                state.next_action,
                action_id=f"action-{revision}",
                action_type=action_type,
                participant_payload={"step": action_type},
                input={"kind": input_kind},
            ),
        )

    class FlowService(FakeChannelService):
        def __init__(self) -> None:
            super().__init__()
            self.states = [
                action_state(0, "acquaintance_consent", "confirm"),
                action_state(1, "acquaintance_answer", "text"),
                action_state(2, "acquaintance_answer", "text"),
                action_state(3, "acquaintance_answer", "text"),
                action_state(4, "acquaintance_confirm", "confirm"),
                action_state(5, "personalized_profile_resolve", "confirm"),
                action_state(6, "case_continue", "confirm"),
                action_state(7, "case_turn", "text"),
                replace(
                    channel_state(revision=8),
                    state="waiting",
                    next_action=None,
                    progress=ChannelProgress(
                        status="active",
                        completed=1,
                        required=3,
                        remaining=2,
                        next_available_at="2026-11-11T12:00:00+03:00",
                    ),
                ),
            ]
            self.position = 0
            self.applied: list[dict[str, object]] = []

        async def read_my_channel_state(self, *args: object, **kwargs: object):
            return self.states[self.position]

        async def my_channel_assignments(self, *args: object, **kwargs: object):
            return [
                StudentChannelAssignmentView(
                    assignment_id=7,
                    assignment_ref="edu:4k-tg-bot:p1:a7",
                    project_code="SYNTH-DEMAND",
                    project_name="Прогноз спроса",
                    role_code="business_analyst",
                    role_name="Бизнес-аналитик",
                    role_version=1,
                )
            ]

        async def apply_my_channel_action(self, *args: object, **kwargs: object):
            self.applied.append(kwargs)
            self.position += 1
            return self.states[self.position]

        async def submit_my_pending_channel_text(self, *args: object, **kwargs: object):
            self.applied.append(kwargs)
            self.position += 1
            return SubmittedChannelInput(assignment_id=7, state=self.states[self.position])

    service = FlowService()
    outputs: list[str] = []
    for step in range(9):
        if step in (1, 2, 3, 7):
            message = FakeMessage(f"Ответ {step}", message_id=500 + step)
            await channel_text_answer(  # type: ignore[arg-type]
                message,
                service,
                SimpleNamespace(),
            )
        else:
            message = FakeMessage("/case 7")
            await case_command(  # type: ignore[arg-type]
                message,
                SimpleNamespace(args="7"),
                service,
                SimpleNamespace(),
            )
            current = await service.read_my_channel_state()
            if current.next_action and current.next_action.input.get("kind") == "confirm":
                before = len(service.applied)
                assert message.markup is not None
                # Reading /case never accepts consent; only an actual callback does.
                button_data = message.markup.inline_keyboard[0][0].callback_data

                class Callback:
                    data = button_data
                    from_user = message.from_user

                    async def answer(self, *args, **kwargs):
                        pass

                callback = Callback()
                callback.message = message
                await bot_module.confirm_channel_action(callback, service, SimpleNamespace())
                assert len(service.applied) == before + 1
        outputs.extend(message.answers)
    assert service.position == 8
    assert [item["expected_revision"] for item in service.bindings] == [1, 2, 3, 7]
    assert [item["action_input"] for item in service.applied if "action_input" in item] == [
        {"kind": "confirm"},
        {"kind": "confirm"},
        {"kind": "confirm"},
        {"kind": "confirm"},
    ]
    assert any("кнопку под сообщением" in item for item in outputs)
    assert any("Ваш кейс:" in item for item in outputs)
    assert all("must not be rendered" not in item for item in outputs)
    progress_message = FakeMessage("/progress 7")
    await progress(  # type: ignore[arg-type]
        progress_message,
        SimpleNamespace(args="7"),
        service,
        SimpleNamespace(),
    )
    assert "Пройдено: 1 из 3" in progress_message.answers[0]
    assert "Следующий кейс доступен: 2026-11-11T12:00:00+03:00" in progress_message.answers[0]
