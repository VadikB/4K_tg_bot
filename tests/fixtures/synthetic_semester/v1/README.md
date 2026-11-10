# Synthetic Semester 1.0

Версионируемый QA-набор для Telegram Student Channel. Он не является runtime-
конфигурацией, публикацией методологии или результатом оценки реального участника.

Источником пяти CRISP-DM-ролей служит приложенный документ `ТГ бот для студентов.md`.
На текущий семестр роли, их обязанности и взаимодействия считаются frozen для этого
набора. Изменение создаёт новую версию каталога и новые checksum в `manifest.json`.

Сценарии первого эшелона:

- `single-role-first-case` — один проект, одна роль, путь до первой AS;
- `multi-project-multi-role-isolation` — один синтетический участник, два проекта,
  три роли и независимые Assignment/Profile/Cycle/progress.

Проверка файлового контракта и topology-evaluator:

```bash
.venv/bin/pytest -q tests/test_synthetic_semester.py
```

PASS этой команды подтверждает только целостность пакета и способность evaluator
обнаружить смешивание scope. Фактический системный PASS требует readback из
изолированных PostgreSQL БД бота и 4К, Channel API и достижения первой AS.
