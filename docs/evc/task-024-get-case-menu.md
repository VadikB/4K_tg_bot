# TASK-024: `/get_case` в меню участника

## Результат и граница

Владелец 19.11.2026 указал, что участник проекта не видит кнопку `/get_case`.
Добавлен Telegram command `/get_case` как алиас существующего `/case` без изменения
предметного сценария, выдачи Case, авторизации или контракта 4К. `/case` остаётся
работоспособным. При `/start` существующий участник видит меню с `/get_case`;
после принятия приглашения команда также показана с условием «после назначения
оценки». При отсутствии назначения бот сохраняет прежний отказ без выдачи Case.

## Источники и факт до изменения

- `README.md`, `docs/sdd/student-channel-v1.md` (`DRAFT`),
  `docs/evc/task-015-student-channel-client.md`, `app/bot.py`,
  `tests/test_student_channel_handlers.py`, `tests/test_telegram_id_invitation.py`.
- Локальный бот: `codex/tg-student-channel-client` @
  `fdf092d27e7167123b3d1bf7c01a5371329f440c` плюс незакоммиченные задачи
  TASK-017–023. Серверный код был обновлён по TASK-023; 4К интеграция на сервере
  имеет режим `disabled`.
- До изменения `bot_commands()` содержал только `/case`, а `/start` участника
  не показывал команду получения кейса. Кнопка Telegram создаётся при
  `set_my_commands` во время запуска бота.

## Проверки и откат

- Роутер принимает и `/case`, и `/get_case`; unit проверяет регистрацию Telegram
  command, алиас, прежний обработчик, меню нового и существующего участника.
- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 18 source files.
- `.venv/bin/pytest -q -m 'not integration'` → PASS, 78 тестов.
- `TEST_DATABASE_URL=…/tg_get_case_pytest .venv/bin/pytest -q -m integration`
  → PASS, 22 теста на отдельной временной PostgreSQL 16; контейнер удалён.
- `git diff --check` → PASS.

Откат — вернуть предыдущий `app/bot.py` и перезапустить сервис. Миграция БД не
нужна; сохранённые проекты не меняются. Реальный Telegram API и получение Case
на общем контуре 4К не проверены. Отдельное решение о включении 4К остаётся
действующим; кнопка сама по себе не открывает недопущенную оценку.

## Обновление сервера

По ранее данному владельцем разрешению обновлять серверный бот рабочий файл
`app/bot.py` сохранён в
`/home/vadim_bogachev/backups/bot_before_get_case_20261119.py`, новая версия
с SHA-256 `6ed62a0a35c048890dcf3ffcdc82aa7de9c34ffd9364436496757d998fedcd25`
проверена в staging и установлена при остановленном сервисе. После запуска
`4k-tg-bot.service`: `active/running`, `MainPID=1424099`, `NRestarts=0`.
Серверный `bot_commands()` содержит `get_case`; количество проектов до и после
равно `4`. `.env`, БД и код 4К не менялись. Серверный runtime venv не содержит
pytest/Ruff/mypy, поэтому тесты выполнены локально на точном коде файла.
