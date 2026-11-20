from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).parent / "fixtures" / "synthetic_semester" / "v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_package() -> dict[str, Any]:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("id") != "synthetic-semester"
        or manifest.get("version") != "1.0"
        or manifest.get("status") != "qa_only"
        or not isinstance(manifest.get("artifacts"), list)
    ):
        raise ValueError("SYNTHETIC_SEMESTER_MANIFEST_INVALID")
    for artifact in manifest["artifacts"]:
        path = PACKAGE / artifact["name"]
        if not path.is_file() or sha256(path) != artifact["sha256"]:
            raise ValueError("SYNTHETIC_SEMESTER_CHECKSUM_INVALID")
    roles = json.loads((PACKAGE / "roles.json").read_text(encoding="utf-8"))
    scenarios = json.loads((PACKAGE / "scenarios.json").read_text(encoding="utf-8"))
    role_codes = {role["code"] for role in roles["roles"]}
    if len(role_codes) != 5 or any(
        assignment["role_code"] not in role_codes
        for scenario in scenarios["scenarios"]
        for assignment in scenario["assignments"]
    ):
        raise ValueError("SYNTHETIC_SEMESTER_ROLE_REFERENCE_INVALID")
    return {"manifest": manifest, "roles": roles, "scenarios": scenarios}


def evaluate_topology(scenario: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected = {item["ref"] for item in scenario["assignments"]}
    assignments = list(observed.get("assignments") or [])
    actual = {str(item.get("assignment_ref")) for item in assignments}
    checks = {
        "assignment_refs_match": actual == expected and len(actual) == len(assignments),
        "profile_scope_isolated": all(
            item.get("profile_assignment_ref") == item.get("assignment_ref") for item in assignments
        ),
        "cycle_scope_isolated": all(
            item.get("cycle_assignment_ref") == item.get("assignment_ref") for item in assignments
        ),
        "progress_scope_isolated": all(
            item.get("progress_assignment_ref") == item.get("assignment_ref")
            for item in assignments
        ),
        "forbidden_identity_absent": not any(
            key in json.dumps(observed, ensure_ascii=False).lower()
            for key in ("telegram_user_id", "recipient_email", "@synthetic")
        ),
    }
    if scenario["id"] == "single-role-first-case":
        checks["first_as_reached"] = bool(observed.get("first_as_presented"))
        checks["one_assignment"] = len(assignments) == 1
    return {
        "scenario_id": scenario["id"],
        "fixture_version": "synthetic-semester/1.0",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "methodology_approval": False,
        "real_participants": False,
    }


def evaluate_bot_readback(scenario: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected = {
        (item["ref"], item["project_ref"], item["participant_ref"], item["role_code"])
        for item in scenario["assignments"]
    }
    rows = list(observed.get("assignments") or [])
    actual = {
        (
            str(item.get("fixture_assignment_ref")),
            str(item.get("project_ref")),
            str(item.get("participant_ref")),
            str(item.get("role_code")),
        )
        for item in rows
    }
    refs = [str(item.get("assignment_ref")) for item in rows]
    checks = {
        "assignment_topology_matches": actual == expected,
        "assignment_refs_unique": len(refs) == len(set(refs)) == len(expected),
        "single_participant": {item.get("participant_ref") for item in rows} == {"student-01"},
        "forbidden_identity_absent": not any(
            key in json.dumps(observed, ensure_ascii=False).lower()
            for key in ("telegram_user_id", "recipient_email", "@synthetic")
        ),
    }
    return {
        "scenario_id": scenario["id"],
        "fixture_version": "synthetic-semester/1.0",
        "stage": "telegram_postgresql_readback",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "methodology_approval": False,
        "real_participants": False,
    }
