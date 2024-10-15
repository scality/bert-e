
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
            }
        ],
        'total_count': 2
    }


def test_aggregated_workflow_run_api_client(client):
    """Run the workflow run client with the GitHub mock server."""
    workflow_runs = AggregatedWorkflowRuns.get(
        client=client,
        owner='octo-org',
        repo='Hello-World',
        params={
            'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3'
        }
    )
    assert workflow_runs.state == 'INPROGRESS'


def test_aggregated_workflow_run(client, workflow_run_json):
    workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

    full_name = \
        workflow_run_json['workflow_runs'][0]['repository']['full_name']
    head_sha = workflow_run_json['workflow_runs'][0]['head_sha']
    owner = \
        workflow_run_json['workflow_runs'][0]['repository']['owner']['login']
    repo = workflow_run_json['workflow_runs'][0]['repository']['name']
    url = f"https://github.com/{full_name}/commit/{head_sha}"
    branch = workflow_run_json['workflow_runs'][0]['head_branch']
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
