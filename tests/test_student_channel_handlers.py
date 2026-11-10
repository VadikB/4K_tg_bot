from dataclasses import replace
from types import SimpleNamespace

from app.application.assessments import StudentChannelAssignmentView, SubmittedChannelInput
from app.bot import (
    case_command,
    channel_text_answer,
    progress,
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
            status="active", completed=0, required=3, remaining=3,
            next_available_at=None,
        ),
    )


class FakeMessage:
    def __init__(self, text: str, message_id: int = 101) -> None:
        self.text = text
        self.message_id = message_id
        self.chat = SimpleNamespace(id=2002, type="private")
        self.from_user = SimpleNamespace(
            id=2002, username="student", full_name="Студент",
        )
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


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


async def test_case_binds_text_action_without_rendering_trace() -> None:
    message = FakeMessage("/case 7")
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
        message, service, SimpleNamespace(),
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
        message, SimpleNamespace(args="7"), service, SimpleNamespace(),
    )
    assert message.answers == ["Кейс доступен только в личном чате с ботом."]
    assert service.read_count == 0
    assert not service.bindings


async def test_case_sends_long_participant_payload_in_telegram_sized_messages() -> None:
    class LongPayloadService(FakeChannelService):
        async def read_my_channel_state(self, *args: object, **kwargs: object):
            state = await super().read_my_channel_state(*args, **kwargs)
            assert state.next_action is not None
            return replace(state, next_action=replace(
                state.next_action, participant_payload={"text": "X" * 8000},
            ))

    message = FakeMessage("/case 7")
    service = LongPayloadService()
    await case_command(  # type: ignore[arg-type]
        message, SimpleNamespace(args="7"), service, SimpleNamespace(),
    )
    assert len(message.answers) > 1
    assert all(len(part) <= 3500 for part in message.answers)
    assert sum(part.count("X") for part in message.answers) == 8000


async def test_fake_acquaintance_profile_and_first_case_flow() -> None:
    def action_state(revision: int, action_type: str, input_kind: str):
        state = channel_state(revision=revision)
        assert state.next_action is not None
        return replace(state, next_action=replace(
            state.next_action,
            action_id=f"action-{revision}",
            action_type=action_type,
            participant_payload={"step": action_type},
            input={"kind": input_kind},
        ))

    class FlowService(FakeChannelService):
        def __init__(self) -> None:
            super().__init__()
            self.states = [
                action_state(0, "acquaintance_consent", "confirm"),
                action_state(1, "acquaintance_answer", "text"),
                action_state(2, "acquaintance_answer", "text"),
                action_state(3, "acquaintance_answer", "text"),
                action_state(4, "personalized_profile_resolve", "confirm"),
                action_state(5, "case_continue", "confirm"),
                action_state(6, "case_turn", "text"),
                replace(
                    channel_state(revision=7),
                    state="waiting",
                    next_action=None,
                    progress=ChannelProgress(
                        status="active", completed=1, required=3, remaining=2,
                        next_available_at="2026-11-11T12:00:00+03:00",
                    ),
                ),
            ]
            self.position = 0
            self.applied: list[dict[str, object]] = []

        async def read_my_channel_state(self, *args: object, **kwargs: object):
            return self.states[self.position]

        async def my_channel_assignments(self, *args: object, **kwargs: object):
            return [StudentChannelAssignmentView(
                assignment_id=7,
                assignment_ref="edu:4k-tg-bot:p1:a7",
                project_code="SYNTH-DEMAND",
                project_name="Прогноз спроса",
                role_code="business_analyst",
                role_name="Бизнес-аналитик",
                role_version=1,
            )]

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
    for step in range(8):
        if step in (1, 2, 3, 6):
            message = FakeMessage(f"Ответ {step}", message_id=500 + step)
            await channel_text_answer(  # type: ignore[arg-type]
                message, service, SimpleNamespace(),
            )
        else:
            message = FakeMessage("/case 7")
            await case_command(  # type: ignore[arg-type]
                message, SimpleNamespace(args="7"), service, SimpleNamespace(),
            )
        outputs.extend(message.answers)
    assert service.position == 7
    assert [item["expected_revision"] for item in service.bindings] == [1, 2, 3, 6]
    assert [item["action_input"] for item in service.applied if "action_input" in item] == [
        {"kind": "confirm"}, {"kind": "confirm"}, {"kind": "confirm"},
    ]
    assert any("Продолжить: /case 7" in item for item in outputs)
    assert any("case_turn" in item for item in outputs)
    assert all("must not be rendered" not in item for item in outputs)
    progress_message = FakeMessage("/progress 7")
    await progress(  # type: ignore[arg-type]
        progress_message, SimpleNamespace(args="7"), service, SimpleNamespace(),
    )
    assert "Пройдено: 1 из 3" in progress_message.answers[0]
    assert "Следующий кейс доступен: 2026-11-11T12:00:00+03:00" in progress_message.answers[0]
