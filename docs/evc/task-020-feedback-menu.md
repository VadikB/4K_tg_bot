# TASK-020: меню и отзыв преподавателю

## Результат

По запросу владельца от 11.11.2026 короткое меню администратора, `/help` и меню
команд Telegram показывают `/roles` без обязательного кода проекта и не показывают
`/new_role`. Эти исправления уже присутствовали в незакоммиченном TASK-017; повторно
их не переписывали. Добавлена работающая `/feedback PROJECT_CODE`: подключённый
участник отправляет текст преподавателю, создавшему проект. После входа по
приглашению студент видит подсказку команды.

## Изменённые файлы

- `app/bot.py`: команда, диалог ввода, меню и подсказка после приглашения.
- `app/application/participants.py`: чтение получателя с проверкой активного участия.
- `tests/test_feedback.py`: меню, отправка, ограничение доступа, повторная проверка.
- `tests/integration/test_project_service.py`: получатель на изолированной БД.
- `README.md`, `docs/sdd/feedback-v1.md`, `docs/sdd/student-channel-v1.md`:
  пользовательский и технический контракт.

## Источники и решения

- Репозиторий бота: `codex/tg-student-channel-client` @
  `fdf092d27e7167123b3d1bf7c01a5371329f440c`; прочитаны `README.md`,
  `docs/sdd/student-channel-v1.md`, `docs/evc/task-017-fixed-semester-roles.md`,
  `app/bot.py`, `app/application/participants.py`, `app/application/projects.py`,
  соответствующие тесты. `CONTRIBUTING.md` и `AGENTS.md` в репозитории бота не найдены.
- Родительский репозиторий 4К: `codex/tg-student-channel-api` @
  `bc63a8ee4a21c36a124dd0040bd44a9f9cccefed`; прочитаны `README.md`,
  `CONTRIBUTING.md`, `docs/evc/agent-workflow.md`, `verification-matrix.md`,
  `artifact-recipe.md`, `docs/architecture/product-4k/1.0/context.md`,
  `registry.md`, Change 01 README, task manifest, ADR-002 и traceability.
  Изменения в 4К не вносились; Change 01 не задаёт предметной нормы для отзыва.
- Решение владельца в этом чате: обратная связь означает отзыв студента
  преподавателю, а не результат оценки 4К. Технический выбор: получатель —
  активный создатель проекта; содержимое передаётся через Telegram без хранения
  в БД и без вызова 4К. Выбор получателя основан на существующей модели проекта.
- Пробел: отдельного ранее согласованного контракта отзыва не было; минимальный
  контракт записан в `docs/sdd/feedback-v1.md`. Подтверждение доставки и UX
  проверены тестами обработчика, реальный Telegram API не проверен.

## Проверки (команда → результат)

- `.venv/bin/ruff check app/bot.py app/application/participants.py tests/test_feedback.py tests/integration/test_project_service.py` → PASS, exit 0.
- `.venv/bin/mypy app` → PASS, exit 0.
- `.venv/bin/pytest -q tests/test_feedback.py tests/test_role_catalog.py tests/test_projects.py` → PASS, 21, exit 0.
- `.venv/bin/pytest -q -m 'not integration'` → PASS, 70, exit 0.
- `TEST_DATABASE_URL=…/feedback_pytest .venv/bin/pytest -q tests/integration/test_project_service.py::test_feedback_recipient_requires_active_project_membership` → PASS, 1, exit 0; отдельный временный PostgreSQL 16, контейнер удалён.
- `git diff --check` → PASS, exit 0.

## Непроверенное

Полный PostgreSQL integration-набор, реальный Telegram API, CI, выкладка и
взаимодействие на реальных аккаунтах — NOT_RUN. Адресный integration-тест
проверяет изменённое правило доступа, но не заменяет полный набор для кандидата.
В рабочей ветке уже находились незакоммиченные изменения иных задач,
поэтому этот результат не является отдельным PR или release-кандидатом.

## Риски, откат и следующий шаг

Конфиг, схема и API 4К не меняются. Текст отзыва проходит через Telegram и
доступен преподавателю в его чате; бот его не сохраняет. Если API не подтверждает
доставку, бот не повторяет запрос автоматически, чтобы не создать дубль.
Откат — убрать `/feedback` из меню и обработчиков и вернуть изменения этого slice;
миграций и сохранённых данных нет. Следующий шаг выпуска — выделить независимый
кандидат из текущего рабочего дерева, запустить CI и проверить путь с тестовыми
Telegram-аккаунтами. Приёмка и выпуск остаются за владельцем.

Открытых вопросов для локальной реализации нет.
