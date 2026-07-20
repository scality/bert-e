# bert-e

This is a **Python automated branch merging bot** (Bert-E). It implements the GitWaterFlow branching model for Scality repositories. It contains:

- Git host integrations (`bert_e/git_host/`) — Bitbucket and GitHub API clients
- Workflow engine (`bert_e/workflow/`) — GitWaterFlow logic for branch queue management
- Job handlers (`bert_e/jobs/`) — discrete operations (create/delete branches, rebuild queues)
- Flask web server (`bert_e/server/`) — webhook receiver and dashboard UI
- Utility libraries (`bert_e/lib/`) — git, retry, schema validation, Jira integration
- Test suite (`bert_e/tests/`) — pytest-based, uses mocks for git host interactions

Tech stack: Python 3.10+, Flask, PyYAML, requests, marshmallow, pytest. No Node.js or git-based shared libraries.

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
