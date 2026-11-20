# TASK-023: email без проверки формата и обновление сервера

## Решение и граница

Владелец 19.11.2026 потребовал: проверить добавление участника синтетическим
тестом, отключить валидацию формата email именно в боте, обновить все текущие
локальные изменения бота на сервере и перезапустить сервис. Уточнение объёма:
владелец выбрал «Все текущие локальные изменения бота» при наличии более старой
серверной версии. Код 4К не меняется. Предметная оценка, доставка email и
подтверждение владения адресом не добавляются.

## Источники и исходное состояние

- Локальный бот: `codex/tg-student-channel-client` @
  `fdf092d27e7167123b3d1bf7c01a5371329f440c` плюс незакоммиченный diff;
  `README.md`, `app/application/participants.py`, `app/bot.py`, модели и миграции
  `0009`–`0011`, `tests/test_participants.py`,
  `tests/test_telegram_id_invitation.py`, `tests/integration/test_project_service.py`.
- Сервер перед обновлением: `codex/tg-server-migration` @
  `f7c5d54ff24a854b4afd4a7ad12739d83f5857ad`, чистый checkout,
  `4k-tg-bot.service` с `WorkingDirectory=/home/vadim_bogachev/projects/4K_tg_bot`;
  БД на `0008_context_preparations`. Сервисный режим `production disabled`: связь
  с 4К выключена. Секреты, пользовательские строки БД и env-файл не читались.
- Основной 4К: Change 01 и draft-контракт Telegram Student Channel не являются
  допуском методологии в runtime. В этом изменении нет вызовов или данных 4К.

## Реализация и проверки

`normalize_email` теперь выполняет только `strip()`, `lower()` и проверку
непустого значения длиной до 320 символов для хранения в `String(320)`.
Строка без `@` принимается. Уникальность в пределах проекта сохраняется.
Мастер Telegram и сервис используют одну функцию; 4К не изменён. Синтетический
мастер проходит с `student-without-at`; integration сохраняет и принимает
приглашение с `StudentWithoutAt`, проверяет нормализацию и отсутствие нового
identity-link по email.

- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 18 source files.
- `.venv/bin/pytest -q -m 'not integration'` → PASS, 76 тестов.
- `TEST_DATABASE_URL=…/tg_email_pytest .venv/bin/pytest -q -m integration`
  → PASS, 22 теста на временной изолированной PostgreSQL 16; контейнер удалён.
- `git diff --check` → PASS.

## Выпуск и откат

До копирования кода требуется backup БД и сохранение серверного commit.
Новые миграции добавочные: `0009` — техническая таблица,
`0010` — таблица и nullable FK,
`0011` — nullable Telegram ID. При неудачном запуске вернуть серверный код
на сохранённый commit и оставить добавочные миграции до отдельного согласованного
отката данных. Временный deployment archive не содержит `.env`, `.venv`, `.git`
или пользовательских данных. Запуск проверить через systemd status и новый PID.

## Факт обновления 19.11.2026

- Архив всех выбранных локальных файлов без `.env`, `.venv`, `.git` и macOS
  `._*`: SHA-256
  `bc23c3cf97a2cd5a3afa58be42f83df2880d0cd9688b096e4026a3e3b9efc2d6`.
  Хеш локального и серверного архива совпал. Первый staging-архив содержал
  AppleDouble-файлы и не прошёл `compileall`; его не копировали в рабочий каталог.
  Исправленный архив прошёл `compileall` и импорт `app.main` на сервере.
- До миграции на сервере создана закрытая резервная копия
  `/home/vadim_bogachev/backups/4k_tg_bot_before_20261119.dump` (`0600`,
  66555 байт); формат проверен `pg_restore --list` без вывода содержимого.
- Перед обновлением и после него `SELECT count(*) FROM projects` → `4`.
  `alembic current` перешёл с `0008_context_preparations` на
  `0011_invited_telegram_user_id`. Данные проектов не удалялись и не
  переносились. `.env` и серверный venv не заменялись.
- `4k-tg-bot.service` остановлен, обновлён из исправленного staging-архива и
  запущен; `ActiveState=active`, `SubState=running`, `MainPID=1407909`,
  `NRestarts=0`. Хеши `participants.py`, `projects.py` и `bot.py` на сервере
  совпадают с локальными. Серверный `normalize_email("StudentWithoutAt")` вернул
  `studentwithoutat` без обращения к БД или 4К.
- Серверный checkout остаётся на прежнем Git commit с рабочим diff из архива;
  неизменяемым реквизитом выпуска служит SHA-256 архива, не ветка. Пакеты для
  Ruff, mypy и pytest в runtime venv сервера отсутствуют; их серверные проверки
  `NOT_RUN`, применены локальные PASS выше. Реальный Telegram API и общий путь
  Telegram→4К не проверялись. `AGENT4K_INTEGRATION_MODE=disabled` остаётся
  выключенным, код 4К и его БД не менялись.
