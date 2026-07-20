# Bert-E — OpenWiki Quickstart

## What is this repository?

**Bert-E** is Scality's automated Git branch-merging bot. It is the *only*
account allowed to write to a repository's protected `development/*`
branches: humans open pull requests, and Bert-E validates, merges, and
cascades the change through every affected release line according to a
branching model called **GitWaterFlow**.

Bert-E runs as a long-lived Flask service that receives GitHub/Bitbucket
webhooks (and a small REST API), turns them into internal **jobs**, and
processes those jobs against a local clone of the target repository using
the `git` CLI and the host's REST API (PR comments, approvals, build
statuses).

Primary references, already authoritative and not duplicated here:
- [`bert_e/docs/USER_DOC.md`](../bert_e/docs/USER_DOC.md) — full business rules, message-code table, options/commands table, queue scenarios.
- [`bert_e/docs/API_DOC.md`](../bert_e/docs/API_DOC.md) — REST API authentication and endpoint reference.
- [`README.md`](../README.md) — local dev quickstart (codespace, `tox run -e run`, `tox -e tests`).
- [`CLAUDE.md`](../CLAUDE.md) — notes for running tests (`.venv/bin/pytest`) and cutting a release.

## Repository layout

```
bert_e/
├── bert_e.py            # BertE core class: task queue, job processing loop
├── job.py                # Job base classes (PullRequestJob, CommitJob, ...)
├── reactor.py            # Generic @bert-e comment command/option registry
├── settings.py           # YAML settings loading + marshmallow schema
├── exceptions.py         # Numbered, templated exceptions = bot's outcomes
├── templates/            # Markdown templates rendered into PR comments
├── git_host/             # Abstraction over GitHub / Bitbucket / mock
├── workflow/
│   ├── gitwaterflow/     # The core merge/branching engine (see below)
│   ├── pr_utils.py
│   └── git_utils.py
├── jobs/                 # API-triggered maintenance jobs (create/delete branch, queues...)
├── bin/                  # Standalone CLI utility scripts
├── lib/                  # git wrapper, retry, caching, templating helpers
├── server/               # Flask app: webhooks, REST API, status/management UI
├── docs/                 # USER_DOC.md / API_DOC.md (hand-maintained business docs)
└── tests/                # Functional (test_bert_e.py) + unit tests
charts/bert-e/            # Helm chart for Kubernetes deployment
manifests/                # Kustomize manifests
settings.sample.yml       # Annotated example of a repository's Bert-E config
```

## Where to go next

- **[Architecture overview](architecture/overview.md)** — how a webhook becomes a merged commit: server, jobs, dispatcher, git host abstraction, settings.
- **[GitWaterFlow engine](architecture/gitwaterflow.md)** — the branching model, branch taxonomy, the pull-request check pipeline, the merge queue, and Jira integration. Start here before changing merge/business logic.
- **[Commands and options](architecture/commands-and-options.md)** — how `@bert-e <command>` comments are parsed and dispatched, and how to add new ones.
- **[Running and testing](operations/running-and-testing.md)** — local dev loop, tox test environments, CI matrix, Docker/Helm deployment, maintenance jobs and CLI scripts.
- **[API and integrations](operations/api-and-integrations.md)** — REST API surface, auth (GitHub App / Bitbucket OAuth), webhook events, Jira configuration.

## Quick orientation for a new change

1. **Business rule / merge-condition change** → read `architecture/gitwaterflow.md`, then `bert_e/workflow/gitwaterflow/__init__.py` and `bert_e/exceptions.py`; check `bert_e/docs/USER_DOC.md` for the checklist order and message codes, and update it if the observable behavior changes.
2. **New `@bert-e` command or option** → read `architecture/commands-and-options.md`, then `bert_e/workflow/gitwaterflow/commands.py` and `bert_e/reactor.py`.
3. **GitHub/Bitbucket API interaction** → `bert_e/git_host/base.py` (abstract interface), then the concrete `github/` or `bitbucket/` implementation, and `bert_e/git_host/mock.py` if you need it reflected in tests.
4. **Webhook/API/server behavior** → `operations/api-and-integrations.md`, then `bert_e/server/`.
5. **Maintenance operation (rebuild queues, delete branch, etc.)** → `operations/running-and-testing.md`, then `bert_e/jobs/`.

Always run the relevant tox environment(s) described in
[`operations/running-and-testing.md`](operations/running-and-testing.md)
before considering a change complete — most business logic is covered by
the large functional suite in `bert_e/tests/test_bert_e.py`, run against a
mock git host.
