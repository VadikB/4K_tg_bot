#!/usr/bin/env bash
set -Eeuo pipefail

sha="${1:?commit SHA required}"
checksum="${2:?archive checksum required}"
archive="${3:?archive path required}"
root=/home/vadim_bogachev/projects/4K_tg_bot
backup_root=/home/vadim_bogachev/backups
service=4k-tg-bot.service

[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$checksum" =~ ^[a-f0-9]{64}$ ]] || exit 2
[[ "$archive" == "/tmp/4k-tg-bot-${sha}.tar.gz" ]] || exit 2
[[ -f "$archive" && -d "$root/app" && -f "$root/.env" ]] || exit 2
[[ -x "$root/.venv/bin/python" && -x "$root/.venv/bin/alembic" ]] || exit 2

exec 9>/tmp/4k-tg-bot-release.lock
flock -n 9 || { echo 'Another release is running' >&2; exit 1; }
stage="$(mktemp -d /tmp/4k-tg-bot-stage.XXXXXXXX)"
backup=''
old_marker=''
[[ ! -f "$root/.deployed-sha" ]] || old_marker="$(cat "$root/.deployed-sha")"
changed=false
cleanup() { rm -rf "$stage" "$archive"; }
rollback() {
  if [[ "$changed" == true ]]; then
    rsync -a --delete "$backup/app/" "$root/app/"
    if [[ -n "$old_marker" ]]; then
      printf '%s\n' "$old_marker" > "$root/.deployed-sha"
    else
      rm -f "$root/.deployed-sha"
    fi
    sudo -n systemctl restart "$service"
  fi
}
on_error() { trap - ERR; rollback; }
trap on_error ERR
trap cleanup EXIT

printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -
tar -xzf "$archive" -C "$stage"
[[ -d "$stage/app" && -d "$stage/migrations" ]] || exit 2
"$root/.venv/bin/python" - "$stage" "$root" <<'PY'
import ast
import configparser
import sys
import tomllib
from pathlib import Path

stage, root = (Path(arg) for arg in sys.argv[1:])
with (stage / "pyproject.toml").open("rb") as source:
    next_project = tomllib.load(source)["project"]
with (root / "pyproject.toml").open("rb") as source:
    current_project = tomllib.load(source)["project"]
for field in ("requires-python", "dependencies"):
    if next_project[field] != current_project[field]:
        raise SystemExit(f"{field} change: manual release plan required")

def migration_ast(directory: Path) -> dict[str, str]:
    return {
        path.name: ast.dump(ast.parse(path.read_text(), filename=str(path)))
        for path in (directory / "migrations/versions").glob("*.py")
    }

if migration_ast(stage) != migration_ast(root):
    raise SystemExit("Migration change: manual release plan required")
def alembic_config(directory: Path) -> dict[str, dict[str, str]]:
    config = configparser.RawConfigParser()
    config.read(directory / "alembic.ini")
    return {section: dict(config.items(section)) for section in config.sections()}

if alembic_config(stage) != alembic_config(root):
    raise SystemExit("alembic.ini change: manual release plan required")
for path in (stage / "app").rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
PY
if [[ "${DEPLOY_PRECHECK_ONLY:-0}" == 1 ]]; then
  printf 'PRECHECK_OK %s\n' "$sha"
  exit 0
fi
backup="$(mktemp -d "$backup_root/4k-tg-bot-release.XXXXXXXX")"
rsync -a "$root/app/" "$backup/app/"
sudo -n systemctl stop "$service"
changed=true
rsync -a --delete "$stage/app/" "$root/app/"
printf '%s\n' "$sha" > "$root/.deployed-sha"
sudo -n systemctl start "$service"
sleep 5
[[ "$(systemctl show "$service" -p ActiveState --value)" == active ]]
[[ "$(systemctl show "$service" -p SubState --value)" == running ]]
[[ "$(cat "$root/.deployed-sha")" == "$sha" ]]
changed=false
printf 'DEPLOYED %s\n' "$sha"
