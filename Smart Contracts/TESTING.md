# Smart Contracts Testing Notes

## Current Environment Limitation

Running the contract suite with:

```bash
npm --prefix 'Smart Contracts' test
```

is currently blocked in this environment because Hardhat cannot download Solidity compiler metadata/binaries:

- Error: `HH502: Couldn't download compiler version list`
- Underlying cause: proxy tunnel returns HTTP `403` during compiler fetch.

This means test results cannot be claimed as passing from this environment until compiler download access is restored or a local/offline compiler mirror is configured.

## Release Checklist Requirement

Before release, execute the full test suite in a build environment that can resolve and download solc `0.8.20` (or provide an approved offline compiler source), and archive the successful test output.
