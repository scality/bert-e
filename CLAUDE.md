# bert-e — Claude Code notes

## Running tests

pytest is at `.venv/bin/pytest` (not in system PATH):

```sh
.venv/bin/pytest
```

## Creating a GitHub release

`gh release create` requires the **full** commit SHA for `--target` — short SHAs are rejected with HTTP 422. Always resolve the full SHA first:

```sh
FULL_SHA=$(git rev-parse origin/main)
gh release create <tag> --target "$FULL_SHA" --prerelease --generate-notes --title "<tag>"
```

Follow the checklist in `devdocs/docs/tools/bert-e/release.md` for the full release process (tag naming, pre-release flag, monitoring the Actions workflow, then updating devinfra).
