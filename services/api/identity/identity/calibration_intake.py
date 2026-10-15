"""Privacy-safe blind review intake for identity confidence evaluation.

The intake deliberately separates resolver metadata from the human annotation
packet. It never derives labels from a runtime action or fixture expectation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .calibration_evaluation import _validate_row

_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TENANT = re.compile(r"^tenant:[A-Za-z0-9_-]{8,128}$")
_REVIEWER = re.compile(r"^reviewer:[A-Za-z0-9_-]{8,128}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(row)
    return rows


def _write_private_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def _case_ref(key: bytes, decision_id: str, pair_ref: str) -> str:
    message = f"identity-calibration-v1\0{decision_id}\0{pair_ref}".encode()
    return "case:" + hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def prepare_review_intake(
    source_path: str | Path,
    output_directory: str | Path,
    *,
    hmac_key: bytes,
) -> dict[str, int]:
    """Create a blinded annotation packet and private join file.

    Input rows must be exported from authorized, non-fixture identity review
    evidence. Only opaque references and score/action metadata are accepted.
    """
    if len(hmac_key) < 32:
        raise ValueError("HMAC key must contain at least 32 bytes")
    source_rows = _read_jsonl(Path(source_path))
    packet: list[dict[str, Any]] = []
    private: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(source_rows, 1):
        required = {
            "decision_id", "pair_ref", "tenant_ref", "score", "runtime_action",
            "source_family", "original_decider_ref", "evidence_origin", "non_fixture",
        }
        if set(row) != required:
            raise ValueError(f"source row {index}: fields must be exactly {sorted(required)}")
        decision_id, pair_ref = row["decision_id"], row["pair_ref"]
        if not isinstance(decision_id, str) or not _OPAQUE.fullmatch(decision_id):
            raise ValueError(f"source row {index}: decision_id must be an opaque reference")
        if not isinstance(pair_ref, str) or not _OPAQUE.fullmatch(pair_ref):
            raise ValueError(f"source row {index}: pair_ref must be an opaque reference")
        if not isinstance(row["tenant_ref"], str) or not _TENANT.fullmatch(row["tenant_ref"]):
            raise ValueError(f"source row {index}: tenant_ref must be pseudonymous")
        if not isinstance(row["original_decider_ref"], str) or not _REVIEWER.fullmatch(row["original_decider_ref"]):
            raise ValueError(f"source row {index}: original_decider_ref must be pseudonymous")
        if not isinstance(row["source_family"], str) or not _SOURCE.fullmatch(row["source_family"]):
            raise ValueError(f"source row {index}: source_family is invalid")
        if row["evidence_origin"] not in {"tenant_identity_review", "operator_identity_review"}:
            raise ValueError(f"source row {index}: evidence_origin must be a real identity review")
        if row["non_fixture"] is not True:
            raise ValueError(f"source row {index}: fixture/synthetic evidence cannot enter calibration intake")
        action = row["runtime_action"]
        score = row["score"]
        if action not in {"merge", "no_merge", "review"}:
            raise ValueError(f"source row {index}: invalid runtime_action")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise ValueError(f"source row {index}: score must be numeric within [0, 1]")
        if decision_id in seen:
            raise ValueError(f"source row {index}: duplicate decision_id")
        seen.add(decision_id)
        case_ref = _case_ref(hmac_key, decision_id, pair_ref)
        packet.append({
            "case_ref": case_ref,
            "pair_ref": pair_ref,
            "source_family": row["source_family"],
            "same_identity": None,
            "adjudicator_ref": None,
            "adjudicated_at": None,
            "independent_review": None,
        })
        private.append({
            "case_ref": case_ref,
            "decision_id": hmac.new(hmac_key, f"decision\0{decision_id}".encode(), hashlib.sha256).hexdigest(),
            "score": float(score),
            "runtime_action": action,
            "tenant_ref": row["tenant_ref"],
            "source_family": row["source_family"],
            "original_decider_ref": row["original_decider_ref"],
            "evidence_origin": row["evidence_origin"],
        })
    out = Path(output_directory)
    out.mkdir(parents=True, exist_ok=True)
    _write_private_jsonl(out / "annotation-packet.jsonl", packet)
    _write_private_jsonl(out / "private-join.jsonl", private)
    return {"prepared_cases": len(packet)}


def assemble_reviewed_labels(
    packet_path: str | Path,
    private_join_path: str | Path,
    annotations_path: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    """Join human-entered annotations to hidden runtime metadata for evaluation."""
    packet_rows = _read_jsonl(Path(packet_path))
    private_rows = _read_jsonl(Path(private_join_path))
    annotation_rows = _read_jsonl(Path(annotations_path))
    indexes: list[dict[str, dict[str, Any]]] = []
    for name, rows in (("packet", packet_rows), ("private join", private_rows), ("annotations", annotation_rows)):
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            case = row.get("case_ref")
            if not isinstance(case, str) or not re.fullmatch(r"case:[0-9a-f]{32}", case):
                raise ValueError(f"{name}: invalid case_ref")
            if case in index:
                raise ValueError(f"{name}: duplicate case_ref")
            index[case] = row
        indexes.append(index)
    packet, private, annotations = indexes
    if not packet or packet.keys() != private.keys() or packet.keys() != annotations.keys():
        raise ValueError("packet, private join, and annotation case sets must match exactly")

    result: list[dict[str, Any]] = []
    for case_ref in sorted(packet):
        annotation = annotations[case_ref]
        metadata = private[case_ref]
        if set(annotation) != {"case_ref", "same_identity", "adjudicator_ref", "adjudicated_at", "independent_review"}:
            raise ValueError(f"annotation {case_ref}: unexpected or missing fields")
        if type(annotation["same_identity"]) is not bool:
            raise ValueError(f"annotation {case_ref}: same_identity must be a human-entered boolean")
        reviewer = annotation["adjudicator_ref"]
        if not isinstance(reviewer, str) or not _REVIEWER.fullmatch(reviewer):
            raise ValueError(f"annotation {case_ref}: adjudicator_ref must be pseudonymous")
        if reviewer == metadata["original_decider_ref"]:
            raise ValueError(f"annotation {case_ref}: adjudicator must be independent of original decision maker")
        timestamp = annotation["adjudicated_at"]
        if not isinstance(timestamp, str):
            raise ValueError(f"annotation {case_ref}: adjudicated_at is required")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"annotation {case_ref}: invalid adjudicated_at") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"annotation {case_ref}: adjudicated_at must include timezone")
        if annotation["independent_review"] is not True:
            raise ValueError(f"annotation {case_ref}: independent_review must be explicitly affirmed")
        row = {
            "decision_id": metadata["decision_id"],
            "score": metadata["score"],
            "same_identity": annotation["same_identity"],
            "runtime_action": metadata["runtime_action"],
            "label_source": "human_review",
            "source_family": metadata["source_family"],
            "tenant_ref": metadata["tenant_ref"],
            "adjudicator_ref": reviewer,
            "adjudicated_at": timestamp,
            "independent_review": True,
        }
        result.append(_validate_row(row))
    _write_private_jsonl(Path(output_path), result)
    return {"assembled_labels": len(result)}
