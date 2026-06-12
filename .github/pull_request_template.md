## Automated Repo Consistency

This PR must pass the required **Repo Consistency** workflow. The canonical local/cloud-agent commands are:

```bash
make repo-doctor-fix
make ci-check
```

## Documentation Impact

_Describe only what changed:_

- Source behavior changed:
- Authored docs updated:
- Generated docs regenerated:
- Source-linked docs reviewed:
- Docs intentionally unchanged because:

## Repo consistency

- [ ] I ran `make repo-doctor-fix`
- [ ] I ran `make ci-check`
- [ ] I committed regenerated `docs/_generated/` files
- [ ] I committed synced docs: `docs/REPO-INDEX.md`, `docs/AUTOMATION.md`
- [ ] I updated source-linked docs where behavior changed
- [ ] I updated SDK public exports where package APIs changed
- [ ] I ran TypeScript typecheck/build/tests
- [ ] I updated contract/event/consent docs if schemas changed
- [ ] I verified no generated diff remains

## Known Risks

*
