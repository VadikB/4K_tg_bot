# TASK-014: SDD-контракт Telegram-канала студента

## Результат

Зафиксирована SDD-спецификация пути студента до первого Case/AS и зависимость от
draft API v1 платформы 4К.

## Область

- Включено: решения владельца, сценарии, локальные границы, acceptance и откат.
- Не входит: изменение handlers, БД, adapter, deploy и публикация API.

## Источники и решения

- Запрос и решения владельца продукта от 10.11.2026.
- `README.md`, `docs/architecture.md`, TASK-008–TASK-013.
- Модели `ProjectParticipant`, `ParticipantRole`, `AssessmentAssignment`,
  `ProjectAssessmentContextSnapshot`, `CaseDelivery`.
- `app/domain/case_policy.py` — существующая локальная политика, которая не должна
  стать каноническим источником нового пути.
- Draft платформы: `Agent4K/docs/architecture/product-4k/telegram-student-channel-v1.md`.

Стоп-условия: runtime меняет публичный API и требует схемы/совместимости, поэтому
он остаётся следующей отдельной задачей. Документирование явно согласовано и не
меняет поведение или сохранённые данные.

Владелец разрешил draft-разработку в отдельной ветке 10.11.2026. Ветка клиента:
`codex/tg-student-channel-client`, base SHA
`ae42436cabd015a28badbde09dbef796cb82bf28`. Разрешение не включает реальное
подключение, PR как кандидата на merge, merge, deploy или публикацию.

## Изменённый артефакт

- `docs/sdd/student-channel-v1.md`, статус `DRAFT`.

## Проверки

- Ссылки, Markdown, согласованность с README/architecture и platform contract.
- Runtime/unit/integration/HTTP/Telegram — NOT_RUN, поведение не менялось.
- CI — NOT_RUN до push/PR.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Удалить документы TASK-014/SDD и ссылку из README. Код и БД не менялись.

## Следующий шаг

После review platform contract — TASK-015: адаптер channel state/actions, технический
operation store, `/case`, `/progress` из 4К и сквозная regression первого Case.

До решения product owner клиент разрабатывается против fake/mock API. Точное
сочетание candidate SHA фиксируется в platform integration manifest.
