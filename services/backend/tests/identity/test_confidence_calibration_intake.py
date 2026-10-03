import json

import pytest

from services.identity.calibration_intake import assemble_reviewed_labels, prepare_review_intake
from services.identity.calibration_evaluation import load_reviewed_pairs


def _source_row(index=1):
    return {
        "decision_id": f"decision_{index:08d}",
        "pair_ref": f"pair_ref_{index:08d}",
        "tenant_ref": "tenant:opaque-tenant-0001",
        "score": 0.82,
        "runtime_action": "review",
        "source_family": "commerce",
        "original_decider_ref": "reviewer:original-0001",
        "evidence_origin": "tenant_identity_review",
        "non_fixture": True,
    }


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _prepared(tmp_path, rows=None):
    source = tmp_path / "source.jsonl"
    _write_rows(source, rows or [_source_row()])
    output = tmp_path / "prepared"
    prepare_review_intake(source, output, hmac_key=b"h" * 32)
    packet = output / "annotation-packet.jsonl"
    private = output / "private-join.jsonl"
    packet_rows = [json.loads(line) for line in packet.read_text().splitlines()]
    return packet, private, packet_rows


def test_prepare_blinds_runtime_metadata_and_writes_private_join(tmp_path):
    packet, private, packet_rows = _prepared(tmp_path)
    row = packet_rows[0]
    assert row["same_identity"] is None
    assert row["adjudicator_ref"] is None
    assert "score" not in row and "runtime_action" not in row and "tenant_ref" not in row
    assert row["pair_ref"] == "pair_ref_00000001"
    private_text = private.read_text()
    assert '"score":0.82' in private_text
    assert "decision_00000001" not in private_text
    assert packet.stat().st_mode & 0o777 == 0o600
    assert private.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("overrides, message", [
    ({"non_fixture": False}, "fixture/synthetic"),
    ({"evidence_origin": "fixture"}, "real identity review"),
    ({"pair_ref": "person@example.com"}, "opaque reference"),
])
def test_prepare_rejects_fixtures_and_non_opaque_fields(tmp_path, overrides, message):
    row = {**_source_row(), **overrides}
    source = tmp_path / "source.jsonl"
    _write_rows(source, [row])
    with pytest.raises(ValueError, match=message):
        prepare_review_intake(source, tmp_path / "out", hmac_key=b"h" * 32)


def test_assemble_requires_explicit_independent_human_label_and_emits_evaluator_rows(tmp_path):
    packet, private, rows = _prepared(tmp_path)
    annotations = tmp_path / "annotations.jsonl"
    _write_rows(annotations, [{
        "case_ref": rows[0]["case_ref"],
        "same_identity": True,
        "adjudicator_ref": "reviewer:independent-0001",
        "adjudicated_at": "2026-10-02T12:30:00Z",
        "independent_review": True,
    }])
    output = tmp_path / "labels.jsonl"
    assert assemble_reviewed_labels(packet, private, annotations, output) == {"assembled_labels": 1}
    result = load_reviewed_pairs(output)[0]
    assert result["same_identity"] is True
    assert result["label_source"] == "human_review"
    assert result["decision_id"] != "decision_00000001"
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("annotation, message", [
    ({"same_identity": None, "adjudicator_ref": "reviewer:independent-0001", "adjudicated_at": "2026-10-02T12:30:00Z", "independent_review": True}, "human-entered boolean"),
    ({"same_identity": True, "adjudicator_ref": "reviewer:original-0001", "adjudicated_at": "2026-10-02T12:30:00Z", "independent_review": True}, "independent of original"),
    ({"same_identity": True, "adjudicator_ref": "reviewer:independent-0001", "adjudicated_at": "2026-10-02T12:30:00Z", "independent_review": False}, "explicitly affirmed"),
])
def test_assemble_rejects_unreviewed_nonindependent_or_incomplete_rows(tmp_path, annotation, message):
    packet, private, rows = _prepared(tmp_path)
    annotations = tmp_path / "annotations.jsonl"
    _write_rows(annotations, [{"case_ref": rows[0]["case_ref"], **annotation}])
    with pytest.raises(ValueError, match=message):
        assemble_reviewed_labels(packet, private, annotations, tmp_path / "labels.jsonl")


def test_intake_requires_exact_case_sets_and_strong_hmac_key(tmp_path):
    source = tmp_path / "source.jsonl"
    _write_rows(source, [_source_row()])
    with pytest.raises(ValueError, match="32 bytes"):
        prepare_review_intake(source, tmp_path / "out", hmac_key=b"short")
