
from bert_e.git_host.github import AggregatedWorkflowRuns, Client

from pytest import fixture


@fixture
def client():
    return Client(
        login='login',
        password='password',
        email='email@org.com',
        base_url="http://localhost:4010",
        accept_header="application/json"
    )


@fixture
def workflow_run_json():
    return {
        'workflow_runs': [
            {
                'id': 1,
                'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3',
                'head_branch': 'q/1',
                'status': 'completed',
                'event': 'pull_request',
                'workflow_id': 1,
                'check_suite_id': 1,
                'conclusion': 'success',
                'pull_requests': [
                    {
                        'number': 1
                    }
                ],
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {
                        'login': 'octo-org'
                    },
                    'name': 'Hello-World'
                }
            },
            {
                'id': 2,
                'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3',
                'head_branch': 'q/1',
                'workflow_id': 1,
                'check_suite_id': 2,
                'event': 'pull_request',
                'status': 'completed',
                'conclusion': 'cancelled',
                'pull_requests': [
                    {
                        'number': 1
                    }
                ],
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {
                        'login': 'octo-org'
                    },
                    'name': 'Hello-World'
                }
            },
            {
                'id': 3,
                'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3',
                'head_branch': 'q/1',
                'workflow_id': 2,
                'check_suite_id': 3,
                'event': 'pull_request',
                'status': 'completed',
                'conclusion': 'skipped',
                'pull_requests': [
                    {
                        'number': 1
                    }
                ],
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {
                        'login': 'octo-org'
                    },
                    'name': 'Hello-World'
                }
            }
        ],
        'total_count': 3
    }


def test_aggregated_workflow_run_api_client(client):
    """Run the workflow run client with the GitHub mock server."""
    head_sha = 'acb5820ced9479c074f688cc328bf03f341a511d'
    owner = 'octocat'
    repo = 'Hello-World'
    workflow_runs = AggregatedWorkflowRuns.get(
        client=client,
        owner=owner,
        repo=repo,
        params={
            'head_sha': head_sha
        }
    )
    assert workflow_runs.state == 'INPROGRESS'
    assert workflow_runs.full_repo == f'{owner}/{repo}'
    assert workflow_runs.commit == head_sha
    assert workflow_runs.owner == owner
    assert workflow_runs.repo == repo
    assert workflow_runs.branch == 'master'


def test_aggregated_workflow_run(client, workflow_run_json):
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

    full_name = \
        workflow_run_json['workflow_runs'][0]['repository']['full_name']
    head_sha = workflow_run_json['workflow_runs'][0]['head_sha']
    owner = \
        workflow_run_json['workflow_runs'][0]['repository']['owner']['login']
    repo = workflow_run_json['workflow_runs'][0]['repository']['name']
    branch = workflow_run_json['workflow_runs'][0]['head_branch']
    url = f"https://github.com/{full_name}/actions?query=branch%3A{branch}"
    assert url == workflow_runs.url
    assert head_sha == workflow_runs.commit
    assert owner == workflow_runs.owner
    assert repo == workflow_runs.repo
    assert full_name == workflow_runs.full_repo
    assert branch == workflow_runs.branch
    assert workflow_runs.is_pending() is False
    assert workflow_runs.is_queued() is False

    workflow_run_json['workflow_runs'][0]['status'] = 'queued'
    workflow_run_json['workflow_runs'][0]['conclusion'] = None
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)
    assert workflow_runs.is_pending() is False
    assert workflow_runs.is_queued() is True
    assert workflow_runs.state == "INPROGRESS"
    workflow_run_json['workflow_runs'][0]['status'] = 'pending'
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)
    assert workflow_runs.is_pending() is True
    assert workflow_runs.is_queued() is False
    assert workflow_runs.state == "INPROGRESS"

    workflow_run_json['workflow_runs'] = []
    workflow_run_json['total_count'] = 0
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)
    assert workflow_runs.url is None
    assert workflow_runs.commit is None
    assert workflow_runs.owner is None
    assert workflow_runs.repo is None
    assert workflow_runs.full_repo is None
    assert workflow_runs.branch is None


def test_cancelled_build_same_sha(client, monkeypatch, workflow_run_json):

    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)
    monkeypatch.setattr(AggregatedWorkflowRuns, 'get',
                        lambda *args, **kwargs: workflow_runs)
    get_workflow_run = AggregatedWorkflowRuns.get(
        client=client,
        owner=workflow_run_json['workflow_runs'][0]['repository']['owner']['login'], # noqa
        repo=workflow_run_json['workflow_runs'][0]['repository']['name'],
        ref=workflow_run_json['workflow_runs'][0]['head_sha']
    )
    assert get_workflow_run.state == 'SUCCESSFUL'


def test_skipped_workflow_treated_as_success(client):
    """Test that a completed workflow with conclusion 'skipped' is
    treated as successful.

    This reproduces the real scenario where:
    - Workflow 1: conclusion='success'
    - Workflow 2: conclusion='skipped' (different workflow_id)

    Both should be considered successful, not cause a KeyError.
    """
    workflow_run_json = {
        'workflow_runs': [
            {
                'id': 1,
                'head_sha': 'abc123',
                'head_branch': 'feature-branch',
                'status': 'completed',
                'event': 'pull_request',
                'workflow_id': 1,
                'check_suite_id': 1,
                'conclusion': 'success',
                'pull_requests': [{'number': 1}],
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {'login': 'octo-org'},
                    'name': 'Hello-World'
                }
            },
            {
                'id': 2,
                'head_sha': 'abc123',
                'head_branch': 'feature-branch',
                'workflow_id': 2,
                'check_suite_id': 2,
                'event': 'pull_request',
                'status': 'completed',
                'conclusion': 'skipped',
                'pull_requests': [{'number': 1}],
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {'login': 'octo-org'},
                    'name': 'Hello-World'
                }
            }
        ],
        'total_count': 2
    }

    # This should not raise KeyError on 'skipped'
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

    # Both workflows should be kept (different workflow_ids)
    assert len(workflow_runs._workflow_runs) == 2

    # State should be SUCCESSFUL (both success and skipped are treated
    # as success)
    assert workflow_runs.state == 'SUCCESSFUL'
    assert workflow_runs.is_pending() is False
    assert workflow_runs.is_queued() is False


def _make_run(*, run_id, sha, branch, status, conclusion, event='push',
              workflow_id):
    return {
        'id': run_id,
        'head_sha': sha,
        'head_branch': branch,
        'status': status,
        'event': event,
        'workflow_id': workflow_id,
        'check_suite_id': run_id,
        'conclusion': conclusion,
        'pull_requests': [],
        'repository': {
            'full_name': 'org/repo',
            'owner': {'login': 'org'},
            'name': 'repo',
        },
    }


SHARED_SHA = 'aabb' * 10
W_BRANCH = 'w/4.3/bugfix/BERTE-602'


def test_cross_branch_sha_poisoning_state_property(client):
    """Document the existing .state bug: a sibling branch's SUCCESSFUL run
    on the same SHA causes .state to return SUCCESSFUL even though the
    w-branch is still in_progress (the PR 5155 hollow-success shape).
    """
    data = {
        'total_count': 2,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                status='in_progress', conclusion=None, workflow_id=10),
            _make_run(
                run_id=2, sha=SHARED_SHA, branch='development/4.3',
                status='completed', conclusion='success', workflow_id=20),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    # The existing .state property returns SUCCESSFUL because development/4.3
    # succeeded — this is the source of the stale-cache poisoning.
    assert runs.state == 'SUCCESSFUL'


def test_state_for_branch_catches_inprogress(client):
    """state_for_branch filters strictly to the requested branch so an
    in-progress run is not masked by a sibling branch's success.
    """
    data = {
        'total_count': 2,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                status='in_progress', conclusion=None, workflow_id=10),
            _make_run(
                run_id=2, sha=SHARED_SHA, branch='development/4.3',
                status='completed', conclusion='success', workflow_id=20),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    assert runs.state_for_branch(W_BRANCH) == 'INPROGRESS'
    assert runs.state_for_branch('development/4.3') == 'SUCCESSFUL'


def test_state_for_branch_no_runs_returns_notstarted(client):
    data = {
        'total_count': 1,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch='development/4.3',
                status='completed', conclusion='success', workflow_id=20),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    assert runs.state_for_branch(W_BRANCH) == 'NOTSTARTED'


def test_state_for_branch_workflow_dispatch_excluded(client):
    data = {
        'total_count': 1,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                status='completed', conclusion='success',
                event='workflow_dispatch', workflow_id=10),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    assert runs.state_for_branch(W_BRANCH) == 'NOTSTARTED'


def test_state_for_branch_deduplicates_within_branch(client):
    """Same workflow_id on the same branch: keep the best conclusion."""
    data = {
        'total_count': 2,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                status='completed', conclusion='cancelled', workflow_id=10),
            _make_run(
                run_id=2, sha=SHARED_SHA, branch=W_BRANCH,
                status='completed', conclusion='success', workflow_id=10),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    assert runs.state_for_branch(W_BRANCH) == 'SUCCESSFUL'


def test_state_for_branch_clean_pr_passes(client):
    """A PR where the w-branch completed successfully passes revalidation."""
    data = {
        'total_count': 2,
        'workflow_runs': [
            _make_run(
                run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                status='completed', conclusion='success', workflow_id=10),
            _make_run(
                run_id=2, sha=SHARED_SHA, branch=W_BRANCH,
                status='completed', conclusion='skipped', workflow_id=20),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    assert runs.state_for_branch(W_BRANCH) == 'SUCCESSFUL'
