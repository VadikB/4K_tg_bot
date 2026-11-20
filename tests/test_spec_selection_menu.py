from types import SimpleNamespace

import pytest

import app.bot as bot_module
from app.bot import AssessmentSpecWizard, new_spec, spec_choice
from app.integrations.agent4k import (
    Agent4KUnavailableError,
    PublishedAssessmentConfigurationOption,
)


class FakeState:
    def __init__(self) -> None:
        self.data = {}
        self.current = None

    async def clear(self) -> None:
        self.data = {}
        self.current = None

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def set_state(self, value) -> None:
        self.current = value.state

    async def get_data(self):
        return self.data.copy()

    async def get_state(self):
        return self.current


class FakeMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(type="private")
        self.from_user = SimpleNamespace(id=11, username="teacher", full_name="Преподаватель")
        self.answers = []

    async def answer(self, text, **kwargs) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))

    async def edit_reply_markup(self, **kwargs) -> None:
        self.answers.append(("page", kwargs["reply_markup"]))


class FakeCallback:
    def __init__(self, message, data) -> None:
        self.message = message
        self.from_user = message.from_user
        self.data = data
        self.alerts = []

    async def answer(self, text=None, **kwargs) -> None:
        self.alerts.append(text)


class FakeProjects:
    async def ensure_actor(self, identity):
        return object(), True

    async def list_projects(self, identity):
        return [SimpleNamespace(code="PRJ-1", name="Первый проект")]


class FakeAdapter:
    def __init__(self) -> None:
        self.options = (
            PublishedAssessmentConfigurationOption(
                id=17,
                ref="agent4k:configuration:17",
                code="standard",
                name="Стандартная",
                methodology_ref="agent4k:methodology:m1:v2",
                reference_checksum="a" * 64,
                is_default=True,
            ),
        )

    async def list_published_assessment_configurations(self):
        return self.options


async def test_spec_wizard_selects_project_and_published_configuration(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    adapter = FakeAdapter()

    await new_spec(message, state, projects)
    token = state.data["token"]
    assert message.answers[-1][1].inline_keyboard[0][0].text == "PRJ-1 — Первый проект"

    await spec_choice(FakeCallback(message, f"sp:{token}:project:0"), state, projects, adapter)
    assert state.current == AssessmentSpecWizard.configuration.state
    assert message.answers[-1][1].inline_keyboard[0][0].text == "standard — Стандартная"

    await spec_choice(
        FakeCallback(message, f"sp:{token}:configuration:0"), state, projects, adapter
    )
    assert state.current == AssessmentSpecWizard.required_case_count.state
    assert state.data["assessment_configuration_ref"] == "agent4k:configuration:17"
    assert state.data["assessment_configuration_checksum"] == "a" * 64
    assert state.data["methodology_ref"] == "agent4k:methodology:m1:v2"


async def test_removed_configuration_aborts_without_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    adapter = FakeAdapter()
    await new_spec(message, state, projects)
    token = state.data["token"]
    await spec_choice(FakeCallback(message, f"sp:{token}:project:0"), state, projects, adapter)
    adapter.options = ()
    await spec_choice(
        FakeCallback(message, f"sp:{token}:configuration:0"), state, projects, adapter
    )
    assert state.current is None
    assert "больше не доступна" in message.answers[-1][0]


async def test_unavailable_4k_aborts_configuration_selection(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    adapter = FakeAdapter()

    async def unavailable():
        raise Agent4KUnavailableError("4К недоступен")

    adapter.list_published_assessment_configurations = unavailable
    await new_spec(message, state, projects)
    await spec_choice(
        FakeCallback(message, f"sp:{state.data['token']}:project:0"),
        state, projects, adapter,
    )
    assert state.current is None
    assert "4К недоступен" in message.answers[-1][0]


async def test_recipient_step_displays_russian_buttons():
    message = FakeMessage()
    message.text = "-"
    state = FakeState()
    await bot_module.spec_period(message, state)
    assert state.current == AssessmentSpecWizard.recipient_policy.state
    keyboard = message.answers[-1][1].keyboard
    assert [row[0].text for row in keyboard] == [
        "Участнику", "Преподавателю", "Участнику и преподавателю"
    ]


@pytest.mark.parametrize("label,policy", [
    ("Участнику", "participant"),
    ("Преподавателю", "instructor"),
    ("Участнику и преподавателю", "participant_and_instructor"),
    ("participant", "participant"),
])
async def test_recipient_button_preserves_service_contract(label, policy):
    message = FakeMessage()
    message.text = label
    state = FakeState()
    state.data = dict(project_code="PRJ-1", assessment_configuration_ref="cfg",
        assessment_configuration_checksum="a" * 64, methodology_ref="m1",
        required_case_count="5", available_from=None, available_until=None)

    class Service:
        async def create_spec_draft(self, identity, *, project_code, draft):
            assert identity.telegram_user_id == 11
            assert project_code == "PRJ-1"
            assert draft.result_recipient_policy == policy
            return SimpleNamespace(version=1, required_case_count=5,
                checksum="b" * 64, runtime_admission="pending")

    await bot_module.spec_recipient_policy(message, state, Service())
    assert state.data == {}
    assert message.answers[-2][1].remove_keyboard
    text, markup = message.answers[-1]
    assert "Количество кейсов: 5" in text
    assert "Период: без ограничения по датам" in text
    assert "Checksum" not in text and "Runtime" not in text and "Draft" not in text
    assert markup.inline_keyboard[0][0].text == "Утвердить настройки"
    assert markup.inline_keyboard[0][0].callback_data == "approve_spec:PRJ-1:1"


@pytest.mark.parametrize("allowed", [True, False])
async def test_approval_checks_project_and_pins_displayed_version(monkeypatch, allowed):
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    callback = FakeCallback(message, "approve_spec:PRJ-1:3")
    calls = []

    class Projects:
        async def list_projects(self, identity):
            return [SimpleNamespace(code="PRJ-1")] if allowed else []

    class Assessments:
        async def publish_spec(self, identity, *, project_code, expected_version):
            calls.append((identity.telegram_user_id, project_code, expected_version))

    await bot_module.approve_spec_settings(callback, Projects(), Assessments())
    assert calls == ([(11, "PRJ-1", 3)] if allowed else [])
    if allowed:
        assert message.answers[0] == ("page", None)
        assert "утверждены" in message.answers[-1][0]
    else:
        assert "недоступен" in callback.alerts[-1]
