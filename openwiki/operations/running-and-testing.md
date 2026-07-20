# Running, Testing, and Deploying

## Local development

Bert-E's only supported dev method is the provided codespace/devcontainer
(`.devcontainer/`). From inside it:

```shell
cp settings.sample.yml settings.yml   # edit to your liking, see settings.sample.yml
tox run -e run                        # runs bert-e-serve on :8000 (tox.ini [testenv:run])
```

`[testenv:run]` (`tox.ini`) sets `BERT_E_CLIENT_ID`/`BERT_E_CLIENT_SECRET`/
`BERT_E_ROBOT_PASSWORD`/`BERT_E_JIRA_TOKEN`/`WEBHOOK_LOGIN`/`WEBHOOK_PWD` from
environment (falling back to dev defaults), then runs
`bert-e-serve -v -f settings.yml -p 8000` (entry point defined in
`setup.py`, implemented in `bert_e/server/server.py`).

Per `CLAUDE.md`, `pytest` is installed at `.venv/bin/pytest` (not on PATH) —
use that directly, or the tox environments below, which is the primary
supported way to run tests.

## Test environments (`tox.ini`)

| tox env | What it runs | Notes |
|---|---|---|
| `flake8` | `flake8 bert_e/` | Style/lint gate |
| `utests` | `pytest bert_e/tests/unit/` | Fast, isolated unit tests |
| `tests-api-mock` | `pytest -k mock bert_e/tests/test_git_host.py` | Git-host client contract tests against the mock |
| `tests-server` | `pytest bert_e/tests/test_server.py` | Flask server/API/webhook tests |
| `tests-noqueue` | `bert_e.tests.test_bert_e` with `--git-host mock --disable-queues` | Full functional suite, queue feature off |
| `tests` | `bert_e.tests.test_bert_e` with `--git-host mock` | Full functional suite, queues on — the main GitWaterFlow regression suite |
| `tests-githost` | Same functional suite against a **real** configured git host | Needs real credentials, see below |
| `coverage-report` | `coverage report` / `coverage html` | |

`bert_e/tests/test_bert_e.py` is organized into test *classes* matching real
scenarios (visible in the CI matrix): `QuickTest`, `BuildFailedTest`,
`RepositoryTests`, `TestBertE`, `TestQueueing`, `TaskQueueTests`. Pass a
class name as a positional arg (`{posargs}`) to run just that subset — this
is how `.github/workflows/main.yaml` parallelizes the functional suite.

Running against a real git host (`tests-githost`) requires credentials for a
team/org, a robot account, a contributor account, and an admin account —
see the env vars listed in `tox.ini`'s `[testenv:tests-githost]` and don't
put real credentials in `settings.yml`/tracked files.

## CI (`.github/workflows/`)

- `main.yaml` ("basic tests") — on every PR/push to `main`: matrix of
  `unit` (`utests`, `tests-api-mock`, `tests-server`), `integration`
  (`tests-noqueue` × `tests`, each × the 6 test classes above), and `lint`
  (`flake8` + `helm lint charts/bert-e`). Coverage uploaded to Codecov
  (`codecov.yml`).
- `build.yaml` — builds/pushes the Docker image.
- `release.yaml` — manual workflow_dispatch release process, see
  `RELEASE.md` (tags a commit, builds+pushes the image, creates a GitHub
  Release). `CLAUDE.md` documents the practical gotcha: `gh release
  create --target` needs the **full** commit SHA, not a short one.
- `codeql.yml`, `trivy.yaml` — security scanning.

## Maintenance jobs (`bert_e/jobs/`)

These are `APIJob` subclasses, triggered via the REST API (see
[api-and-integrations.md](api-and-integrations.md)) rather than by webhooks,
for operations an admin needs to trigger by hand:

- `create_branch.py` — create a new `development/*`/`hotfix/*` destination
  branch and fold it into the cascade.
- `delete_branch.py` — remove a destination branch.
- `rebuild_queues.py` — recompute/repair the merge queue from scratch.
- `force_merge_queues.py` — force-merge the current queue state.
- `delete_queues.py` — drop all queue (`q/*`) branches.
- `eval_pull_request.py` — force (re-)evaluation of a specific PR outside
  the normal webhook trigger.

Each defines a `Job` subclass plus a `@handler(...)`-registered function
following the same dispatcher pattern described in
[architecture/overview.md](../architecture/overview.md).

## Standalone CLI scripts (`bert_e/bin/`)

Installed as console scripts by `setup.py`, independent of the running
server:

- `webhook_register.py` (`webhook_register`) — registers the Bitbucket
  webhook events Bert-E needs on a repository.
- `webhook_parser.py` (`webhook_parser`) — decodes/inspects a raw webhook
  payload for debugging.
- `filter_pull_requests.py` (`filter_pull_requests`) — lists/filters PRs
  matching criteria.
- `nobuildstatus.py` (`nobuildstatus`) — finds commits/branches missing a
  build status.

## Deployment

- **Docker** (`Dockerfile`): `python:3.10-slim-bullseye` base, installs
  `git` + `requirements.txt`, installs the package, entrypoint
  `bert-e-serve`. Built/pushed by `build.yaml`/`release.yaml`.
- **Kubernetes**: `charts/bert-e/` is the Helm chart (values in
  `values.yaml`, linted in CI via `helm lint`); `manifests/` holds Kustomize
  manifests for environment-specific overlays. Treat `values.yaml`/manifests
  as the reference for what's configurable at deploy time (replica count,
  ingress, secrets wiring) rather than duplicating it here.
- Runtime configuration is a per-repository `settings.yml` validated by
  `bert_e/settings.py`; **never commit real secrets** — robot passwords,
  OAuth secrets, and Jira tokens are supplied via environment/secret store,
  not the settings file itself (see the `[MANDATORY]`/`[OPTIONAL]` comments
  in `settings.sample.yml` for the full list of fields and what's sensitive).

## What to watch out for

- The `tests`/`tests-noqueue` functional suite is the primary safety net for
  GitWaterFlow business-logic changes; always run the relevant test
  class(es) locally before considering a merge/queue change done.
- `flake8` (E501 line length, etc.) is enforced in CI; several past commits
  exist solely to fix lint violations — run `tox -e flake8` before pushing.
- `helm lint charts/bert-e` is also a CI gate if you touch the chart.
