"""Versioned, checksum-verified student role catalog for the current semester."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.enums import CrispDmStage

PACKAGE = Path(__file__).parent / "artifacts" / "crisp_dm_roles" / "2026"
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
STAGES = frozenset(stage.value for stage in CrispDmStage)


@dataclass(frozen=True)
class CatalogRole:
    code: str
    name: str
    crisp_dm_phases: tuple[str, ...]
    description: str
    interactions: tuple[str, ...]


@dataclass(frozen=True)
class RoleCatalog:
    catalog_id: str
    version: str
    sha256: str
    roles: tuple[CatalogRole, ...]

    def find(self, code: str) -> CatalogRole | None:
        normalized = code.strip().lower()
        return next((role for role in self.roles if role.code == normalized), None)


def load_role_catalog() -> RoleCatalog:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("id") != "crisp-dm-student-roles"
        or manifest.get("status") != "frozen_for_semester"
        or manifest.get("artifact") != "roles.json"
        or not isinstance(manifest.get("version"), str)
    ):
        raise ValueError("ROLE_CATALOG_MANIFEST_INVALID")
    raw = (PACKAGE / "roles.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest.get("sha256"):
        raise ValueError("ROLE_CATALOG_CHECKSUM_INVALID")
    document = json.loads(raw)
    rows = document.get("roles")
    if document.get("schema_version") != 1 or not isinstance(rows, list) or not rows:
        raise ValueError("ROLE_CATALOG_INVALID")
    roles: list[CatalogRole] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ROLE_CATALOG_INVALID")
        code = row.get("code")
        name = row.get("name")
        description = row.get("description")
        phases = row.get("crisp_dm_phases")
        interactions = row.get("interactions")
        if (
            not isinstance(code, str)
            or not CODE_RE.fullmatch(code)
            or code in seen
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not description.strip()
            or not isinstance(phases, list)
            or not phases
            or any(not isinstance(stage, str) or stage not in STAGES for stage in phases)
            or len(set(phases)) != len(phases)
            or not isinstance(interactions, list)
            or not interactions
            or any(not isinstance(item, str) or not item.strip() for item in interactions)
        ):
            raise ValueError("ROLE_CATALOG_INVALID")
        seen.add(code)
        roles.append(CatalogRole(code, name, tuple(phases), description, tuple(interactions)))
    return RoleCatalog(manifest["id"], manifest["version"], digest, tuple(roles))
