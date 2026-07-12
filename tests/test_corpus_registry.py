import copy
import hashlib

import pytest

from tools.corpus_registry import (
    GENESIS_HASH,
    build_access_record,
    registry_fingerprint,
    validate_access_log,
    validate_registry,
    visible_identities,
)


def registry():
    value = {
        "schema_version": 1,
        "registry_version": "corpus-registry-v1",
        "status": "sealed",
        "custodian_id": "custodian-1",
        "development_executor_ids": ["executor-1"],
        "frozen": {
            "candidate_commit": "a" * 40,
            "candidate_config_hash": "b" * 64,
            "routing_epoch": "routing-v1",
            "prompt_epoch": "prompt-v1",
            "reader_epoch": "reader-v1",
            "grader_epoch": "grader-v1",
            "evaluator_version": "v1",
            "exclusions": ["mechanical:unreadable-placeholder"],
            "supported_classes": ["targeted", "coverage"],
            "supported_environments": ["macos-arm64-python-3.14"],
            "minimum_confirmatory_families": 5,
            "minimum_confirmatory_families_by_class": {"targeted": 3, "coverage": 3},
        },
        "families": [
            {"family_id": "dev-family-1", "split": "development", "question_classes": ["targeted"],
             "identities": [{"identity_id": "dev-source-001", "identity_sha256": "1" * 64}]},
            {"family_id": "dev-family-2", "split": "development", "question_classes": ["coverage"],
             "identities": [{"identity_id": "dev-source-002", "identity_sha256": "2" * 64}]},
            *[
                {"family_id": f"confirm-family-{index}", "split": "confirmatory",
                 "question_classes": ["targeted", "coverage"],
                 "identities": [{"identity_id": f"reserve-source-{index:03}",
                                 "identity_sha256": hashlib.sha256(f"placeholder-{index}".encode()).hexdigest()}]}
                for index in range(1, 6)
            ],
        ],
    }
    value["seal_sha256"] = registry_fingerprint(value)
    return value


def test_registry_seals_families_without_real_source_locator():
    value = registry()
    assert validate_registry(value) == []
    assert visible_identities(value, actor_id="executor-1") == ["dev-source-001", "dev-source-002"]
    with pytest.raises(PermissionError, match="confirmatory"):
        visible_identities(value, actor_id="executor-1", split="confirmatory")


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value["families"][2].update(split="development"), "seal_sha256"),
    (lambda value: value["families"][2].update(family_id="dev-family-1"), "duplicate family"),
    (lambda value: value["families"][1]["identities"][0].update(identity_sha256="1" * 64), "duplicate identity"),
    (lambda value: value["families"][0].update(source_url="forbidden-locator"), "every family"),
    (lambda value: value["families"][0]["identities"][0].update(private_media="forbidden"), "identity must"),
    (lambda value: value["families"][0]["identities"][0].update(note="https" + "://reserve.invalid/item"), "identity must"),
    (lambda value: value["families"][0]["identities"][0].update(note="/" + "private/source.mp4"), "identity must"),
    (lambda value: value["families"][0]["identities"][0].update(note="caption secret payload"), "identity must"),
    (lambda value: value["frozen"].update(candidate_commit="A" * 40), "lowercase sha40"),
    (lambda value: value["frozen"].update(exclusions=["outcome:bad-result"]), "exclusions must"),
    (lambda value: value["frozen"].update(minimum_confirmatory_families=4), "at least 5"),
])
def test_registry_rejects_leakage_aliases_locators_outcomes_and_underpower(mutation, expected):
    value = registry()
    mutation(value)
    assert any(expected in error for error in validate_registry(value))


@pytest.mark.parametrize("identity_id", ["reserve.example", "../reserve", "reserve.mp4", "reserve/source", "reserve\\source", "reserve?x", "reserve#x"])
def test_registry_allowlist_rejects_locator_shaped_opaque_identity_exploits(identity_id):
    value = registry()
    value["families"][0]["identities"][0]["identity_id"] = identity_id
    assert any("identity_id must be an opaque label" in error for error in validate_registry(value))


def test_hash_chained_access_log_distinguishes_opening_exposure_and_spend():
    value = registry()
    opening = build_access_record(value, [], actor_id="custodian-1", action="authorized_open",
                                  identity_ids=["reserve-source-001"], authorization_id="P29-owner")
    assert validate_access_log(value, [opening]) == []
    exposure = build_access_record(value, [opening], actor_id="custodian-1", action="exposure",
                                   identity_ids=["reserve-source-001"], authorization_id="P31-run")
    assert validate_access_log(value, [opening, exposure]) == []
    reuse = build_access_record(value, [opening, exposure], actor_id="custodian-1", action="authorized_open",
                                identity_ids=["reserve-source-002"], authorization_id="retry")
    assert any("spent cohort" in error for error in validate_access_log(value, [opening, exposure, reuse]))

    tampered = copy.deepcopy(opening)
    tampered["identity_ids"] = ["reserve-source-002"]
    assert any("record_hash" in error for error in validate_access_log(value, [tampered]))


def test_access_rejects_unlogged_executor_stale_epoch_and_bad_chain():
    value = registry()
    record = build_access_record(value, [], actor_id="custodian-1", action="authorized_open",
                                 identity_ids=["reserve-source-001"], authorization_id="P29-owner")
    executor = copy.deepcopy(record)
    executor["actor_id"] = "executor-1"
    executor["record_hash"] = ""
    assert any("custodian" in error for error in validate_access_log(value, [executor]))

    stale = copy.deepcopy(record)
    stale["frozen_epochs_sha256"] = GENESIS_HASH
    stale["record_hash"] = ""
    assert any("stale frozen epochs" in error for error in validate_access_log(value, [stale]))

    broken = copy.deepcopy(record)
    broken["previous_hash"] = "f" * 64
    broken["record_hash"] = ""
    assert any("previous_hash" in error for error in validate_access_log(value, [broken]))
