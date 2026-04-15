"""Unit tests for check_fix_versions and _notify_pending_hotfix_if_needed.

Rules:
- Hotfix branch PRs require the exact 4-digit fix version in Jira
  (e.g. "10.0.0.0" pre-GA, "10.0.0.1" first post-GA hotfix, …).
  3-digit aliases (e.g. "10.0.0") are NOT accepted.
- Development-branch PRs may have an extra 4-digit "X.Y.Z.0" entry in
  the ticket when a pre-GA hotfix branch exists alongside the waterflow.
  That entry is consumed by the separate cherry-pick PR to the hotfix
  branch and must not cause the dev-branch check to fail.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bert_e import exceptions
from bert_e.workflow.gitwaterflow.jira import (
    check_fix_versions,
    _notify_pending_hotfix_if_needed,
)


def _make_issue(*version_names):
    versions = [SimpleNamespace(name=v) for v in version_names]
    return SimpleNamespace(
        key='TEST-00001',
        fields=SimpleNamespace(fixVersions=versions),
    )


def _make_job(*target_versions, phantom_hotfix_versions=None):
    cascade = SimpleNamespace(
        target_versions=list(target_versions),
        phantom_hotfix_versions=phantom_hotfix_versions or set(),
    )
    git = SimpleNamespace(cascade=cascade)
    return SimpleNamespace(git=git, active_options=[])


# ---------------------------------------------------------------------------
# Hotfix branch PRs — exact 4-digit version required
# ---------------------------------------------------------------------------

def test_pre_ga_hotfix_accepts_four_digit_version():
    """'10.0.0.0' in Jira is accepted for pre-GA hotfix/10.0.0."""
    check_fix_versions(_make_job('10.0.0.0'), _make_issue('10.0.0.0'))


def test_pre_ga_hotfix_rejects_three_digit_version():
    """'10.0.0' alone is NOT accepted — only 4-digit '10.0.0.0' is valid."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue('10.0.0'))


def test_pre_ga_hotfix_rejects_empty_versions():
    """No fix version in Jira is rejected for pre-GA hotfix/10.0.0."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue())


def test_pre_ga_hotfix_rejects_wrong_version():
    """Unrelated version is rejected for pre-GA hotfix/10.0.0."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue('9.5.0'))


def test_post_ga_hotfix_accepts_correct_4digit():
    """'10.0.0.1' in Jira is accepted for post-GA hotfix (hfrev=1)."""
    check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0.1'))


def test_post_ga_hotfix_rejects_pre_ga_version():
    """'10.0.0.0' is NOT accepted once GA tag exists (target is '10.0.0.1')."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0.0'))


def test_post_ga_hotfix_rejects_3digit_base():
    """'10.0.0' is NOT accepted for post-GA hotfix (target is '10.0.0.1')."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0'))


def test_post_ga_second_hotfix():
    """'10.0.0.2' in Jira is accepted for second post-GA hotfix (hfrev=2)."""
    check_fix_versions(_make_job('10.0.0.2'), _make_issue('10.0.0.2'))


# ---------------------------------------------------------------------------
# Development-branch PRs — phantom hotfix version excluded from check
# ---------------------------------------------------------------------------

def test_dev_pr_phantom_hotfix_excluded_from_check():
    """Ticket with 9.5.3 + 10.0.0.0 + 10.1.0 passes the dev/9.5 PR check.

    The 10.0.0.0 entry belongs to the pre-GA hotfix branch and is consumed
    by the separate cherry-pick PR.  It must not cause a mismatch here.
    """
    job = _make_job('9.5.3', '10.1.0',
                    phantom_hotfix_versions={'10.0.0.0'})
    issue = _make_issue('9.5.3', '10.0.0.0', '10.1.0')
    check_fix_versions(job, issue)  # must not raise


def test_dev_pr_phantom_hotfix_still_requires_all_dev_versions():
    """Missing dev version still fails even when phantom is excluded."""
    job = _make_job('9.5.3', '10.1.0',
                    phantom_hotfix_versions={'10.0.0.0'})
    issue = _make_issue('9.5.3', '10.0.0.0')  # missing 10.1.0
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(job, issue)


def test_dev_pr_no_phantom_rejects_unexpected_4digit_version():
    """Without a phantom hotfix, X.Y.Z.0 in the ticket causes a mismatch."""
    job = _make_job('9.5.3', '10.1.0',
                    phantom_hotfix_versions=set())
    issue = _make_issue('9.5.3', '10.0.0.0', '10.1.0')
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(job, issue)


def test_dev_pr_without_hotfix_version_passes():
    """Dev PR still passes when the ticket has exactly the dev versions."""
    job = _make_job('9.5.3', '10.1.0',
                    phantom_hotfix_versions={'10.0.0.0'})
    issue = _make_issue('9.5.3', '10.1.0')
    check_fix_versions(job, issue)  # must not raise


# ---------------------------------------------------------------------------
# Regular dev-branch PR (no phantom hotfixes) — pre-existing behaviour
# ---------------------------------------------------------------------------

def test_dev_branch_accepts_matching_versions():
    """Standard 3-digit dev-branch version check still works."""
    check_fix_versions(
        _make_job('4.3.19', '5.1.4'),
        _make_issue('4.3.19', '5.1.4'),
    )


def test_dev_branch_rejects_mismatch():
    """Wrong versions for a dev-branch PR are still rejected."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(
            _make_job('4.3.19', '5.1.4'),
            _make_issue('4.3.18', '5.1.4'),
        )


# ---------------------------------------------------------------------------
# _notify_pending_hotfix_if_needed — dedup behaviour
# ---------------------------------------------------------------------------

def _make_notify_job(phantom_hotfix_versions=None):
    """Build a minimal job for _notify_pending_hotfix_if_needed tests."""
    cascade = SimpleNamespace(
        phantom_hotfix_versions=phantom_hotfix_versions or set(),
    )
    settings = SimpleNamespace(robot='bert-e')
    return SimpleNamespace(
        git=SimpleNamespace(cascade=cascade),
        settings=settings,
        pull_request=MagicMock(),
        active_options=[],
    )


@patch('bert_e.workflow.gitwaterflow.jira.notify_user')
@patch('bert_e.workflow.gitwaterflow.jira.find_comment', return_value=None)
def test_pending_hotfix_posts_when_not_yet_in_history(mock_find, mock_notify):
    """Reminder is posted when no previous comment with that title exists."""
    job = _make_notify_job(phantom_hotfix_versions={'10.0.0.0'})
    issue = _make_issue('9.5.3', '10.0.0.0', '10.1.0')
    _notify_pending_hotfix_if_needed(job, issue)
    mock_notify.assert_called_once()


@patch('bert_e.workflow.gitwaterflow.jira.notify_user')
@patch('bert_e.workflow.gitwaterflow.jira.find_comment',
       return_value=MagicMock())
def test_pending_hotfix_skips_when_already_in_history(mock_find, mock_notify):
    """Reminder is NOT posted when a previous comment with that title exists.

    This covers the active_options footer dedup fix: even if active_options
    changed between runs (making the full text differ), the title-prefix
    check prevents a second post.
    """
    job = _make_notify_job(phantom_hotfix_versions={'10.0.0.0'})
    issue = _make_issue('9.5.3', '10.0.0.0', '10.1.0')
    _notify_pending_hotfix_if_needed(job, issue)
    mock_notify.assert_not_called()
