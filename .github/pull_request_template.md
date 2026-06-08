## Automated Repo Consistency

This PR must pass the required **Repo Consistency** workflow.

The workflow enforces:

- version alignment
- generated docs freshness
- docs sync freshness
- docs frontmatter validity
- docs drift (strict mode)
- contract / event / consent validation
- SDK release alignment
- package / test validation

## Documentation Impact

_Describe only what changed:_

- Source behavior changed:
- Authored docs updated:
- Generated docs regenerated:
- Source-linked docs reviewed:
- Docs intentionally unchanged because:

## Validation

Required validation is automated through:

```bash
make repo-doctor
```

Paste local/cloud validation output only if a check failed or needed special handling.

## Known Risks

*
