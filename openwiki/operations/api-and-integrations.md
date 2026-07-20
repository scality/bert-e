# API and Integrations

## REST API (`bert_e/server/api/`)

Full endpoint reference (auth flow, request/response bodies, examples) is
authoritative in [`bert_e/docs/API_DOC.md`](../../bert_e/docs/API_DOC.md) —
this page summarizes the mechanism and where to extend it.

- `server/api/__init__.py` registers the API blueprint and its
  sub-resources.
- `server/api/base.py` — shared helpers: turning a `Job` into a JSON
  response, permission checks (session user vs. `admins`/repo membership).
- `server/api/jobs.py` — `GET /api/jobs` (list, capped at the last 1000
  completed + in-flight) and `GET /api/jobs/<id>` (single job status). Maps
  directly onto `BertE.tasks_done` / `task_queue` described in
  [architecture/overview.md](../architecture/overview.md).
- `server/api/pull_requests.py` — `POST /api/pull-requests/<id>` creates an
  `eval_pull_request`-style job to (re-)evaluate a PR outside of a webhook.
- `server/api/gwf/` — endpoints that map onto the maintenance `Job`
  subclasses in `bert_e/jobs/` (create/delete branch, rebuild/force-merge/
  delete queues) — see
  [running-and-testing.md](running-and-testing.md#maintenance-jobs-bert_ejobs).

Adding a new API endpoint typically means: define a new `APIJob` subclass in
`bert_e/jobs/`, register a `@handler(...)` function for it (see
[architecture/overview.md](../architecture/overview.md#jobs-bert_ejobpy-bert_ejobs)),
then expose it via a new route in `server/api/`.

## Authentication (`bert_e/server/auth.py`, `session.py`)

Two distinct auth mechanisms, for two distinct audiences:

- **Webhook endpoints** (`/github`, `/bitbucket` in `server/webhook.py`) are
  protected by HTTP Basic Auth (`requires_basic_auth` decorator), using
  credentials configured on the git host side when the webhook was
  registered (see `bin/webhook_register.py`).
- **Human-facing API/UI** uses OAuth login against GitHub or Bitbucket via
  `authlib`/`loginpass` (`server/auth.py`), establishing a Flask session
  (`server/session.py`) after `/api/auth` validates the provider access
  token. Session-authenticated users are authorized against the
  repository's `admins` setting for privileged operations.

Never commit real client secrets/tokens; they are supplied as environment
variables at deploy time (see `[testenv:run]` in `tox.ini` and
`charts/bert-e/values.yaml` for how secrets are wired in each environment).

## Webhooks (`bert_e/server/webhook.py`)

Single entry point that turns git-host webhook payloads into `Job`s pushed
onto `BertE`'s queue (`bert_e.put_job`, see
[architecture/overview.md](../architecture/overview.md)):

- **Bitbucket**: `handle_bitbucket_repo_event` (commit/build status changes
  → `CommitJob`) and `handle_bitbucket_pr_event` (PR created/updated/
  commented/reviewed → `PullRequestJob`).
- **GitHub**: `handle_github_pr_event` (PR events, ignoring `closed`),
  `handle_github_issue_comment` (issue/PR comments), and check-suite/status
  events → `CommitJob`. GitHub events are parsed into typed objects (e.g.
  `github.PullRequestEvent`) via each provider's `schema.py`.

Build-status events are cached in `BUILD_STATUS_CACHE`
(`bert_e/git_host/cache.py`) to avoid redundant lookups when many statuses
arrive in a burst (e.g. CI reporting several checks).

## Git host abstraction

See [architecture/overview.md](../architecture/overview.md#git-host-abstraction-bert_egit_host)
for the `base.py`/`factory.py`/`mock.py`/`github/`/`bitbucket/` breakdown.
Practical integration notes:

- New provider capabilities must be added to `base.AbstractClient` (or the
  relevant `Abstract*` class) first, then implemented in **both**
  `github/__init__.py` and `bitbucket/__init__.py`, and in `mock.py` so the
  functional test suite exercises it (`tox -e tests`).
  `bert_e/tests/test_git_host.py` (run via `tox -e tests-api-mock`) is the
  contract test suite for the abstraction itself.
- Each provider has its own `schema.py` for marshmallow (de)serialization of
  that provider's REST payloads — this is where field-name differences
  between GitHub and Bitbucket are absorbed.

## Jira integration

Configured per-repository via `jira_account_url`, `jira_email`, `jira_keys`,
and `prefixes` in `settings.yml` (see `settings.sample.yml` for the full,
commented list). If `jira_account_url`/`jira_email`/`jira_keys` are empty,
Jira checks are skipped entirely.

- `bert_e/lib/jira.py` — thin wrapper (`JiraIssue`) around the `jira` Python
  client, doing basic-auth (email + API token) lookups of a single issue.
- `bert_e/workflow/gitwaterflow/jira.py` — the actual business checks run
  against a PR's branch (issue exists, project matches `jira_keys`, issue
  type matches the branch prefix via `prefixes`, Fix Version/s field is
  coherent with the target branch, including pre-GA hotfix nuances). See
  [architecture/gitwaterflow.md](../architecture/gitwaterflow.md#jira-integration)
  for the business rules and message codes.

## Existing docs to read alongside this page

- [`bert_e/docs/API_DOC.md`](../../bert_e/docs/API_DOC.md) — full endpoint
  reference with request/response examples.
- [`bert_e/docs/USER_DOC.md`](../../bert_e/docs/USER_DOC.md) — end-user
  facing behavior (options, commands, message codes).
