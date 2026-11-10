# Перенос 4K Telegram bot через локальный архив

Статус: этап A выполнен 10.11.2026. Старый бот остановлен; финальный дамп и `.env`
скачаны в защищённый каталог `/Users/vadim_bogachev/4k-tg-bot-migration` на Mac.
Локальный checksum дампа прошёл; PostgreSQL на старом сервере продолжает работать.
Новый IP не нужен для первого этапа. Второй этап предполагает Ubuntu
24.04 на новом сервере; для другого дистрибутива замените установку пакетов.
При паузе свыше 24 часов часть входящих сообщений может пропасть: [Telegram хранит
updates не дольше 24 часов](https://core.telegram.org/bots/api#getting-updates).
Пользователям потребуется отправить такие сообщения повторно.

Учётную запись `vadim_bogachev` создают **на новом сервере** в этапе B1, когда
станет известен его IP. На старом сервере одноимённая учётная запись уже
существует: она использовалась для SSH-доступа и резервной копии, но не создавалась
и не изменялась в ходе подготовки. На Mac остаётся закрытый ключ `~/.ssh/mws_key`.

## Зафиксированное состояние 10.11.2026

- Старый SSH: `ssh -i ~/.ssh/mws_key vadim_bogachev@147.45.39.8`.
- Код: `/home/vadim_bogachev/projects/4K_tg_bot`, чистый checkout
  `ae42436cabd015a28badbde09dbef796cb82bf28` на
  `codex/task-008-educational-context-snapshot`.
- `4k-tg-bot.service` запускался от `vadim_bogachev` через `.venv/bin/python
  -m app.main` и `.env` в каталоге проекта; сейчас остановлен.
- PostgreSQL: `4k-tg-bot-postgres`, `postgres:16-alpine`, том
  `4k_tg_bot_pgdata`, порт только `127.0.0.1:55432`.
- Версия схемы: Alembic `0008_context_preparations`. На старом хосте работают
  другие контейнеры; их нельзя останавливать командами для бота.
- Ветка `codex/tg-server-migration` основана на серверном коммите. Изменения в
  ней: эта инструкция, Compose/systemd-шаблоны и снимок 30 версий Python-пакетов.
  Код бота, миграции БД и предметные артефакты не менялись.

Локальная рабочая ветка бота содержит более поздний код и незакоммиченные
изменения; они не входят в перенос. Дамп БД содержит данные участников, а `.env`
содержит секреты. Оба файла держите вне Git, с правами `600`, и передавайте по SSH.

## Этап A. Сохранить старый сервер до его закрытия

### A1. Подготовить защищённый каталог на своём компьютере

**Выполнено:** каталог создан на Mac с правами `700`. Команды для повторной проверки:

```bash
umask 077
mkdir -p "$HOME/4k-tg-bot-migration"
chmod 700 "$HOME/4k-tg-bot-migration"
```

Предварительный online-дамп также сохранён на старом сервере с именем
`4k_tg_bot_online_20261110.dump`, но для переноса используйте финальный.

Проверенный перенос кода обеспечит удалённая ветка `codex/tg-server-migration`.
Сверьте её commit с SHA из отчёта о подготовке; не берите автоматически HEAD
другой рабочей ветки. Закрытый SSH-ключ `~/.ssh/mws_key` не копируйте.

### A2. Остановить бот и создать финальный дамп

Этот шаг **уже выполнен** 10.11.2026. Команды оставлены для повторной процедуры;
готовый файл не перезаписывайте. Telegram сохранит непринятые updates не более
24 часов; длительный перерыв необходимо сообщить пользователям бота.
На **старом сервере**, только если потребуется новый финальный снимок:

```bash
sudo systemctl stop 4k-tg-bot.service
! systemctl is-active --quiet 4k-tg-bot.service
umask 077
mkdir -p "$HOME/migration-backup"
chmod 700 "$HOME/migration-backup"
BACKUP_FILE="$HOME/migration-backup/4k_tg_bot_final.dump"
test ! -e "$BACKUP_FILE"
sudo docker exec 4k-tg-bot-postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  > "$BACKUP_FILE"
test -s "$BACKUP_FILE"
(cd "$HOME/migration-backup" && sha256sum 4k_tg_bot_final.dump > 4k_tg_bot_final.dump.sha256)
```

Готовый финальный дамп:
`/home/vadim_bogachev/migration-backup/4k_tg_bot_final.dump`, 64 356 байт,
права `600`, SHA-256
`cc11083edfd2c529dba18495584af6f85aa2343e188227d68e995019a2c9e2c3`.
Каталог архива проверен через `pg_restore --list` без вывода данных.

Проверьте коды выхода `pg_dump` и `test -s`. При ошибке дампа **не закрывайте**
старый сервер: устраните причину и сделайте новый файл, не перезаписывая
существующий. Если перенос отменён, можно возобновить бот командой
`sudo systemctl start 4k-tg-bot.service` на старом сервере.

### A3. Скачать и проверить архив на Mac

**Выполнено:** `bot.env`, финальный дамп и `.sha256` скачаны по SSH на Mac вне Git;
права файлов `600`, `shasum -a 256 -c` вернул `OK`. Ниже использованные команды;
для нового снимка выберите другой каталог, чтобы сохранить проверенную копию:

```bash
scp -i ~/.ssh/mws_key \
  vadim_bogachev@147.45.39.8:/home/vadim_bogachev/projects/4K_tg_bot/.env \
  "$HOME/4k-tg-bot-migration/bot.env"
scp -i ~/.ssh/mws_key \
  vadim_bogachev@147.45.39.8:/home/vadim_bogachev/migration-backup/4k_tg_bot_final.dump \
  "$HOME/4k-tg-bot-migration/"
scp -i ~/.ssh/mws_key \
  vadim_bogachev@147.45.39.8:/home/vadim_bogachev/migration-backup/4k_tg_bot_final.dump.sha256 \
  "$HOME/4k-tg-bot-migration/"
chmod 600 "$HOME/4k-tg-bot-migration/"*
cd "$HOME/4k-tg-bot-migration"
shasum -a 256 -c 4k_tg_bot_final.dump.sha256
test -s bot.env
test -s 4k_tg_bot_final.dump
```

Ожидаемый результат checksum — `OK`. Проверьте наличие трёх файлов в каталоге и
сохраните их также в согласованном защищённом резервном хранилище. Не используйте
автоматическую синхронизацию открытого облака или Git. **Только после этой проверки
закрывайте старый сервер.**

## Этап B. Восстановить после выдачи нового IP

### B1. Создать пользователя и настроить SSH

Войдите в новый сервер через консоль провайдера или первоначальный
административный аккаунт. Проверьте SSH fingerprint нового сервера по данным
провайдера. Следующий блок выполняется **только на новом сервере после его
выдачи**:

```bash
sudo useradd --create-home --shell /bin/bash vadim_bogachev
sudo usermod --append --groups sudo vadim_bogachev
sudo passwd vadim_bogachev
sudo install -d -m 700 -o vadim_bogachev -g vadim_bogachev /home/vadim_bogachev/.ssh
sudo tee /home/vadim_bogachev/.ssh/authorized_keys >/dev/null <<'PUBLIC_KEY'
ВСТАВЬТЕ_ОДНУ_СТРОКУ_ИЗ_ЛОКАЛЬНОГО_ФАЙЛА_~/.ssh/mws_key.pub
PUBLIC_KEY
sudo chown vadim_bogachev:vadim_bogachev /home/vadim_bogachev/.ssh/authorized_keys
sudo chmod 600 /home/vadim_bogachev/.ssh/authorized_keys
```

На **Mac** получите одну строку публичного ключа через
`cat ~/.ssh/mws_key.pub` и проверьте вход:

```bash
ssh -i ~/.ssh/mws_key vadim_bogachev@NEW_IP 'id -un'
```

### B2. Установить код и зависимости

На **новом сервере** под `vadim_bogachev`:

```bash
sudo apt update
sudo apt install -y git python3.12 python3.12-venv docker.io docker-compose-v2
sudo systemctl enable --now docker
mkdir -p ~/projects
git clone --branch codex/tg-server-migration https://github.com/VadikB/4K_tg_bot.git ~/projects/4K_tg_bot
cd ~/projects/4K_tg_bot
git rev-parse HEAD
git diff --exit-code ae42436cabd015a28badbde09dbef796cb82bf28 HEAD -- app migrations alembic.ini pyproject.toml
python3.12 -m venv .venv
.venv/bin/python -m pip install -e . -c deploy/runtime-constraints.txt
.venv/bin/python -m pip check
```

Сверьте SHA с отчётом. Constraints отражают реально установленные версии пакетов
старого `.venv` на Python 3.12.3, но не содержат wheel-файлов и их хешей. Если
какая-либо версия недоступна, не меняйте её молча во время восстановления.

### B3. Передать закрытые файлы и поднять пустую БД

На **Mac**:

```bash
scp -i ~/.ssh/mws_key "$HOME/4k-tg-bot-migration/bot.env" \
  vadim_bogachev@NEW_IP:/home/vadim_bogachev/projects/4K_tg_bot/.env
scp -i ~/.ssh/mws_key "$HOME/4k-tg-bot-migration/4k_tg_bot_final.dump" \
  vadim_bogachev@NEW_IP:/home/vadim_bogachev/4k_tg_bot_final.dump
scp -i ~/.ssh/mws_key "$HOME/4k-tg-bot-migration/4k_tg_bot_final.dump.sha256" \
  vadim_bogachev@NEW_IP:/home/vadim_bogachev/4k_tg_bot_final.dump.sha256
```

На **новом сервере**:

```bash
chmod 600 ~/projects/4K_tg_bot/.env ~/4k_tg_bot_final.dump*
sha256sum -c ~/4k_tg_bot_final.dump.sha256
cd ~/projects/4K_tg_bot
```

В закрытом `.env` сохраните Telegram token, bootstrap admin IDs и настройки
интеграции 4К; проверьте приватно `AGENT4K_API_URL`, если он указывал на старый IP.
Добавьте `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` для нового контейнера
и согласованный с ними `DATABASE_URL` вида
`postgresql+asyncpg://USER:PASSWORD@127.0.0.1:55432/DB`. Задайте новый длинный
случайный пароль, например hex-строку из `openssl rand -hex 24`; храните его только
в закрытом `.env`. Не выводите `.env` в журнал или чат.

```bash
sudo docker compose --env-file .env -p 4k_tg_bot -f deploy/compose.production.yml config --quiet
sudo docker compose --env-file .env -p 4k_tg_bot -f deploy/compose.production.yml up -d db
sudo docker exec 4k-tg-bot-postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

`compose.production.yml` связывает PostgreSQL только с loopback. Не запускайте
корневой `docker-compose.yml`: он предназначен для локальной разработки, открывает
порт на всех интерфейсах и содержит примерные учётные данные.

### B4. Восстановить БД и запустить бот

На **новом сервере**:

```bash
cd ~/projects/4K_tg_bot
sudo docker exec -i 4k-tg-bot-postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < ~/4k_tg_bot_final.dump
sudo docker exec 4k-tg-bot-postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"'
.venv/bin/alembic current
sudo install -m 0644 deploy/4k-tg-bot.service.example /etc/systemd/system/4k-tg-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now 4k-tg-bot.service
systemctl is-active 4k-tg-bot.service
```

Обе проверки схемы должны показать `0008_context_preparations`. Не выполняйте
`alembic upgrade head`: код взят с того же коммита, что и старый сервер. Проверьте
в Telegram `/start` и заранее известный безопасный сценарий, затем интеграцию 4К,
если она была включена. Старый экземпляр бота не запускайте параллельно.

## Откат и закрытие работы

До запуска нового бота можно остановить его пустой сервис и сохранить локальный
архив. После обработки новых сообщений на новом сервере его БД становится
источником последних данных. При сбое сначала остановите новый сервис, сделайте
финальный дамп новой БД тем же способом и восстановите его на исправленном хосте
PostgreSQL 16; старый архив остаётся доказательством состояния на момент закрытия
старого сервера. Не возобновляйте старую копию БД после новых записей.

После приёмки определите срок хранения защищённых дампов и удалите временные
копии отдельным решением владельца. `.env`, дампы и ключи остаются вне Git.

## Проверки подготовки и открытые условия

Проверены без вывода `.env` и записей БД: SSH-доступ, Git SHA и чистота checkout,
служба, образ/том/порт PostgreSQL, доступность БД, версия Alembic, Python 3.12.3
и целостность установленного Python-окружения (`pip check`). Локально проверены
синтаксис команд и Compose с синтетическими значениями. Предварительный и
финальный дампы созданы на старом сервере, финальный архив структурно проверен;
файлы скачаны на Mac, локальный checksum подтверждён. Восстановление не выполнено:
IP нового сервера и его первый административный вход неизвестны; они нужны только
для этапа B. Второй копии в отдельном резервном хранилище пока нет.
