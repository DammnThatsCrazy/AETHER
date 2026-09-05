from __future__ import annotations

from pathlib import Path

from scripts import validate_frontend_branding as validator


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(tmp_path: Path, relative: str, text: str, *, exceptions=()):
    path = _write(tmp_path / relative, text)
    return validator.scan(root=tmp_path, paths=[path], exceptions=exceptions)


def test_nav_glyphs_and_deprecated_primitive_are_reported_with_lines(tmp_path: Path) -> None:
    findings, applied = _scan(
        tmp_path,
        "frontend/aether/src/components/app-shell.tsx",
        "import { GlyphIcon } from '@aether/ui';\nconst nav = [{ glyph: '[u]' }];\n",
    )

    assert applied == []
    assert {(item["rule"], item["line"]) for item in findings} == {
        ("deprecated-glyph-icon", 1),
        ("deprecated-nav-glyph", 2),
    }


def test_raw_unicode_and_escaped_icon_glyphs_are_limited_to_migrated_nav(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/components/layout/top-bar.tsx",
        "const icon = '\\u2709';\nconst second = '◈';\n",
    )

    assert [item["rule"] for item in findings] == [
        "raw-navigation-glyph",
        "raw-navigation-glyph",
    ]
    assert [item["line"] for item in findings] == [1, 2]


def test_navigation_glyphs_mentioned_in_comments_are_not_runtime_violations(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/components/layout/sidebar.tsx",
        "// Deprecated glyph: ◈ → NavigationIcon\nconst entries = [];\n",
    )

    assert findings == []


def test_legacy_paths_outside_migration_targets_do_not_fail_nav_rule(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether/src/pages/legacy-panel.tsx",
        "const nav = [{ glyph: '◈' }];\n",
    )

    assert findings == []


def test_provider_svg_and_local_map_are_blocked_only_at_migrated_provider_seams(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/features/notifications/channel-type-icon.tsx",
        "const SlackIcon = () => <svg><path d='M0 0' /></svg>;\nconst ICON_MAP = {};\n",
    )

    assert {item["rule"] for item in findings} == {
        "inline-provider-svg",
        "feature-local-provider-map",
    }


def test_provider_renderer_component_name_is_not_mistaken_for_a_local_map(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/features/notifications/channel-type-icon.tsx",
        "export const ChannelTypeIcon = () => <ProviderMark provider=\"slack\" />;\n",
    )

    assert findings == []


def test_new_feature_local_provider_svg_is_detected_without_scanning_unrelated_icons(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether/src/pages/connectors/provider-icon.tsx",
        "const SlackIcon = () => <svg><path d='M0 0' /></svg>;\n",
    )

    assert [item["rule"] for item in findings] == ["inline-provider-svg"]


def test_direct_provider_urls_and_feature_local_canonical_assets_are_rejected(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether/src/pages/connectors/card.tsx",
        """
        const provider = <img src=\"https://cdn.example.com/slack-logo.svg\" />;
        const mark = <img src=\"/assets/logo-aether-layers.svg\" />;
        """,
    )

    assert {item["rule"] for item in findings} == {
        "remote-provider-asset",
        "feature-local-canonical-asset",
    }


def test_analytics_script_endpoints_are_not_flagged_but_remote_google_marks_are(
    tmp_path: Path,
) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether-marketing/src/lib/analytics.ts",
        """
        script.src = `https://www.googletagmanager.com/gtag/js?id=${id}`;
        const mark = <img src=\"https://cdn.example.com/google-mark.svg\" />;
        """,
    )

    assert [item["rule"] for item in findings] == ["remote-provider-asset"]


def test_registry_backed_provider_mark_rejects_unknown_static_id(tmp_path: Path) -> None:
    _write(
        tmp_path / "packages/brand/src/providers/registry.ts",
        "export const providerRegistry = { slack: provider('slack', 'Slack') };\n",
    )
    findings, _ = _scan(
        tmp_path,
        "frontend/aether/src/pages/connectors/card.tsx",
        "export const Card = () => <ProviderMark provider=\"unknown-vendor\" />;\n",
    )

    assert findings == [
        {
            "path": "frontend/aether/src/pages/connectors/card.tsx",
            "line": 1,
            "rule": "unregistered-provider",
            "reason": "ProviderMark references 'unknown-vendor', which is absent from packages/brand/src/providers/registry.ts",
        }
    ]


def test_canonical_mark_geometry_and_fixed_icon_dimensions_are_rejected(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether/src/components/aether-logo.tsx",
        "export const AetherLogo = () => <svg width={16}><path d='M0' fill='#3a6896' /></svg>;\n",
    )

    assert {item["rule"] for item in findings} == {
        "feature-local-canonical-mark",
        "hardcoded-icon-size",
    }


def test_raw_motion_shadow_and_unnamed_icon_only_controls_are_reported(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/components/layout/top-bar.tsx",
        """
        const Button = () => <button><svg /></button>;
        const css = 'transition-duration: 175ms; box-shadow: 0 1px 2px black;';
        """,
    )

    assert {item["rule"] for item in findings} == {
        "icon-only-control-name",
        "raw-motion-literal",
        "raw-shadow-literal",
    }


def test_escaped_unicode_icon_only_control_still_needs_a_name(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/components/layout/top-bar.tsx",
        "const Button = () => <button>{'\\u2709'}</button>;\n",
    )

    assert {item["rule"] for item in findings} == {
        "raw-navigation-glyph",
        "icon-only-control-name",
    }


def test_reduced_motion_baseline_and_deprecated_compatibility_are_allowed(tmp_path: Path) -> None:
    style_findings, _ = _scan(
        tmp_path,
        "frontend/kyber/src/styles/index.css",
        "@media (prefers-reduced-motion: reduce) { * { transition-duration: 0.01ms !important; } }\n",
    )
    glyph_findings, _ = _scan(
        tmp_path,
        "frontend/shared/src/components/glyph-icon.tsx",
        "/** @deprecated Use Icon or NavIcon. */\nexport const GlyphIcon = () => null;\n",
    )

    assert style_findings == []
    assert glyph_findings == []


def test_exact_path_rule_exception_suppresses_only_the_documented_finding(tmp_path: Path) -> None:
    exception = validator.BrandException(
        path="frontend/aether/src/components/app-shell.tsx",
        rule="deprecated-nav-glyph",
        reason="Migration rollout is blocked on a downstream renderer release.",
    )
    findings, applied = _scan(
        tmp_path,
        "frontend/aether/src/components/app-shell.tsx",
        "const nav = [{ glyph: '[u]' }];\n",
        exceptions=(exception,),
    )

    assert findings == []
    assert applied == [exception]


def test_docs_and_tests_are_not_runtime_validator_input(tmp_path: Path) -> None:
    docs = _write(
        tmp_path / "frontend/docs/src/pages/iconography.tsx",
        "const nav = [{ glyph: '◈' }];\n",
    )
    test = _write(
        tmp_path / "frontend/aether/src/test/shell.test.tsx",
        "const nav = [{ glyph: '◈' }];\n",
    )

    findings, _ = validator.scan(root=tmp_path, paths=[docs, test])

    assert findings == []


def test_marketing_pages_enforce_raw_motion_literals(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether-marketing/src/pages/home-page.tsx",
        "const css = 'transition-duration: 300ms';\n",
    )

    assert [(item["rule"], item["line"]) for item in findings] == [
        ("raw-motion-literal", 1),
    ]


def test_marketing_interaction_transition_utilities_are_allowed(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/olympus-marketing/src/components/marketing-section.tsx",
        (
            "const cls = 'transition-colors transition-opacity transition-transform "
            "translate-x-0 hover:translate-x-1 duration-[var(--aether-motion-standard)]';\n"
        ),
    )

    assert findings == []


def test_marketing_reduced_motion_literal_is_exempt(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/aether-marketing/src/styles/index.css",
        "@media (prefers-reduced-motion: reduce) {\n"
        "  *,\n"
        "  *::before,\n"
        "  *::after {\n"
        "    animation-duration: 0.01ms !important;\n"
        "    animation-iteration-count: 1 !important;\n"
        "    transition-duration: 0.01ms !important;\n"
        "    scroll-behavior: auto !important;\n"
        "  }\n"
        "}\n",
    )

    assert findings == []


def test_marketing_decorative_animation_is_reported(tmp_path: Path) -> None:
    findings, _ = _scan(
        tmp_path,
        "frontend/olympus-marketing/src/pages/home-page.css",
        "@keyframes float-in {\n"
        "  from { opacity: 0; }\n"
        "}\n"
        ".hero { animation: float-in 2s ease infinite; will-change: transform; }\n",
    )

    assert {item["rule"] for item in findings} == {"decorative-motion"}
    assert len(findings) == 3
