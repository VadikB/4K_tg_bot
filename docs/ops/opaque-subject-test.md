# Выпуск непрозрачной связи: ID4 / PRJ-C100657129C7

Владелец явно поручил исправить интеграцию и довести путь до первого Case на test.
Участник реальный; согласие и ответы даёт сам. Mapping business_analyst →
specialist_expert v1 ID2 согласован. Контракт UUID — docs/sdd/one-way-4k-integration-v1.md;
реализация ограничена данным test-сценарием, общий rollout не заявлен.

Бот хранит UUID4 в project_participants.external_subject_ref до первого HTTP.
Повтор после timeout использует тот же UUID. Email, ФИО и Telegram ID в subject
resolve не отправляются; agent4k_user_id остаётся NULL. Context snapshot содержит
UUID вместо legacy runtime ID. 4К использует анонимный FK owner без средств входа.

Expand migration 0012 добавляет nullable unique UUID, расширяет linked_at check и
разрешает NULL external_assignment_id, пока каноническое назначение не создано.
Существующие данные не переписываются. Проверяются чистый bootstrap и повторная
связь после timeout. Откат кода сохраняет новые поля; downgrade блокируется при
наличии UUID или pending preparation.

После зелёного CI: резервная копия, pg_restore list и восстановление в отдельную
проверочную БД; затем точная migration на сервере и синхронизация её файла для
штатной AST-проверки release gate. Старый app совместим с additive схемой. После
merge проверить SHA, службу и активный endpoint https://test.4k-assistant.ru.
Настроить AGENT4K_ORGANIZATION_REF; связь, mapping и назначение через application
services от владельца проекта. Опубликовать context без контактов, проверить
канонический admission и дать участнику собственные кнопки согласия/подтверждения.
/get_case никогда не подтверждает согласие автоматически.

Нельзя считать first Case полученным по mock-тесту или серверному enqueue.
Нужно фактическое participant-safe содержание в Telegram после ответов человека.
PR #7 с настройками спецификации остаётся отдельным результатом.
