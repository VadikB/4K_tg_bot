# TASK-013: команды выбора AssessmentProgram

## Результат

Преподаватель использует `/admission_programs ASSIGNMENT_ID` для просмотра только
совместимых программ и `/connect_program ASSIGNMENT_ID PROGRAM_ID` для явного
подключения. После подключения бот предлагает повторить `/prepare_cycle`.

## Безопасность и границы

- Команды доступны только системному admin и требуют опубликованного snapshot.
- HTTP выполняется вне DB transaction; локальный audit не содержит персональных данных.
- Произвольный или несовместимый program ID отклоняется 4К.
- Остальные admission-причины показываются с предметным следующим действием, но не
  закрываются техническим флагом.

## Проверки

- Ruff/mypy → PASS; unit → 36 PASS; PostgreSQL integration → 12 PASS.
- Реальный общий `.env` → NOT_RUN до настройки токенов.
- CI → NOT_RUN до push/PR.

## Действия выпуска

`branch_push=false`, `pr=false`, `merge=false`, `deploy=false`,
`version_bump=false`, `artifact_publish=false`.

## Откат

Удалить команды и методы adapter. Уже выполненное подключение программы не отменять
автоматически; использовать штатную смену connection в 4К.
