"""
Static CI guard for A6 reward enablement docs.

Checks:
- All 5 source-of-truth reward docs exist and have required frontmatter
- No forbidden no-custody language in any of those docs
- No forbidden language in the core backend routes
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

SOT_DOCS = [
    "docs/source-of-truth/REWARD_ENABLEMENT.md",
    "docs/source-of-truth/REWARD_RAILS.md",
    "docs/source-of-truth/REWARD_POLICY_ENGINE.md",
    "docs/source-of-truth/REWARD_PROOFS.md",
    "docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md",
]

FORBIDDEN_PHRASES = [
    "Aether distributes rewards",
    "Aether pays users",
    "Aether sends rewards",
    "Aether holds campaign reward funds",
    "Aether reward wallet",
    "Aether executes tenant payouts",
]


def test_all_sot_reward_docs_exist():
    for rel in SOT_DOCS:
        p = ROOT / rel
        assert p.exists(), f"Required source-of-truth doc missing: {rel}"


def test_all_sot_reward_docs_have_content():
    for rel in SOT_DOCS:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8").strip()
        assert text, f"{rel} is empty"
        assert text[0] == "#" or text.startswith("---"), (
            f"{rel} should start with a Markdown heading or YAML frontmatter"
        )


def test_sot_reward_docs_no_forbidden_language():
    # REWARD_NO_CUSTODY_MODEL.md explicitly documents forbidden phrases as anti-patterns;
    # skip it here and check all other reward docs instead.
    skip = {"docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md"}
    for rel in SOT_DOCS:
        if rel in skip:
            continue
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, (
                f"Forbidden no-custody language found in {rel}: {phrase!r}"
            )


def test_reward_routes_no_forbidden_language():
    routes_path = (
        ROOT / "Backend Architecture" / "aether-backend" / "services" / "rewards" / "routes.py"
    )
    if not routes_path.exists():
        return
    text = routes_path.read_text(encoding="utf-8")
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, (
            f"Forbidden no-custody language found in routes.py: {phrase!r}"
        )


def test_productization_checklist_has_a6_section():
    checklist = ROOT / "docs" / "PRODUCTIZATION-CHECKLIST.md"
    assert checklist.exists(), "docs/PRODUCTIZATION-CHECKLIST.md missing"
    text = checklist.read_text(encoding="utf-8")
    assert "Reward Enablement" in text, (
        "docs/PRODUCTIZATION-CHECKLIST.md missing Reward Enablement (A6) section"
    )
