# TASK-005: спецификация и назначение оценки

## Результат

Администратор создаёт и публикует локальную спецификацию оценки, затем назначает
её участнику на точную опубликованную роль. Участник читает операционный прогресс.

## Область

- Включено: snapshot/checksum, lifecycle draft/published, период и timezone,
  required cases, получатели результата, assignment и participant progress.
- Не входит: проверка конфигурации через API 4К, создание Cycle, выдача Case,
  Dialogue, Evidence, расчёт и Results.

## Источники и решения

Повторно использованы источники TASK-001–004, runtime snapshot-контракт 4К и решение
владельца «делаем» от 06.11.2026. Base commit
`85a267396ba21267b17ddd481da49deebd0eb642`.

`published` относится только к неизменяемости локальной проектной спецификации.
Snapshot явно содержит `runtime_admission=pending_agent4k_verification`; назначение
остаётся `assigned`, `external_cycle_id=NULL`. Поэтому локальная публикация не выдаётся
за допуск AssessmentConfiguration или запуск PM-04.

Стоп-условие интеграции с 4К остаётся открытым, но не блокирует локальные данные:
endpoint проверки конфигурации и создания Cycle ещё не утверждён. Зависимая выдача
кейсов не реализуется.

## Критерии приёмки

- [x] Snapshot фиксирует ref/checksum конфигурации, методологию, период и политику.
- [x] Published snapshot неизменяем на уровне PostgreSQL.
- [x] Назначить оценку можно только на assigned published role.
- [x] Назначение сохраняет точные версии спецификации и роли.
- [x] До интеграции `external_cycle_id` отсутствует и runtime pending отображается.
- [x] `/progress` показывает пройдено/осталось без промежуточной оценки навыков.
- [ ] Конфигурация проверяется через API 4К и создаётся Cycle.
- [ ] Telegram transport проверен с реальным токеном.

## Проверки

- `.venv/bin/ruff check .` → PASS.
- `.venv/bin/mypy app` → PASS, 16 source files.
- Unit → PASS, 25 tests.
- PostgreSQL integration → PASS, 9 tests, включая отказ для неназначенной роли.
- Alembic existing DB `0003 -> 0004` → PASS.
- Alembic downgrade/upgrade `0004 -> 0003 -> 0004` → PASS.
- Fresh migration `base -> 0001 -> 0002 -> 0003 -> 0004` → PASS.
- Telegram/API 4К → NOT_RUN: токен и утверждённый endpoint отсутствуют.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Отключить команды спецификаций и назначений. Предпочтительно оставить схему для
чтения и откатить приложение. `0004 -> 0003` удаляет guards, но не данные; опубликованные
snapshots не переписывать и назначения не превращать в запущенные Cycle.
