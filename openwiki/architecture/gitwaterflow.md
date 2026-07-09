# GitWaterFlow Engine

This is the core business logic of Bert-E: the branching model, the checks a
pull request must pass, and the merge queue that lands code on
`development/*` branches. Read this before changing any merge/branching
behavior. For how a webhook/job reaches this code, see
[overview.md](overview.md).

The authoritative, user-facing description of these rules (message-code
table, full option/command list, worked queue scenarios) lives in
[`bert_e/docs/USER_DOC.md`](../../bert_e/docs/USER_DOC.md) — **update it
whenever observable behavior changes**. This page explains the implementation
and the "why", and links into that table rather than duplicating it.

## Branch taxonomy (`bert_e/workflow/gitwaterflow/branches.py`)

Every branch name is parsed into a typed object by `branch_factory()`, which
tries each `GWFBranch` subclass's regex `pattern` in turn:

| Class | Pattern example | Role |
|---|---|---|
| `FeatureBranch` | `feature/KEY-123-x`, `bugfix/...`, `improvement/...` | Source branches carrying a change; `cascade_producer = True` |
| `DevelopmentBranch` | `development/6`, `development/6.0` | Destination branches; both a cascade producer and consumer |
| `HotfixBranch` | `hotfix/6.0.1` | Destination for hotfixes on a released version; `can_be_destination = True` |
| `LegacyHotfixBranch` | `hotfix/<label>` | Older, unversioned hotfix naming, kept for compatibility |
| `ReleaseBranch` | `release/6.0` | Marks a version as released |
| `UserBranch` | `user/...` | Explicitly ignored by Bert-E |
| `IntegrationBranch` / `GhostIntegrationBranch` | `w/6.0/feature/KEY-123-x` | Temporary branch merging a feature branch's latest code onto one destination branch; one per (PR, destination) pair |
| `QueueBranch` / `QueueIntegrationBranch` | `q/6.0`, `q/<pr>/6.0/...` | Merge-queue branches (see below) |

Key invariants encoded here:
- **Cascade**: a change accepted into one `development/x` branch must also
  reach every later `development/*` branch. `BranchCascade` (bottom of
  `branches.py`) builds the ordered set of destination branches from the
  existing `development/*`, `hotfix/*`, and `release/*` branches and computes
  merge paths (`get_merge_paths`, `_set_target_versions`, `finalize`).
- **Version ordering**: `compare_branches`/`_compare_version_component`
  implement the specific ordering rule `4.3 < 4 < 5.1 < 10.0 < 10` (minor
  branches sort before their major-only counterpart) — this is
  repository-specific and easy to get subtly wrong; there are dedicated unit
  tests for it (`bert_e/tests/unit/test_queueing.py` and others).
  Pre-GA hotfixes (`hfrev`) and "phantom" hotfix versions are a newer, more
  delicate area — see `HotfixBranch.hfrev`, `pending_hotfix_branches`,
  `phantom_hotfix_versions`, and `update_versions()` in `branches.py`, and
  recent git history on `branches.py`/`jira.py` for the pre-GA hotfix
  reminder feature.

## The pull request pipeline (`bert_e/workflow/gitwaterflow/__init__.py`)

`handle_pull_request` → `_handle_pull_request` runs a strict, ordered
sequence of checks. Each check either passes silently or raises a
`bert_e.exceptions.TemplateException` subclass (see "Exceptions are the
control flow" below), which becomes a PR comment and stops processing for
that run. In order:

1. `early_checks` — is the PR open, destination a `development/*` branch,
   source branch usable at all.
2. `send_greetings` — first-time welcome comment (`InitMessage`).
3. `handle_comments` — parses all PR comments through the `Reactor`
   (see [commands-and-options.md](commands-and-options.md)) to compute
   `job.active_options` and execute any one-shot commands.
4. `check_dependencies` — `after_pull_request` option: wait for other PRs.
5. `clone_git_repo` — from here on the code operates on a real local clone.
6. `check_branch_compatibility` — source-branch prefix valid for destination
   (`bypass_incompatible_branch`).
7. `jira_checks` (`jira.py`) — ticket reference, project, issue type vs
   branch prefix, Fix Version coherence (`bypass_jira_check`); includes the
   pre-GA hotfix "pending fix version" one-time reminder.
8. `check_commit_diff` — diff size limit (`max_commit_diff` setting).
9. `create_integration_branches` / `create_integration_pull_requests`
   (`integration.py`) — build the `w/<version>/<branch>` branches (and
   optionally PRs) for every destination in the cascade;
   `check_integration_branches` detects manual tampering and offers
   `reset`/`force_reset`.
10. `check_in_sync` / `check_pull_request_skew` — integration branches still
    match the current PR head and destination.
11. `check_approvals` — author approval (not on GitHub) and peer/leader
    approval counts, with `unanimity`, `bypass_*_approval` options.
12. `check_build_status` / `revalidate_build_status` — build status on
    integration branches must be green; the latter does a **live** re-check
    right before merging to avoid racing a stale cached status
    (`bypass_build_status`).
13. `merge_integration_branches` — the actual merge. If `use_queue` is
    enabled (default), this **adds PRs to the merge queue** instead of
    merging directly to `development/*` (see below); otherwise it merges
    each integration branch straight onto its destination.

`handle_commit` reacts to build-status webhooks: it maps the updated commit
back to its branch(es); if any are queue branches it re-runs the queue
handler (`queueing.handle_merge_queues`), otherwise it re-runs
`handle_pull_request` for the owning PR so the pipeline above re-evaluates
build status.

### Exceptions are the control flow

`bert_e/exceptions.py` defines one exception class per outcome/message,
each with a numeric `code`, a Markdown `template` (rendered from
`bert_e/templates/`), and a `dont_repeat_if_in_history` policy controlling
whether Bert-E re-posts the same comment on every run. This is the
mechanism used to talk to PR authors — **there is no separate "notification"
system**; raising the right exception *is* how you send a message or stop
processing. When adding a new check, add a matching exception + template
pair here, and reference the message-code table in `USER_DOC.md`.

## The merge queue (`bert_e/workflow/gitwaterflow/queueing.py`)

When `use_queue` is enabled (the default, toggled by `disable_queues`
setting), a validated PR is not merged immediately. Instead:

- `add_to_queue` creates `q/<pr_id>/<version>/...` (`QueueIntegrationBranch`)
  branches stacked on top of the current `q/<version>` (`QueueBranch`) tip,
  for every destination version, and pushes a combined build.
- `QueueCollection` (in `branches.py`) reconstructs the full picture of all
  queued branches across all versions from the repository's branch list
  (`build_queue_collection`), and `validate()` performs horizontal
  (per-version) and vertical (cross-version, cascade-consistency) validation
  to compute which queued PRs have an all-green, fully-stacked build
  (`mergeable_queues` / `mergeable_prs`) versus which failed
  (`failed_prs`).
- `handle_merge_queues` (registered for `QueuesJob`, triggered by a build
  status change on a queue branch, or the `rebuild_queues`/`force_merge_queues`
  maintenance jobs) is the periodic reconciliation: build the cascade,
  build the queue collection, validate it, and if there is a mergeable
  prefix of the queue, fast-forward the real `development/*`/`hotfix/*`
  branches (`merge_queues`), close out the corresponding PRs
  (`close_queued_pull_request`), and push everything with `--prune`.

This "optimistic queueing" design lets multiple PRs build concurrently
against a stacked, speculative history, and only promotes commits once the
whole stack from the front of the queue is green — see the worked scenarios
in `USER_DOC.md` for the user-visible behavior.

## Jira integration (`bert_e/workflow/gitwaterflow/jira.py`)

When `jira_account_url`/`jira_keys` are configured, `jira_checks` validates
the ticket referenced in the branch name: existence, project membership,
issue type vs. the `prefixes` mapping in settings, and Fix Version
consistency with the cascade of destination branches. `bert_e/lib/jira.py`
is the thin REST client. Pre-GA hotfix branches get special handling
(`_notify_pending_hotfix_if_needed`) to remind authors once about a required
follow-up cherry-pick, without repeating on every run.

## What to watch out for

- **Order matters.** The pipeline stops at the first failing check; moving a
  check earlier/later changes which message a user sees first. Match new
  checks to the existing order described in `USER_DOC.md`.
- **`GWFBranch.__eq__`/`__lt__` and `version_t`** encode subtle,
  repository-specific version-ordering rules (major vs `major.minor`,
  hotfix `hfrev`, pre-GA "phantom" versions). Changes here have historically
  caused regressions (see git history on `branches.py` and
  `bert_e/tests/unit/test_queueing.py`) — always add/adjust unit tests
  alongside any change.
- **Exceptions carry `dont_repeat_if_in_history`.** Get this wrong and users
  either get spammed on every run or never see an important message again.
- **Robot-authored PRs** (integration PRs, whose source branch matches
  `IntegrationBranch.pattern`) are routed to `handle_parent_pull_request`
  instead of being treated as a normal feature PR — don't break this
  dispatch when touching `handle_pull_request`.
- Most of this logic is exercised by the large functional suite
  `bert_e/tests/test_bert_e.py` run against the `mock` git host (tox env
  `tests`), plus focused unit tests in `bert_e/tests/unit/`. See
  [operations/running-and-testing.md](../operations/running-and-testing.md).
