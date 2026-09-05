#!/usr/bin/env python3
"""Guard canonical frontend brand migration seams without freezing legacy debt.

This validator is deliberately source-only: it does not try to understand all
of TSX or CSS.  Instead, it guards the finite surfaces that have been migrated
to the Olympus/Aether brand contracts.  That makes the rule useful in CI
without incorrectly treating an unrelated legacy feature as a failed migration.

The scanner excludes documentation, generated files, and test/story fixtures.
For a justified temporary exception, pass ``--exception PATH:RULE:REASON``.
Exceptions are exact-path, exact-rule, and require a human-readable reason;
they are reported in both text and JSON output so they do not become invisible
allowlists.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".css"}
TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__", "test-support", "fixtures", "mocks"}
TEST_FILENAME_RE = re.compile(r"\.(?:test|spec|stories)\.(?:[cm]?[jt]sx?)$", re.IGNORECASE)

# These are the only application seams that this change set migrates.  Keep
# this list small and add an entry only with the matching product migration.
# A broad "ban every old icon in the repository" would prevent incremental,
# behavior-preserving work on the rest of Aether and Kyber.
NAVIGATION_TARGETS = frozenset(
    {
        "frontend/aether/src/components/app-shell.tsx",
        "frontend/kyber/src/components/layout/sidebar.tsx",
        "frontend/kyber/src/components/layout/top-bar.tsx",
    }
)
PROVIDER_TARGETS = frozenset(
    {
        "frontend/shared/src/components/social-provider-icon.tsx",
        "frontend/kyber/src/features/notifications/channel-type-icon.tsx",
    }
)
CANONICAL_MARK_TARGETS = frozenset(
    {"frontend/aether/src/components/aether-logo.tsx"}
)
MOTION_SURFACE_ROOTS = (
    "frontend/aether-marketing/src/components/",
    "frontend/aether-marketing/src/pages/",
    "frontend/aether-marketing/src/styles/",
    "frontend/aether/src/components/",
    "frontend/kyber/src/components/layout/",
    "frontend/kyber/src/styles/",
    "frontend/olympus-marketing/src/components/",
    "frontend/olympus-marketing/src/pages/",
    "frontend/olympus-marketing/src/styles/",
    "frontend/shared/src/components/",
)
GLYPH_COMPATIBILITY_PATH = "frontend/shared/src/components/glyph-icon.tsx"

# Navigation icon glyphs documented by the pre-migration audit.  Scanning this
# known set avoids flagging ordinary non-ASCII product copy (for example a
# version separator) while ensuring the actual font-dependent icon seams stay
# gone after the shell migration.
RAW_NAV_GLYPHS = frozenset(
    {
        "◈", "⬡", "⧉", "⚑", "⌁", "◉", "⌘", "✓", "⬢", "⊞", "⇪", "◫",
        "⚒", "◎", "▣", "▤", "◐", "↔", "≈", "⇛", "⇄", "¤", "∴", "⊙",
        "₿", "≋", "▥", "◌", "→", "⛨", "⚙", "⚗", "✉", "←",
    }
)
RAW_NAV_GLYPH_RE = re.compile("[" + re.escape("".join(sorted(RAW_NAV_GLYPHS))) + "]")
RAW_UNICODE_ESCAPE_RE = re.compile(r"\\u(?:[0-9a-fA-F]{4}|\{[0-9a-fA-F]+\})")
GLYPH_PROPERTY_RE = re.compile(r"\bglyph\s*:\s*['\"]")
GLYPH_RENDER_RE = re.compile(r"\bGlyphIcon\b")
COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)

# Provider names are intentionally used only to identify a *direct asset URL*.
# They are not an authority list; runtime IDs continue to come from the brand
# registry and backend/shared contracts.
PROVIDER_URL_TERMS = (
    "google",
    "apple",
    "slack",
    "microsoft",
    "discord",
    "telegram",
    "stripe",
    "coinbase",
    "shopify",
    "hubspot",
    "salesforce",
    "mailchimp",
    "sendgrid",
    "klaviyo",
    "intercom",
    "zendesk",
    "github",
    "gitlab",
    "notion",
    "linear",
    "jira",
)
_PROVIDER_TERM_GROUP = "|".join(PROVIDER_URL_TERMS)
# The tag-manager host is excluded from the provider-term match: the Google
# Tag Manager *script endpoint* (https://www.googletagmanager.com/gtag/js) is
# a network/analytics seam, not a hotlinked provider brand mark, even though
# its hostname contains the "google" provider term.
REMOTE_PROVIDER_URL_RE = re.compile(
    rf"""(?:\b(?:src|href)\s*=\s*\{{?\s*|\b(?:src|href)\s*:\s*)
         [\"'`](?:https?:)?//(?!(?:www\.)?googletagmanager\.com/)
         [^\"'`\s]*(?:{_PROVIDER_TERM_GROUP}|logo)[^\"'`\s]*""",
    re.IGNORECASE | re.VERBOSE,
)
LOCAL_PROVIDER_ASSET_RE = re.compile(
    rf"""(?:\bfrom\s*|\b(?:src|href)\s*=\s*\{{?\s*)[\"'](?!https?:|//)[^\"']*
         (?:{_PROVIDER_TERM_GROUP})[^\"']*\.(?:svg|png|jpe?g|webp)""",
    re.IGNORECASE | re.VERBOSE,
)
CANONICAL_BRAND_ASSET_RE = re.compile(
    r"[\"'][^\"']*(?:logo-(?:aether|olympus)|lockup-(?:aether|olympus|combined)|favicon-aether)[^\"']*\.(?:svg|png|webp)",
    re.IGNORECASE,
)
INLINE_PROVIDER_SVG_RE = re.compile(r"<(?:svg|path)\b", re.IGNORECASE)
PROVIDER_PATH_MAP_RE = re.compile(
    r"\b(?:paths|path_?map|icon_?map|color_?map)\s*(?::[^=]+)?=\s*(?:\{|\()",
    re.IGNORECASE,
)
# This catches a newly introduced `SlackIcon = () => <svg ...>` outside the
# two legacy seams above.  It intentionally requires a known provider-like
# identifier *and* SVG markup, so normal product/action icons remain outside
# this conservative static rule.
_PROVIDER_COMPONENT_GROUP = "|".join(term.title().replace("_", "") for term in PROVIDER_URL_TERMS)
NAMED_INLINE_PROVIDER_SVG_RE = re.compile(
    rf"\b(?:{_PROVIDER_COMPONENT_GROUP})(?:Icon|Logo|Mark)?\b.{{0,320}}?<(?:svg|path)\b",
    re.IGNORECASE | re.DOTALL,
)
CANONICAL_MARK_COMPONENT_RE = re.compile(
    r"\b(?:Aether|Olympus)(?:Logo|Layers|Mark|Lockup)\b.{0,320}?<(?:svg|path)\b",
    re.IGNORECASE | re.DOTALL,
)

FIXED_ICON_DIMENSION_RE = re.compile(
    r"<(?:svg|img)\b[^>]*\b(?:width|height)\s*=\s*(?:\{\s*)?[\"']?\d+(?:px)?",
    re.IGNORECASE,
)
FIXED_ICON_STYLE_RE = re.compile(
    r"\b(?:width|height)\s*:\s*[\"']?\d+(?:px)?[\"']?",
)
RAW_MOTION_RE = re.compile(
    r"\b(?:transition-duration|animation-duration)\s*:\s*(?!var\()[0-9.]+(?:ms|s)\b",
    re.IGNORECASE,
)
RAW_TAILWIND_DURATION_RE = re.compile(r"\bduration-(?:\[)?\d+(?:ms|s)?\]?\b")
RAW_SHADOW_RE = re.compile(r"\bbox-shadow\s*:\s*(?!var\()[^;]+", re.IGNORECASE)
RAW_TAILWIND_SHADOW_RE = re.compile(r"\bshadow-\[[^\]]+\]")
REDUCED_MOTION_LITERAL_RE = re.compile(r"0\.01ms\s*!important")

# Continuous decorative motion is not a canonical brand recipe.  These patterns
# guard the seams that introduce it on migrated motion surfaces: bespoke
# keyframes, `will-change` layer promotion, and raw `animate-*` utilities or
# `animation:` shorthands.  They deliberately do not touch interaction motion
# (`transition-colors`, `transition-transform`, `transition-opacity`,
# `translate-x-*` transform utilities) or token-bound durations
# (`duration-[var(--aether-motion-*)]`), which the raw-motion rules above also
# leave alone.
DECORATIVE_KEYFRAMES_RE = re.compile(r"@keyframes\s+[a-zA-Z0-9_-]+")
DECORATIVE_WILL_CHANGE_RE = re.compile(r"\bwill-change\s*:|\bwillChange\s*:")
DECORATIVE_ANIMATE_UTILITY_RE = re.compile(
    r"\banimate-(?:[a-zA-Z0-9_-]+|\[[^\]]*\])"
)
DECORATIVE_ANIMATION_SHORTHAND_RE = re.compile(r"(?<![\w-])animation\s*:")
DECORATIVE_ANIMATION_NONE_RE = re.compile(r"animation\s*:\s*none\b", re.IGNORECASE)

PROVIDER_MARK_PROP_RE = re.compile(
    r"<ProviderMark\b[^>]*\b(?:provider|providerId)\s*=\s*[\"'](?P<provider>[a-z0-9_-]+)[\"']",
)
REGISTRY_PROVIDER_RE = re.compile(r"\bprovider\(\s*['\"](?P<provider>[a-z0-9_-]+)['\"]")
BUTTON_RE = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<body>.*?)</button\s*>", re.DOTALL | re.IGNORECASE)
ICON_ONLY_BUTTON_RE = re.compile(
    r"<(?:svg|(?:[A-Z][A-Za-z0-9]*(?:Icon|Mark)))\b|\\u(?:[0-9a-fA-F]{4}|\{[0-9a-fA-F]+\})"
)
ACCESSIBLE_BUTTON_RE = re.compile(r"\baria-(?:label|labelledby)\s*=|\btitle\s*=|\bsr-only\b")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class BrandException:
    """An auditable temporary exception to exactly one rule in exactly one file."""

    path: str
    rule: str
    reason: str


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "reason": self.reason,
        }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(path: Path, text: str, offset: int, rule: str, reason: str, root: Path) -> Finding:
    return Finding(_relative(path, root), _line_number(text, offset), rule, reason)


def is_runtime_path(path: Path, root: Path = ROOT) -> bool:
    """Return whether a file is production frontend source rather than test/docs output."""
    if path.suffix not in SOURCE_SUFFIXES:
        return False
    rel = _relative(path, root)
    parts = Path(rel).parts
    if not parts or parts[0] != "frontend" or "src" not in parts:
        return False
    if "docs" in parts or "generated" in parts:
        return False
    return not (
        any(part in TEST_DIRECTORY_NAMES for part in parts)
        or TEST_FILENAME_RE.search(path.name) is not None
    )


def _runtime_files(root: Path) -> Iterable[Path]:
    frontend = root / "frontend"
    if not frontend.exists():
        return ()
    return (
        path
        for path in sorted(frontend.rglob("*"))
        if path.is_file() and is_runtime_path(path, root)
    )


def _is_motion_surface(rel: str) -> bool:
    return rel.startswith(MOTION_SURFACE_ROOTS)


def _is_approved_exception(
    finding: Finding, exceptions: Iterable[BrandException]
) -> bool:
    return any(
        exception.path == finding.path and exception.rule == finding.rule
        for exception in exceptions
    )


def _registered_provider_ids(root: Path) -> set[str]:
    """Read IDs from the visual registry without making it a validator input API."""
    registry = root / "packages/brand/src/providers/registry.ts"
    if not registry.exists():
        return set()
    return set(REGISTRY_PROVIDER_RE.findall(registry.read_text(encoding="utf-8")))


def _without_comments(text: str) -> str:
    """Mask comments without changing offsets, so findings retain real line numbers."""
    return COMMENT_RE.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)


def _scan_navigation(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if rel not in NAVIGATION_TARGETS:
        return findings
    code = _without_comments(text)

    for match in GLYPH_PROPERTY_RE.finditer(code):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "deprecated-nav-glyph",
                "navigation entries must use a canonical icon destination, not a glyph string",
                root,
            )
        )
    for match in GLYPH_RENDER_RE.finditer(code):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "deprecated-glyph-icon",
                "migrated navigation must render the shared semantic Icon/NavIcon, not GlyphIcon",
                root,
            )
        )
    for match in RAW_NAV_GLYPH_RE.finditer(code):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "raw-navigation-glyph",
                "raw Unicode navigation glyphs are font-dependent; use a canonical semantic icon",
                root,
            )
        )
    for match in RAW_UNICODE_ESCAPE_RE.finditer(code):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "raw-navigation-glyph",
                "escaped Unicode icon glyphs are not a semantic navigation icon contract",
                root,
            )
        )
    return findings


def _scan_provider_targets(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if rel not in PROVIDER_TARGETS:
        return findings
    for match in INLINE_PROVIDER_SVG_RE.finditer(text):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "inline-provider-svg",
                "provider marks must render through the approved shared ProviderMark renderer",
                root,
            )
        )
        break
    for match in PROVIDER_PATH_MAP_RE.finditer(text):
        findings.append(
            _finding(
                path,
                text,
                match.start(),
                "feature-local-provider-map",
                "provider paths and brand-color maps belong in the @olympus/brand registry, not a feature",
                root,
            )
        )
        break
    return findings


def _scan_canonical_mark(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    if rel not in CANONICAL_MARK_TARGETS:
        return []
    # A multi-path SVG or hard-coded brand palette in this compatibility file
    # means the Aether mark is still owned by the app instead of the package.
    match = re.search(r"<(?:svg|path)\b|#[0-9a-fA-F]{3,8}\b", text)
    if match is None:
        return []
    return [
        _finding(
            path,
            text,
            match.start(),
            "feature-local-canonical-mark",
            "Aether/Olympus mark geometry and palette must come from the shared brand renderer",
            root,
        )
    ]


def _scan_assets_and_registry(
    path: Path,
    text: str,
    rel: str,
    root: Path,
    registered_provider_ids: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for pattern, rule, reason in (
        (
            REMOTE_PROVIDER_URL_RE,
            "remote-provider-asset",
            "provider marks must be approved local assets or the neutral registry fallback; remote logo URLs are not allowed",
        ),
        (
            LOCAL_PROVIDER_ASSET_RE,
            "feature-local-provider-asset",
            "provider assets must be referenced through ProviderMark and the canonical provider registry",
        ),
        (
            CANONICAL_BRAND_ASSET_RE,
            "feature-local-canonical-asset",
            "Aether/Olympus canonical assets must be resolved by the shared brand renderer, not an application feature",
        ),
    ):
        for match in pattern.finditer(text):
            findings.append(_finding(path, text, match.start(), rule, reason, root))

    if rel not in PROVIDER_TARGETS:
        match = NAMED_INLINE_PROVIDER_SVG_RE.search(text)
        if match:
            findings.append(
                _finding(
                    path,
                    text,
                    match.start(),
                    "inline-provider-svg",
                    "provider SVG geometry belongs only in the approved shared ProviderMark renderer",
                    root,
                )
            )
    if rel not in CANONICAL_MARK_TARGETS:
        match = CANONICAL_MARK_COMPONENT_RE.search(text)
        if match:
            findings.append(
                _finding(
                    path,
                    text,
                    match.start(),
                    "feature-local-canonical-mark",
                    "Aether/Olympus mark geometry must be supplied by the shared brand renderer",
                    root,
                )
            )

    if registered_provider_ids:
        for match in PROVIDER_MARK_PROP_RE.finditer(text):
            provider_id = match.group("provider")
            if provider_id not in registered_provider_ids:
                findings.append(
                    _finding(
                        path,
                        text,
                        match.start(),
                        "unregistered-provider",
                        f"ProviderMark references {provider_id!r}, which is absent from packages/brand/src/providers/registry.ts",
                        root,
                    )
                )
    return findings


def _scan_size_motion_and_shadow(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if rel in NAVIGATION_TARGETS or rel in PROVIDER_TARGETS or rel in CANONICAL_MARK_TARGETS:
        for pattern in (FIXED_ICON_DIMENSION_RE, FIXED_ICON_STYLE_RE):
            match = pattern.search(text)
            if match:
                findings.append(
                    _finding(
                        path,
                        text,
                        match.start(),
                        "hardcoded-icon-size",
                        "icon dimensions must use the canonical icon-size contract rather than a fixed pixel literal",
                        root,
                    )
                )
                break

    if not _is_motion_surface(rel):
        return findings
    for pattern, rule, reason in (
        (
            RAW_MOTION_RE,
            "raw-motion-literal",
            "use the canonical motion duration/easing recipe rather than a raw duration literal",
        ),
        (
            RAW_TAILWIND_DURATION_RE,
            "raw-motion-literal",
            "use a semantic motion recipe rather than an arbitrary Tailwind duration utility",
        ),
        (
            RAW_SHADOW_RE,
            "raw-shadow-literal",
            "use the canonical elevation/shadow recipe rather than a raw box-shadow value",
        ),
        (
            RAW_TAILWIND_SHADOW_RE,
            "raw-shadow-literal",
            "use a semantic elevation recipe rather than an arbitrary Tailwind shadow value",
        ),
    ):
        for match in pattern.finditer(text):
            # The tiny duration in the standard reduced-motion media rule is a
            # recognized accessibility technique, not a brand-motion value.
            line = text[text.rfind("\n", 0, match.start()) + 1 : text.find("\n", match.start()) if "\n" in text[match.start():] else len(text)]
            if rule == "raw-motion-literal" and REDUCED_MOTION_LITERAL_RE.search(line):
                continue
            findings.append(_finding(path, text, match.start(), rule, reason, root))
    return findings


def _scan_decorative_motion(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    """Flag seams that introduce continuous decorative motion on migrated surfaces."""
    if not _is_motion_surface(rel):
        return []
    findings: list[Finding] = []
    code = _without_comments(text)
    for pattern, reason in (
        (
            DECORATIVE_KEYFRAMES_RE,
            "raw @keyframes are not a shared reduced-motion-aware recipe; use the canonical motion recipes or a tokenized utility",
        ),
        (
            DECORATIVE_WILL_CHANGE_RE,
            "will-change promotes ad-hoc animation layers; rely on the canonical motion recipes instead",
        ),
        (
            DECORATIVE_ANIMATE_UTILITY_RE,
            "raw animate-* utilities are not shared reduced-motion-aware recipes",
        ),
        (
            DECORATIVE_ANIMATION_SHORTHAND_RE,
            "raw animation: shorthand is not a shared reduced-motion-aware recipe",
        ),
    ):
        for match in pattern.finditer(code):
            line_start = code.rfind("\n", 0, match.start()) + 1
            line_end = code.find("\n", match.start())
            if line_end == -1:
                line_end = len(code)
            line = code[line_start:line_end]
            # Reduced-motion media literals and `animation: none` (disabling
            # motion) are accessibility techniques, not decorative animation,
            # and stay exempt.
            if REDUCED_MOTION_LITERAL_RE.search(line):
                continue
            if (
                pattern is DECORATIVE_ANIMATION_SHORTHAND_RE
                and DECORATIVE_ANIMATION_NONE_RE.search(line)
            ):
                continue
            findings.append(
                _finding(path, text, match.start(), "decorative-motion", reason, root)
            )
    return findings


def _scan_icon_only_controls(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    if rel not in NAVIGATION_TARGETS:
        return []
    findings: list[Finding] = []
    for match in BUTTON_RE.finditer(text):
        attrs = match.group("attrs")
        body = match.group("body")
        visible = RAW_UNICODE_ESCAPE_RE.sub("", TAG_RE.sub("", body))
        is_icon_only = bool(ICON_ONLY_BUTTON_RE.search(body)) and not re.search(r"[A-Za-z0-9]", visible)
        if is_icon_only and not ACCESSIBLE_BUTTON_RE.search(attrs + body):
            findings.append(
                _finding(
                    path,
                    text,
                    match.start(),
                    "icon-only-control-name",
                    "icon-only buttons require aria-label, aria-labelledby, title, or visually hidden text",
                    root,
                )
            )
    return findings


def _scan_glyph_compatibility(path: Path, text: str, rel: str, root: Path) -> list[Finding]:
    if rel != GLYPH_COMPATIBILITY_PATH:
        return []
    if "@deprecated" in text:
        return []
    return [
        _finding(
            path,
            text,
            0,
            "glyph-compatibility-undocumented",
            "GlyphIcon may remain only as a documented deprecated compatibility adapter during migration",
            root,
        )
    ]


def scan(
    *,
    root: Path = ROOT,
    paths: Iterable[Path] | None = None,
    exceptions: Iterable[BrandException] = (),
) -> tuple[list[dict[str, object]], list[BrandException]]:
    """Return active findings and the explicitly applied exceptions.

    ``paths`` exists for focused unit tests and local diagnosis.  The default
    walks production frontend source, but the high-signal migration rules still
    run only on the target lists declared above.
    """
    exception_list = tuple(exceptions)
    registered_provider_ids = _registered_provider_ids(root)
    findings: list[Finding] = []
    applied: list[BrandException] = []
    seen_applied: set[BrandException] = set()

    candidates = paths if paths is not None else _runtime_files(root)
    for path in candidates:
        if not path.exists() or not is_runtime_path(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = _relative(path, root)
        file_findings = [
            *_scan_navigation(path, text, rel, root),
            *_scan_provider_targets(path, text, rel, root),
            *_scan_canonical_mark(path, text, rel, root),
            *_scan_assets_and_registry(path, text, rel, root, registered_provider_ids),
            *_scan_size_motion_and_shadow(path, text, rel, root),
            *_scan_decorative_motion(path, text, rel, root),
            *_scan_icon_only_controls(path, text, rel, root),
            *_scan_glyph_compatibility(path, text, rel, root),
        ]
        for finding in file_findings:
            matching = [
                exception
                for exception in exception_list
                if _is_approved_exception(finding, (exception,))
            ]
            if matching:
                for exception in matching:
                    if exception not in seen_applied:
                        applied.append(exception)
                        seen_applied.add(exception)
                continue
            findings.append(finding)
    findings.sort(key=lambda finding: (finding.path, finding.line, finding.rule, finding.reason))
    return [finding.as_dict() for finding in findings], applied


def _parse_exception(value: str) -> BrandException:
    try:
        path, rule, reason = value.split(":", 2)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "exceptions must be PATH:RULE:REASON (the reason must not be empty)"
        ) from error
    if not path or not rule or not reason.strip():
        raise argparse.ArgumentTypeError(
            "exceptions must include a non-empty path, rule, and reason"
        )
    return BrandException(path=path, rule=rule, reason=reason.strip())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate only the frontend brand seams migrated to the canonical Olympus/Aether contracts.",
        epilog=(
            "Test, story, generated, and documentation files are ignored. "
            "Temporary exceptions are exact PATH:RULE:REASON entries and are printed so reviewers can remove them."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings and applied exceptions")
    parser.add_argument(
        "--exception",
        action="append",
        default=[],
        type=_parse_exception,
        metavar="PATH:RULE:REASON",
        help="allow one documented temporary exception; may be passed more than once",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    findings, applied = scan(exceptions=args.exception)
    if args.json:
        print(
            json.dumps(
                {
                    "findings": findings,
                    "applied_exceptions": [
                        {"path": item.path, "rule": item.rule, "reason": item.reason}
                        for item in applied
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for finding in findings:
            print(
                f"frontend-branding: {finding['path']}:{finding['line']}: "
                f"[{finding['rule']}] {finding['reason']}",
                file=sys.stderr,
            )
        for exception in applied:
            print(
                "frontend-branding: allowed "
                f"{exception.path} [{exception.rule}] — {exception.reason}",
                file=sys.stderr,
            )
        if not findings:
            print(
                "frontend-branding: pass "
                f"(0 migration violations, {len(applied)} documented exception(s) applied)."
            )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
