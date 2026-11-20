from types import SimpleNamespace

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
