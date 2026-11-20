# TASK-025: последовательный выбор для `/assign_role`

## Вход и границы

Запрос владельца от 20.11.2026: выбирать проект, участника и роль последовательно
из списков. Работа ведётся в `4K_tg_bot`, ветка `codex/tg-student-channel-client`,
основание `fdf092d27e7167123b3d1bf7c01a5371329f440c`. В рабочем дереве до
задачи уже были несвязанные изменения; они сохранены. 4К API, данные, миграции,
каталог и опубликованные версии не меняются. Старый вызов с тремя аргументами
сохранён для совместимости.

Прочитаны `4K/README.md`, `4K/CONTRIBUTING.md`, `4K/docs/evc/agent-workflow.md`,
`4K/docs/evc/verification-matrix.md`, `4K/docs/evc/artifact-recipe.md`,
`4K/docs/architecture/product-4k/1.0/context.md`, `registry.md`, Change 01
`README.md`, task `manifest.json`, `4K/docs/adr/002-cycle-as-dialogue-contracts.md`,
`4K/docs/evc/change01-traceability.md`, бот `README.md`,
`docs/sdd/student-channel-v1.md`, `docs/evc/task-017-fixed-semester-roles.md`,
`app/bot.py`, сервисы и тесты ролей, проектов, участников. Для этой UI-задачи
методологическое правило M1 не изменяется: M1 v1.4 FROZEN/CURRENT=NO,
Change 01 WORKING, предметный каталог бота `2026.1` с checksum из TASK-017.
Исходные SHA-256 находятся в task `manifest.json`; новая методологическая норма
не вводится.

## Решение и трасса

Решение владельца → `/assign_role` без аргументов → `ProjectService.list_projects`
→ `ParticipantService.list_participants` → опубликованные каталожные версии
`RoleService.list_roles` → прежний `RoleService.assign`. Каждый этап показывает
inline-кнопки по восемь пунктов со страницами. Выбор привязан к FSM и случайному
токену; старые кнопки отклоняются. Проект и участник перепроверяются перед
следующим этапом, а запись и её предметные ограничения остаются в `RoleService`.
Для нескольких published-версий показывается последняя. `/cancel` очищает выбор.

Реализация: `app/bot.py`, справка `README.md`. Регрессия:
`tests/test_assign_role_menu.py` — три этапа, страницы, последняя версия,
устаревшая кнопка и удалённый участник.

## Проверки и передача

- `.venv/bin/ruff check .` — PASS.
- `.venv/bin/ruff format --check app/bot.py tests/test_assign_role_menu.py` — PASS.
- `.venv/bin/mypy app` — PASS.
- `.venv/bin/pytest -q -m 'not integration'` — PASS, 82 теста; 22 integration deselected.
- `git diff --check` — PASS.
- PostgreSQL integration, реальный Telegram API и CI — NOT_RUN: этот срез не меняет
  БД и выполнялся локально без внешнего контура. Перед merge остаются обязательные
  CI и приёмка владельца; выпуск клиента ограничен `development_only` по SDD.

Откат до выпуска: убрать только diff TASK-025. После выпуска вернуть прежний
обработчик и справку отдельным релизом; данные назначений не переписывать.
