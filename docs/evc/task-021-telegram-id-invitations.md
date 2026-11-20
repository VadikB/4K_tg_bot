# TASK-021: приглашение участника по ФИО, email и Telegram ID

## Результат и граница

Владелец 17.11.2026 выбрал Telegram ID как идентификатор приглашения, а
18.11.2026 уточнил состав вводимых данных: ФИО, email и Telegram ID.
`/add_participant` запрашивает код проекта и эти три поля. Бот выдаёт прежнюю
одноразовую ссылку; принять её может только указанный Telegram ID. Существующие
приглашения по email продолжают работать по прежнему контракту.

Решение владельца: данные учебного проекта, участника, роли и Telegram identity
остаются в БД бота; взаимодействие с 4К инициирует только бот через тестовую
Organization. 4К остаётся владельцем собственных Assessment/Cycle/Dialogue/Results,
получает минимальный immutable контекст. Telegram ID и email не передаются в 4К.

Связь с 4К — отдельное зависимое решение: текущий endpoint
`POST /integration/v1/participants/resolve` принимает email и имя. Владелец
выбрал хранить email только в боте. Нужен новый сервисный контракт по непрозрачному
ключу, возвращающий внутренний ID 4К. До его реализации ни старые, ни новые
приглашения не запускают identity-link и не готовы к оцениванию без ранее
сохранённого `agent4k_user_id`. Проект контракта —
`docs/sdd/one-way-4k-integration-v1.md`, статус `DRAFT`.

## Источники

- Бот: `codex/tg-student-channel-client` @
  `fdf092d27e7167123b3d1bf7c01a5371329f440c`, `README.md`,
  `docs/evc/task-003-participant-invitations.md`,
  `task-006-participant-email-link.md`, `task-007-agent4k-identity-client.md`,
  `docs/sdd/student-channel-v1.md`, `app/bot.py`,
  `app/application/participants.py`, `app/models.py`, migrations `0002/0005/0010`,
  затронутые тесты. В дереве уже есть незакоммиченные изменения TASK-017–020;
  их не перезаписывать.
- 4К: `codex/tg-student-channel-api` @
  `bc63a8ee4a21c36a124dd0040bd44a9f9cccefed`, `README.md`,
  `CONTRIBUTING.md`, рабочий цикл, матрица, рецепт, архитектурный context/Registry,
  Change 01, task manifest, ADR-002 и traceability; для этой задачи адресно
  просмотрены `Api/integration_routes.py`, `integration_identity_service.py`,
  `database/bootstrap/v1/base.sql`, контрактные тесты. Change 01 не задаёт
  способ Telegram identity для учебного бота.

## Совместимость и проверки

Новая nullable колонка в `project_participants` хранит ожидаемый Telegram ID.
Старые строки остаются NULL и продолжают использовать токен. Новые строки
сохраняют ФИО и нормализованный email в БД бота; при принятии проверяется
совпадение ID до изменения данных. Введённое ФИО не заменяется отображаемым именем
Telegram. Токен остаётся одноразовым, в БД хранится только его SHA-256.

Адресные проверки: корректный/чужой ID, повтор, истечение срока, старое
email-приглашение, дубликат в одном проекте, миграция на существующих строках,
backend unit, PostgreSQL integration на отдельной базе, Ruff, mypy, diff.
Откат до выкладки — убрать изменения этого slice. После выкладки сохранять
выданные ссылки и новые строки; downgrade блокируется при любой строке с Telegram ID
до согласованного переноса, без удаления данных.

## Реализация и фактические проверки

- `app/bot.py`: мастер с вводом кода проекта, ФИО, email и Telegram ID; после
  принятия сообщает о недоступной оценке, без ложного обещания retry.
- `app/application/participants.py`: отдельный метод нового приглашения, проверка
  владельца проекта и дубля, проверка ID до принятия токена; старый email-метод
  сохранён для уже выданных ссылок. Email-based identity-link отключён для всех;
  ранее сохранённые внутренние ID 4К читаются без изменения.
- `app/integrations/agent4k.py`: прежний метод `resolve_participant` сохранён в
  интерфейсе совместимости, но не делает HTTP-запрос и возвращает отказ.
- `app/models.py`, `migrations/versions/0011_invited_telegram_user_id.py`:
  nullable Telegram ID, уникальность в проекте, положительное значение,
  data-preserving downgrade guard.
- `README.md`, `docs/sdd/student-channel-v1.md`,
  `docs/sdd/one-way-4k-integration-v1.md`: UX, пределы и проект внешнего контракта.
- `.venv/bin/ruff check .` → PASS, exit 0.
- `.venv/bin/mypy app` → PASS, exit 0, 18 source files.
- `.venv/bin/pytest -q -m 'not integration'` → PASS, 73, exit 0.
- `TEST_DATABASE_URL=…/tg_contract_pytest .venv/bin/pytest -q -m integration` →
  PASS, 21, exit 0, PostgreSQL 16 в отдельном временном контейнере; контейнер удалён.
- Миграция `0011 -> 0010 -> 0011` с legacy-строкой → PASS; downgrade после
  сохранения нового Telegram ID → штатный отказ без потери строки.
- `git diff --check` → PASS, exit 0.

Реальный Telegram API, новый identity endpoint 4К,
общий API/Telegram прогон, CI, PR, merge и deploy — NOT_RUN. Статус интеграции:
только draft-проектирование; участники без ранее сохранённого `agent4k_user_id`
остаются без оценочных назначений.
Реальные данные и секреты не использовались.

## Стоп-условия и риски

Предметная норма оценки не меняется. Локальная схема расширяется совместимо;
старые приглашения и связи остаются читаемыми. Новый публичный контракт 4К,
способ создания технического пользователя, точная тестовая Organization,
права и жизненный цикл ещё не утверждены: зависимая реализация 4К остановлена.
Telegram ID и email остаются только в БД бота и не попадают в assessment snapshot
или вызов 4К. В audit payload сохраняются лишь признаки наличия полей.
Перед выпуском нужен review миграции, контракта и прав,
CI и реальный Telegram-прогон на синтетических аккаунтах.

## Состояние и передача

Ветка бота: `codex/tg-student-channel-client` @
`fdf092d27e7167123b3d1bf7c01a5371329f440c` плюс незакоммиченный diff;
миграция `0011` зависит от ещё незакоммиченной `0010_role_profile_bindings`.
Бот-путь уточнён по трём полям, исходящая передача email отключена.
Следующий шаг: review draft-контракта 4К,
решение об Organization и способе создания внутреннего пользователя,
затем отдельная реализация endpoint/adapter и сквозная проверка. Владелец
принимает результат и выпуск. `branch_push=false`, `pr=false`, `merge=false`,
`deploy=false`, `version_bump=false`.
