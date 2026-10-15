# Aether Releases

Aether has not reached a public production release. It is a pre-production private alpha.

The canonical version is in [`VERSION`](VERSION) and mirrors `pyproject.toml`, which owns the platform version.

## Release classes

| Class | Meaning |
|---|---|
| `alpha` | Internal or design-partner candidate. APIs and contracts may still change. |
| `beta` | Stabilization candidate with known remaining work. |
| `rc` | Release candidate. Intended to become stable unless blockers appear. |
| `1.0.0` | First public production release. |

No version is described as stable, production, GA, or enterprise-ready until Aether reaches that state.

## Where release information lives

- [`CHANGELOG.md`](CHANGELOG.md)
- [Release policy](docs/operations/releases/release-policy.md)
- [Tag policy](docs/operations/releases/tag-policy.md)
- [Version scheme](docs/operations/releases/version-scheme.md)
- [Retrospective milestones](docs/operations/releases/retrospective-milestones.md)
- [Unreleased changes](docs/operations/releases/unreleased.md)
- [Release truth](docs/reference/source-of-truth/release-truth.md)

## Changing the version

```bash
python scripts/bump_version.py --check
python scripts/bump_version.py <NEW_VERSION>
```
