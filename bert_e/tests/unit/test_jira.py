"""Unit tests for check_fix_versions in jira.py.

Covers the pre-GA hotfix dual-acceptance rule:
  - When the hotfix branch has no GA tag yet (hfrev == 0 → target ends
    in ".0"), both the 4-digit form ("10.0.0.0") AND the 3-digit base
    ("10.0.0") must be accepted.
  - Once the GA tag is pushed (hfrev advances to 1 → target becomes
    "10.0.0.1"), only the exact 4-digit version is accepted again.
"""
import pytest
from types import SimpleNamespace

from bert_e import exceptions
from bert_e.workflow.gitwaterflow.jira import check_fix_versions


def _make_issue(*version_names):
    versions = [SimpleNamespace(name=v) for v in version_names]
    return SimpleNamespace(
        key='TEST-00001',
        fields=SimpleNamespace(fixVersions=versions),
    )


def _make_job(*target_versions):
    cascade = SimpleNamespace(target_versions=list(target_versions))
    git = SimpleNamespace(cascade=cascade)
    return SimpleNamespace(git=git, active_options=[])


# ---------------------------------------------------------------------------
# Pre-GA hotfix: target ends in ".0" (hfrev == 0, no GA tag yet)
# ---------------------------------------------------------------------------

def test_pre_ga_hotfix_accepts_four_digit_version():
    """Jira with '10.0.0.0' is accepted for pre-GA hotfix/10.0.0."""
    check_fix_versions(_make_job('10.0.0.0'), _make_issue('10.0.0.0'))


def test_pre_ga_hotfix_accepts_three_digit_version():
    """Jira with '10.0.0' is accepted for pre-GA hotfix/10.0.0 (no GA tag)."""
    check_fix_versions(_make_job('10.0.0.0'), _make_issue('10.0.0'))


def test_pre_ga_hotfix_accepts_three_digit_among_others():
    """Jira with '10.0.0' among other versions is still accepted."""
    check_fix_versions(
        _make_job('10.0.0.0'),
        _make_issue('9.5.3', '10.0.0', '11.0.0'),
    )


def test_pre_ga_hotfix_rejects_wrong_version():
    """Unrelated version is rejected for pre-GA hotfix/10.0.0."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue('9.5.0'))


def test_pre_ga_hotfix_rejects_empty_versions():
    """No fix version in Jira is rejected for pre-GA hotfix/10.0.0."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue())


def test_pre_ga_hotfix_rejects_next_micro():
    """'10.0.1' is not a valid substitute for pre-GA '10.0.0.0'."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.0'), _make_issue('10.0.1'))


# ---------------------------------------------------------------------------
# Post-GA hotfix: target does NOT end in ".0" (hfrev >= 1, GA tag exists)
# ---------------------------------------------------------------------------

def test_post_ga_hotfix_accepts_correct_4digit():
    """'10.0.0.1' in Jira is accepted for post-GA hotfix (hfrev=1)."""
    check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0.1'))


def test_post_ga_hotfix_rejects_3digit_base():
    """'10.0.0' is NOT accepted once GA tag exists (target is '10.0.0.1')."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0'))


def test_post_ga_hotfix_rejects_pre_ga_4digit():
    """'10.0.0.0' is NOT accepted once GA tag exists (target is '10.0.0.1')."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.1'), _make_issue('10.0.0.0'))


def test_post_ga_second_hotfix():
    """'10.0.0.2' in Jira is accepted for second post-GA hotfix (hfrev=2)."""
    check_fix_versions(_make_job('10.0.0.2'), _make_issue('10.0.0.2'))


def test_post_ga_hotfix_rejects_lower_hfrev():
    """'10.0.0.1' is NOT accepted when target is '10.0.0.2'."""
    with pytest.raises(exceptions.IncorrectFixVersion):
        check_fix_versions(_make_job('10.0.0.2'), _make_issue('10.0.0.1'))


# ---------------------------------------------------------------------------
# Regular dev-branch PR (not hotfix) — pre-existing behaviour unchanged
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
