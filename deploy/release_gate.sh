#!/usr/bin/env bash
# Install outside the working checkout as an authorized_keys forced command.
set -Eeuo pipefail

root=/home/vadim_bogachev/projects/4K_tg_bot
remote=https://github.com/VadikB/4K_tg_bot.git
[[ "${SSH_ORIGINAL_COMMAND:-}" =~ ^deploy\ ([a-f0-9]{40})$ ]] || exit 2
sha="${BASH_REMATCH[1]}"

exec 9>/tmp/4k-tg-bot-release-gate.lock
flock -n 9 || { echo 'Another release is running' >&2; exit 1; }
current="$(GIT_TERMINAL_PROMPT=0 git ls-remote "$remote" refs/heads/main | cut -f 1)"
[[ "$current" == "$sha" ]] || { echo 'Not current main' >&2; exit 1; }
GIT_TERMINAL_PROMPT=0 git -C "$root" fetch --no-tags "$remote" main
[[ "$(git -C "$root" rev-parse FETCH_HEAD)" == "$sha" ]] || exit 1

archive="/tmp/4k-tg-bot-${sha}.tar.gz"
git -C "$root" archive --format=tar "$sha" | gzip -n > "$archive"
checksum="$(sha256sum "$archive" | cut -d ' ' -f 1)"
git -C "$root" show "$sha:deploy/release_remote.sh" |
  bash -s -- "$sha" "$checksum" "$archive"
