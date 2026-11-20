from types import SimpleNamespace

import app.bot as bot_module
from app.application.roles import RoleAssignmentResult, RoleView
from app.bot import assign_role, assign_role_choice, assign_role_keyboard


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


class FakeParticipants:
    async def list_participants(self, identity, *, project_code):
        assert project_code == "PRJ-1"
        return [SimpleNamespace(id=42, display_name="Участник")]


class FakeRoles:
    def __init__(self) -> None:
        self.assigned = []

    async def list_roles(self, identity, *, project_code):
        return [
            RoleView("business_analyst", "Бизнес-аналитик", 2, "published", "b" * 64),
            RoleView("business_analyst", "Бизнес-аналитик", 1, "published", "a" * 64),
        ]

    async def assign(self, identity, **kwargs):
        self.assigned.append(kwargs)
        return RoleAssignmentResult(42, "business_analyst", 1, True, True)


async def test_assign_role_selects_project_participant_and_role(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    participants = FakeParticipants()
    roles = FakeRoles()
    await assign_role(message, SimpleNamespace(args=None), state, projects, roles)
    token = state.data["token"]
    assert message.answers[-1][0] == "Выберите код проекта:"
    assert message.answers[-1][1].inline_keyboard[0][0].text == "PRJ-1 — Первый проект"

    for stage in ("project", "participant", "role"):
        callback = FakeCallback(message, f"ar:{token}:{stage}:0")
        await assign_role_choice(callback, state, projects, participants, roles)
        assert callback.alerts == [None]
        if stage == "project":
            assert message.answers[-1][0] == "Выберите ID участника:"
            assert message.answers[-1][1].inline_keyboard[0][0].text == "ID 42 — Участник"
        if stage == "participant":
            assert message.answers[-1][0] == "Выберите код роли:"
            assert (
                message.answers[-1][1].inline_keyboard[0][0].text
                == "business_analyst — Бизнес-аналитик (v2)"
            )

    assert roles.assigned == [
        {
            "project_code": "PRJ-1",
            "participant_id": 42,
            "role_code": "business_analyst",
        }
    ]
    assert state.current is None
    assert "назначена" in message.answers[-1][0]


async def test_stale_selection_cannot_assign_role(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    roles = FakeRoles()
    await assign_role(message, SimpleNamespace(args=None), state, projects, roles)
    await state.clear()
    callback = FakeCallback(message, "ar:old:project:0")
    await assign_role_choice(callback, state, projects, FakeParticipants(), roles)
    assert "устарел" in callback.alerts[0]
    assert roles.assigned == []


async def test_removed_participant_is_rechecked_before_role_selection(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "Message", FakeMessage)
    message = FakeMessage()
    state = FakeState()
    projects = FakeProjects()
    roles = FakeRoles()
    participants = FakeParticipants()
    await assign_role(message, SimpleNamespace(args=None), state, projects, roles)
    token = state.data["token"]
    await assign_role_choice(
        FakeCallback(message, f"ar:{token}:project:0"),
        state,
        projects,
        participants,
        roles,
    )

    async def removed(identity, *, project_code):
        return []

    participants.list_participants = removed
    await assign_role_choice(
        FakeCallback(message, f"ar:{token}:participant:0"),
        state,
        projects,
        participants,
        roles,
    )
    assert "больше не доступен" in message.answers[-1][0]
    assert roles.assigned == []
    assert state.current is None


def test_assign_role_keyboard_pages_large_lists() -> None:
    items = [(f"Проект {index}", str(index)) for index in range(9)]
    first = assign_role_keyboard(items, "token", "project")
    assert len(first.inline_keyboard) == 9
    assert first.inline_keyboard[-1][0].callback_data == "ar:token:project:p1"
    second = assign_role_keyboard(items, "token", "project", 1)
    assert second.inline_keyboard[0][0].callback_data == "ar:token:project:8"
