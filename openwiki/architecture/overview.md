# Architecture Overview

This page explains how Bert-E is wired together end to end: from an
incoming webhook or API call, to a queued job, to actual git operations
against the target repository. For the merge/branching business logic
itself, see [gitwaterflow.md](gitwaterflow.md).

## High-level flow

```
GitHub/Bitbucket webhook  ──┐
REST API call             ──┼──▶  Job (PullRequestJob / CommitJob / QueuesJob / APIJob subclass)
CLI invocation (bert-e)   ──┘             │
                                           ▼
                              BertE.put_job()  (dedups equal jobs)
                                           │
                                           ▼
                         background worker thread: BertE.process_task()
                                           │
                                           ▼
                    JobDispatcher.dispatch(job)  (bert_e/lib/dispatcher.py,
                    MRO-aware: matches job's class or a superclass to a
                    @handler-registered function)
                                           │
                                           ▼
                gitwaterflow handler (handle_pull_request / handle_commit /
                handle_merge_queues) — see gitwaterflow.md
                                           │
                                           ▼
        git_host client (GitHub/Bitbucket/mock) + local git clone (bert_e/lib/git.py)
```

Source: `bert_e/bert_e.py` (`BertE` class, `process_task`, `put_job`),
`bert_e/job.py`, `bert_e/lib/dispatcher.py`.

## The `BertE` core object (`bert_e/bert_e.py`)

`BertE` is constructed once per running process from a loaded `settings`
object. On construction it:

- builds a git-host client via `client_factory(settings.repository_host, ...)`
  (GitHub, Bitbucket, or `mock` for tests) — see "Git host abstraction" below;
- resolves `project_repo` (the target repo on the host);
- clones the repository locally into a temp directory (`GitRepository` from
  `bert_e/lib/git.py`), which is where all merges/conflicts actually happen;
- holds an in-process `Queue` of pending jobs (`task_queue`) and a bounded
  history of completed jobs (`tasks_done`, capped at 1000) used by the
  status page and `/api/jobs`.

`process_task()` is run in a loop by a background thread (started in
`bert_e/server/__init__.py::setup_bert_e`). It pops one job, calls
`self.process(job)` (which resets/dispatches), and records success/failure.
Errors that are not `BertE_Exception`/`InternalException` are logged as
unexpected; `JobFailure` is logged as an expected API failure. This is the
central place to look when debugging "why didn't my job run" or "why did
processing crash".

## Jobs (`bert_e/job.py`, `bert_e/jobs/`)

A **Job** is the unit of work carried on the task queue. Base classes:

- `Job` — id (uuid4), layered `settings` (per-job overrides merged over the
  global repository settings via `SettingsDict`), timing, status/details,
  JSON serialization for the API/status page.
- `RepoJob` — adds `project_repo` and a `git` namespace holding the local
  repo handle and the shared `BranchCascade` for this run.
- `PullRequestJob` — triggered by PR webhook events (open/update/comment/
  review); carries the `pull_request` object and per-author bypass options
  (from `pr_author_options` in settings).
- `CommitJob` — triggered by commit/build-status webhook events; used to
  react to build results on integration/queue branches.
- `QueuesJob` — merge-queue maintenance (supports `force_merge`).
- `APIJob` — base class for jobs triggered through the REST API; concrete
  subclasses live in `bert_e/jobs/*.py` (see
  [operations/running-and-testing.md](../operations/running-and-testing.md)).

Handlers are registered with the `@handler(JobClass)` decorator and
dispatched via `JobDispatcher`/`Dispatcher` (`bert_e/lib/dispatcher.py`),
which walks the job's MRO so a handler registered for a base class also
matches subclasses.

## Settings (`bert_e/settings.py`, `settings.sample.yml`)

Settings are loaded from a YAML file and validated with a `marshmallow`
schema (`setup_settings`). They define per-repository configuration:
git host, robot credentials, Jira integration, approval requirements,
branch-prefix rules, bypass privileges (`admins`, `pr_author_options`),
and queue-related toggles (`always_create_integration_branches`,
`always_create_integration_pull_requests`, `disable_queues`,
`max_commit_diff`). `settings.sample.yml` is the authoritative, commented
reference for every option — read it before adding a new setting.

Per-job settings (`Job.settings`) are a `SettingsDict` layering
request-specific overrides (e.g. an author's personal bypass options) on
top of the global settings, so handler code can read `job.settings.xxx`
without caring where the value came from.

## Git host abstraction (`bert_e/git_host/`)

Bert-E supports GitHub and Bitbucket (plus an in-memory `mock` used
throughout the test suite) behind one abstract interface:

- `base.py` defines `AbstractClient`, `AbstractRepository`,
  `AbstractPullRequest`, `AbstractComment`, `AbstractBuildStatus` — the
  contract every provider must implement (fetch/approve/decline/comment on
  PRs, read/set build status, create/delete repos, etc.), plus
  `BertESession`, a `requests.Session` with retry/backoff on flaky
  responses (raises `FlakyGitHost` after exhausting retries).
- `factory.py` is a small registry: each provider module registers itself
  with `@factory.api_client('github')` / `'bitbucket'`, and
  `client_factory(service, ...)` looks up the right class by the
  `repository_host` setting.
- `github/__init__.py` and `bitbucket/__init__.py` are the concrete
  implementations (each with its own `schema.py` for marshmallow
  (de)serialization of the provider's REST payloads).
- `mock.py` is a fully in-memory fake client, used by the functional test
  suite (`bert_e/tests/test_bert_e.py --git-host mock`) so that GitWaterFlow
  logic can be exercised without hitting a real git host.
- `cache.py` holds `BUILD_STATUS_CACHE`, used by the webhook handlers and
  status page to avoid redundant build-status lookups.

When adding support for a new check or PR attribute, extend the abstract
base first, then implement it in both `github/` and `bitbucket/`
(and `mock.py`, so tests can cover it).

## The Flask server (`bert_e/server/`)

`bert_e/server/__init__.py` wires everything into a Flask app:

- `setup_bert_e()` constructs the `BertE` instance and starts the
  background worker thread described above.
- `setup_server()` builds the Flask app, configures webhook/OAuth
  credentials and CSRF key, and registers blueprints for the API, webhook
  receivers, status page, management UI, docs, auth, and session handling.

Key modules:
- `webhook.py` — receives `/bitbucket` and `/github` webhooks (behind HTTP
  basic auth), parses event type, and turns supported events (PR
  opened/updated, issue/PR comments, PR reviews, commit/check-suite status)
  into `PullRequestJob`/`CommitJob` instances submitted via `bert_e.put_job`.
- `status.py` — renders the live status page: current job, queued jobs,
  recently merged PRs, and per-version merge-queue state.
- `auth.py` / `session.py` — OAuth login (GitHub/Bitbucket) plus basic auth
  for webhook endpoints; see
  [operations/api-and-integrations.md](../operations/api-and-integrations.md).
- `api/` — REST endpoints that map directly onto `bert_e/jobs/*.py` job
  classes (see the same operations page and `bert_e/docs/API_DOC.md`).

## Supporting libraries (`bert_e/lib/`)

- `git.py` — thin wrapper around the `git` CLI (`simplecmd.py` runs shell
  commands) used for cloning, branching, merging, and inspecting history.
- `dispatcher.py` — the generic MRO-aware handler registry used by jobs.
- `retry.py` — a retry decorator used around flaky network operations.
- `template_loader.py` — loads and renders the Markdown templates in
  `bert_e/templates/` (used by `TemplateException`, see
  [gitwaterflow.md](gitwaterflow.md#exceptions-are-the-control-flow)).
- `settings_dict.py` — the layered-dict type used for settings and job
  options.
- `schema.py`, `versions.py`, `jira.py`, `lru_cache.py` — marshmallow
  schema helpers, semantic-version parsing, a small Jira REST client, and
  an LRU cache utility.

## What to watch out for

- The local git clone in `self.tmpdir` is shared/reset per job
  (`BertE.process`); handlers assume a clean, correctly-checked-out repo at
  the start of each run.
- Job deduplication (`put_job`) relies on `Job.__eq__`; if you add a new Job
  subclass, make sure duplicate-submission semantics are what you expect.
- Any new git-host capability must be added to `base.py` and implemented
  consistently in `github/`, `bitbucket/`, and `mock.py`, or the mock-backed
  functional tests will not exercise it.
