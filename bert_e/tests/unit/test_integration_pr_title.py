"""Unit tests for integration PR title sanitisation.

GitHub's PR API returns a 422 Unprocessable Entity when the title contains
newline characters. A parent PR whose title was set from a multi-line commit
message (e.g. "My feature\n* fix something") would propagate the newline into
the integration PR title and trigger that error (PTFE-3249).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bert_e.workflow.gitwaterflow.branches import (
    DevelopmentBranch, IntegrationBranch,
)
from bert_e.tests.unit.helpers import FakeRepo


def _make_integration_branch(name='w/5.3/bugfix/PTFE-3249-test'):
    repo = FakeRepo()
    dst = DevelopmentBranch(repo, 'development/5.3')
    branch = IntegrationBranch(repo, name)
    branch.dst_branch = dst
    return branch


def _make_parent_pr(title, pr_id=4910):
    return SimpleNamespace(id=pr_id, title=title)


def _capture_create_pr_title(branch, parent_pr):
    """Call get_or_create_pull_request and return the title passed to
    create_pull_request."""
    captured = {}

    def fake_create_pull_request(title, **kwargs):
        captured['title'] = title
        return MagicMock()

    project_repo = MagicMock()
    project_repo.create_pull_request.side_effect = fake_create_pull_request

    with patch('bert_e.workflow.gitwaterflow.branches.render',
               return_value=''):
        branch.get_or_create_pull_request(
            parent_pr, open_prs=[], bitbucket_repo=project_repo)

    assert 'title' in captured, "create_pull_request was never called"
    return captured['title']


# ---------------------------------------------------------------------------
# Tests that document the expected (fixed) behaviour
# ---------------------------------------------------------------------------

def test_newline_in_parent_title_is_stripped():
    """A \\n in parent PR title must not appear in the integration PR title.

    This is the core regression: GitHub returns 422 when a PR title contains
    newline characters.
    """
    branch = _make_integration_branch()
    parent = _make_parent_pr('Add feature X\n* fix something\n* clean up')

    title = _capture_create_pr_title(branch, parent)

    assert '\n' in parent.title, "pre-condition: parent title has newline"
    assert '\n' not in title


def test_carriage_return_in_parent_title_is_stripped():
    """\\r in the parent PR title must also be removed."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('Add feature\r\n* with asterisk')

    title = _capture_create_pr_title(branch, parent)

    assert '\r' not in title
    assert '\n' not in title


def test_asterisk_without_newline_is_preserved():
    """A bare * in the title (without a newline) must be kept as-is."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('Fix * wildcard handling in parser')

    title = _capture_create_pr_title(branch, parent)

    assert '*' in title


def test_clean_title_is_unchanged():
    """A title with no special characters must pass through unmodified."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('Add feature X')

    title = _capture_create_pr_title(branch, parent)

    assert title == 'INTEGRATION [PR#4910 > development/5.3] Add feature X'


def test_integration_prefix_is_present():
    """The INTEGRATION prefix and branch info must always be in the title."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('Some PR title\n* extra line')

    title = _capture_create_pr_title(branch, parent)

    assert title.startswith('INTEGRATION [PR#4910 > development/5.3]')


def test_trailing_newline_does_not_produce_trailing_space():
    """A title ending with \\n must not leave a trailing space."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('Add feature X\n')

    title = _capture_create_pr_title(branch, parent)

    assert not title.endswith(' ')


def test_newlines_only_title_does_not_produce_trailing_space():
    """A pathological title consisting entirely of newlines must not leave a
    trailing space in the final integration PR title."""
    branch = _make_integration_branch()
    parent = _make_parent_pr('\n\n\n')

    title = _capture_create_pr_title(branch, parent)

    assert not title.endswith(' ')
