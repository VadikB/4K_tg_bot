"""Explicit, one-project operator entry point for additive catalog backfill."""

import argparse
import asyncio
import json
import os

from app.application.projects import ProjectService, TelegramIdentity
from app.db import session_factory


async def _run(args: argparse.Namespace, database_url: str) -> None:
    service = ProjectService(session_factory(database_url), bootstrap_admin_ids=())
    actor = TelegramIdentity(args.actor_telegram_id, "Оператор миграции")
    if args.apply:
        plan = await service.apply_catalog_backfill(
            actor,
            project_code=args.project,
            expected_fingerprint=args.expect_fingerprint,
        )
    else:
        plan = await service.preview_catalog_backfill(actor, project_code=args.project)
    print(
        json.dumps(
            {
                "mode": "applied" if args.apply else "preview",
                "project_code": plan.project_code,
                "catalog_version": plan.catalog_version,
                "catalog_checksum": plan.catalog_checksum,
                "fingerprint": plan.fingerprint,
                "missing": plan.missing,
                "existing": plan.existing,
                "conflicts": plan.conflicts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Просмотр/добавление ролей одного проекта")
    parser.add_argument("--project", required=True, help="Код существующего проекта")
    parser.add_argument("--actor-telegram-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Добавить только отсутствующие роли")
    parser.add_argument("--expect-fingerprint", help="Отпечаток из предварительного просмотра")
    args = parser.parse_args()
    if args.apply and not args.expect_fingerprint:
        parser.error("--apply требует --expect-fingerprint из предварительного просмотра")
    if not args.apply and args.expect_fingerprint:
        parser.error("--expect-fingerprint допустим только с --apply")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("Нужно явно задать DATABASE_URL в окружении")
    asyncio.run(_run(args, database_url))


if __name__ == "__main__":
    main()
