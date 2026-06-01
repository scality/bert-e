"""Unit tests for revalidate_build_status (BERTE-602).

These tests exercise the PR 5155 shape: same commit SHA on a w-branch
and its destination branch, with the push workflow on the w-branch still
in_progress when bert-e reaches the merge decision.

The specific incident (artesca#5155, 2026-05-20): the source branch was
renamed, so the same commit SHA appeared under both the old and new
w-branch names. The old w-branch had a completed-successful run; the new
w-branch's push workflow was still in_progress. Bert-E's aggregator returned
SUCCESSFUL (picking the best across branches), latched it into the cache,
and merged immediately. The fix: filter strictly to the current branch name
before aggregating so the old-name's success cannot mask the new-name's
in-progress run.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bert_e import exceptions as messages
from bert_e.git_host.github import AggregatedWorkflowRuns, Client
from bert_e.workflow.gitwaterflow import revalidate_build_status


SHARED_SHA = 'deadbeef' * 5
W_BRANCH = 'w/4.3/bugfix/BERTE-602'


@pytest.fixture
def client():
    return Client(
        login='login',
        password='password',
        email='email@org.com',
        base_url='http://localhost:4010',
        accept_header='application/json',
    )


def _make_run(*, run_id, sha, branch, status, conclusion,
              event='push', workflow_id):
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


def _make_job(*, key='github_actions', bypass=False):
    job = MagicMock()
    job.settings.build_key = key
    job.settings.bypass_build_status = bypass
    job.author_bypass.get.return_value = False
    job.settings.repository_host = 'github'
    job.settings.repository_owner = 'org'
    job.settings.repository_slug = 'repo'
    job.active_options = {}
    return job


def _make_wbranch(name, sha):
    branch = MagicMock()
    branch.name = name
    branch.get_latest_commit.return_value = sha
    return branch


def _make_combined(client, runs_data, key='github_actions'):
    """Build a fake combined status object as returned by get_commit_status."""
    actions = AggregatedWorkflowRuns(
        client, workflow_runs=runs_data, total_count=len(runs_data))
    combined = MagicMock()
    combined.status = {key: actions}
    return combined


def test_pr5155_shape_raises_build_in_progress(client):
    """Same SHA on w-branch (in_progress) and destination (success).

    revalidate_build_status must catch the in-progress run on the w-branch
    and raise BuildInProgress, blocking the merge.
    """
    runs_data = [
        _make_run(run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                  status='in_progress', conclusion=None, workflow_id=10),
        _make_run(run_id=2, sha=SHARED_SHA, branch='development/4.3',
                  status='completed', conclusion='success', workflow_id=20),
    ]
    job = _make_job()
    job.project_repo.get_commit_status.return_value = _make_combined(
        client, runs_data)
    job.project_repo.get_build_url.return_value = ''
    job.project_repo.get_commit_url.return_value = ''

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    with pytest.raises(messages.BuildInProgress):
        revalidate_build_status(job, wbranches)


def test_clean_pr_passes(client):
    """A PR with all runs completed successfully must not raise."""
    runs_data = [
        _make_run(run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                  status='completed', conclusion='success', workflow_id=10),
        _make_run(run_id=2, sha=SHARED_SHA, branch=W_BRANCH,
                  status='completed', conclusion='skipped', workflow_id=20),
    ]
    job = _make_job()
    job.project_repo.get_commit_status.return_value = _make_combined(
        client, runs_data)

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    revalidate_build_status(job, wbranches)


def test_bypass_skips_check(client):
    """bypass_build_status option must short-circuit the whole check."""
    job = _make_job(bypass=True)
    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    revalidate_build_status(job, wbranches)
    job.project_repo.get_commit_status.assert_not_called()


def test_no_build_key_skips_check(client):
    """Empty build_key must skip the check."""
    job = _make_job(key='')
    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    revalidate_build_status(job, wbranches)
    job.project_repo.get_commit_status.assert_not_called()


def test_host_without_get_commit_status_skips_check():
    """Hosts that lack get_commit_status (e.g. Bitbucket) must be skipped."""
    job = _make_job()
    job.project_repo = SimpleNamespace(
        get_build_url=lambda *a: '',
        get_commit_url=lambda *a: '',
    )
    job.settings.build_key = 'pre-merge'
    job.settings.bypass_build_status = False
    job.author_bypass.get.return_value = False

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]
    revalidate_build_status(job, wbranches)


def test_no_status_for_sha_raises_build_not_started(client):
    """get_commit_status returning None must raise BuildNotStarted."""
    job = _make_job()
    job.project_repo.get_commit_status.return_value = None

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    with pytest.raises(messages.BuildNotStarted):
        revalidate_build_status(job, wbranches)


def test_key_absent_in_combined_raises_build_not_started(client):
    """Key missing from combined status must raise BuildNotStarted."""
    job = _make_job()
    combined = MagicMock()
    combined.status = {}
    job.project_repo.get_commit_status.return_value = combined

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    with pytest.raises(messages.BuildNotStarted):
        revalidate_build_status(job, wbranches)


def test_failed_run_raises_build_failed(client):
    """A completed-failure run must raise BuildFailed."""
    runs_data = [
        _make_run(run_id=1, sha=SHARED_SHA, branch=W_BRANCH,
                  status='completed', conclusion='failure', workflow_id=10),
    ]
    job = _make_job()
    job.project_repo.get_commit_status.return_value = _make_combined(
        client, runs_data)
    job.project_repo.get_build_url.return_value = 'https://ci.example.com/1'
    job.project_repo.get_commit_url.return_value = 'https://github.com/c/sha'

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    with pytest.raises(messages.BuildFailed):
        revalidate_build_status(job, wbranches)


def test_no_runs_for_branch_raises_build_not_started(client):
    """If no runs exist for the specific w-branch, raise BuildNotStarted."""
    runs_data = [
        _make_run(run_id=1, sha=SHARED_SHA, branch='development/4.3',
                  status='completed', conclusion='success', workflow_id=10),
    ]
    job = _make_job()
    job.project_repo.get_commit_status.return_value = _make_combined(
        client, runs_data)

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    with pytest.raises(messages.BuildNotStarted):
        revalidate_build_status(job, wbranches)


def test_artesca5155_renamed_branch_inprogress_blocked(client):
    """Regression test for the exact artesca#5155 incident (2026-05-20).

    The source branch was renamed from 'bugfix/zenko-ui-bump' to
    'bugfix/zenko-ui-4.3.3'. Both the old and new w-branches share the same
    commit SHA. GitHub's API returns workflow runs for both branch names.

    The old w-branch (bugfix/zenko-ui-bump) has a completed-successful run.
    The new w-branch (bugfix/zenko-ui-4.3.3) has a push run still in_progress.

    The pre-fix aggregator returned SUCCESSFUL (best-of across branches) and
    latched it in the cache, causing an immediate merge.

    revalidate_build_status must filter to the new w-branch only and raise
    BuildInProgress, blocking the merge.
    """
    OLD_W = 'w/4.3/bugfix/zenko-ui-bump'
    NEW_W = 'w/4.3/bugfix/zenko-ui-4.3.3'

    runs_data = [
        # Old w-branch: push run completed successfully (before rename)
        _make_run(run_id=10, sha=SHARED_SHA, branch=OLD_W,
                  status='completed', conclusion='success', workflow_id=1),
        # New w-branch: push run triggered by the rename, still in_progress
        _make_run(run_id=11, sha=SHARED_SHA, branch=NEW_W,
                  status='in_progress', conclusion=None, workflow_id=1),
    ]
    job = _make_job()
    job.project_repo.get_commit_status.return_value = _make_combined(
        client, runs_data)
    job.project_repo.get_build_url.return_value = ''
    job.project_repo.get_commit_url.return_value = ''

    wbranches = [_make_wbranch(NEW_W, SHARED_SHA)]

    with pytest.raises(messages.BuildInProgress):
        revalidate_build_status(job, wbranches)


def test_non_github_actions_status_fallback_to_state(client):
    """Exercise the else-branch: raw_status has no state_for_branch.

    This covers the fallback path in revalidate_build_status for hosts or
    build keys that return a plain status object (e.g. a classic GitHub
    commit-status context) without the state_for_branch method.
    """
    from types import SimpleNamespace

    for state, exc in [
        ('INPROGRESS', messages.BuildInProgress),
        ('FAILED', messages.BuildFailed),
        ('NOTSTARTED', messages.BuildNotStarted),
    ]:
        job = _make_job()
        raw_status = SimpleNamespace(state=state)
        combined = MagicMock()
        combined.status = {'github_actions': raw_status}
        job.project_repo.get_commit_status.return_value = combined
        job.project_repo.get_build_url.return_value = ''
        job.project_repo.get_commit_url.return_value = ''

        wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

        with pytest.raises(exc):
            revalidate_build_status(job, wbranches)


def test_non_github_actions_status_successful_passes():
    """Fallback path: SUCCESSFUL state must not raise."""
    from types import SimpleNamespace

    job = _make_job()
    raw_status = SimpleNamespace(state='SUCCESSFUL')
    combined = MagicMock()
    combined.status = {'github_actions': raw_status}
    job.project_repo.get_commit_status.return_value = combined

    wbranches = [_make_wbranch(W_BRANCH, SHARED_SHA)]

    revalidate_build_status(job, wbranches)


def test_artesca5155_old_aggregator_would_have_passed(client):
    """Document that the old aggregator (AggregatedWorkflowRuns.state) returns
    SUCCESSFUL for the artesca#5155 shape, confirming the bug that made the
    incident possible.
    """
    OLD_W = 'w/4.3/bugfix/zenko-ui-bump'
    NEW_W = 'w/4.3/bugfix/zenko-ui-4.3.3'

    data = {
        'total_count': 2,
        'workflow_runs': [
            _make_run(run_id=10, sha=SHARED_SHA, branch=OLD_W,
                      status='completed', conclusion='success', workflow_id=1),
            _make_run(run_id=11, sha=SHARED_SHA, branch=NEW_W,
                      status='in_progress', conclusion=None, workflow_id=1),
        ],
    }
    runs = AggregatedWorkflowRuns(client, **data)
    # The old .state property would return SUCCESSFUL here — this is the bug.
    assert runs.state == 'SUCCESSFUL'
