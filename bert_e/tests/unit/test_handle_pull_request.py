"""Unit tests for gitwaterflow.handle_pull_request routing."""
from types import SimpleNamespace
from unittest.mock import patch

from bert_e.workflow.gitwaterflow import handle_pull_request


class _FakeRepo:
    def __init__(self):
        self._url = ''
        self._remote_branches = {}

    def cmd(self, *args, **kwargs):
        return ''


def _make_job(author, src_branch):
    """Return a minimal PullRequestJob stub."""
    pull_request = SimpleNamespace(
        author=author,
        src_branch=src_branch,
        id=5171,
    )
    settings = SimpleNamespace(robot=author)
    bert_e = SimpleNamespace(settings=settings)
    git = SimpleNamespace(cascade=None, repo=_FakeRepo())
    return SimpleNamespace(
        pull_request=pull_request,
        settings=settings,
        bert_e=bert_e,
        git=git,
    )


def test_robot_authored_integration_branch_routes_to_parent():
    """A PR authored by the robot on a w/... branch must be routed to
    handle_parent_pull_request — it's an integration PR."""
    job = _make_job(author='bert-e',
                    src_branch='w/4.2/improvement/ARTESCA-17563-something')

    with patch('bert_e.workflow.gitwaterflow.handle_parent_pull_request') as mock_parent:
        handle_pull_request(job)
        mock_parent.assert_called_once_with(job, job.pull_request)


def test_robot_authored_feature_branch_does_not_route_to_parent():
    """A PR authored by the robot on a feature/... branch (e.g. a CID bump)
    must NOT be routed to handle_parent_pull_request.

    Regression: bert-e was crashing with 404 on bump PRs because it extracted
    the first number in the description (a Jira ticket ID) and tried to fetch
    a non-existent parent PR.
    """
    job = _make_job(author='bert-e',
                    src_branch='feature/ARTESCA-17576-bump-identity-ui-0.41.0')

    with patch('bert_e.workflow.gitwaterflow.handle_parent_pull_request') as mock_parent, \
         patch('bert_e.workflow.gitwaterflow._handle_pull_request') as mock_handle:
        handle_pull_request(job)
        mock_parent.assert_not_called()
        mock_handle.assert_called_once_with(job)
