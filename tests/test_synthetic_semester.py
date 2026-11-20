import pytest

from tests.synthetic_semester import evaluate_bot_readback, evaluate_topology, load_package


def _scenario(package, scenario_id):
    return next(item for item in package["scenarios"]["scenarios"] if item["id"] == scenario_id)


def _observed(scenario, *, first_as=True):
    return {
        "assignments": [
            {
                "assignment_ref": item["ref"],
                "profile_assignment_ref": item["ref"],
                "cycle_assignment_ref": item["ref"],
                "progress_assignment_ref": item["ref"],
            }
            for item in scenario["assignments"]
        ],
        "first_as_presented": first_as,
    }


def test_package_preserves_fixed_roles_and_two_initial_scenarios():
    package = load_package()
    assert {role["code"] for role in package["roles"]["roles"]} == {
        "business_analyst", "data_researcher", "data_engineer", "ml_engineer", "validator"
    }
    assert {item["id"] for item in package["scenarios"]["scenarios"]} == {
        "single-role-first-case", "multi-project-multi-role-isolation"
    }


@pytest.mark.parametrize("scenario_id", [
    "single-role-first-case", "multi-project-multi-role-isolation",
])
def test_topology_evaluator_accepts_isolated_synthetic_observation(scenario_id):
    package = load_package()
    scenario = _scenario(package, scenario_id)
    assert evaluate_topology(scenario, _observed(scenario))["status"] == "passed"


def test_topology_evaluator_rejects_cross_assignment_profile():
    package = load_package()
    scenario = _scenario(package, "multi-project-multi-role-isolation")
    observed = _observed(scenario)
    observed["assignments"][1]["profile_assignment_ref"] = observed["assignments"][0][
        "assignment_ref"
    ]
    result = evaluate_topology(scenario, observed)
    assert result["status"] == "failed"
    assert result["checks"]["profile_scope_isolated"] is False


def test_bot_readback_evaluator_rejects_duplicate_assignment_reference():
    package = load_package()
    scenario = _scenario(package, "multi-project-multi-role-isolation")
    observed = {
        "assignments": [
            {
                "fixture_assignment_ref": item["ref"],
                "assignment_ref": "edu:" + item["ref"],
                "project_ref": item["project_ref"],
                "participant_ref": item["participant_ref"],
                "role_code": item["role_code"],
            }
            for item in scenario["assignments"]
        ]
    }
    observed["assignments"][1]["assignment_ref"] = observed["assignments"][0]["assignment_ref"]
    result = evaluate_bot_readback(scenario, observed)
    assert result["status"] == "failed"
    assert result["checks"]["assignment_refs_unique"] is False
