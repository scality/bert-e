"""Unit tests for ``check_approvals`` covering the bot-author / assignee rule.

The bot-author branch is exercised directly with lightweight stubs rather than
through the full integration harness so the rule can be tested in isolation.
"""
from types import SimpleNamespace

import pytest

from bert_e import exceptions as messages
from bert_e.lib.settings_dict import SettingsDict
from bert_e.workflow.gitwaterflow import check_approvals


class StubPullRequest:
    def __init__(self, author, assignees=(), approvals=(), participants=(),
                 change_requests=(), author_is_bot=False):
        self.id = 1
        self.author = author
        self._assignees = list(assignees)
        self._approvals = list(approvals)
        self._participants = list(participants) or list(approvals)
        self._change_requests = list(change_requests)
        self._author_is_bot = author_is_bot

    @property
    def assignees(self):
        return list(self._assignees)

    @property
    def author_is_bot(self):
        return self._author_is_bot

    def get_approvals(self):
        return list(self._approvals)

    def get_participants(self):
        return list(self._participants)

    def get_change_requests(self):
        return list(self._change_requests)


def make_job(pull_request, *, approving_users=None, approve=False,
             need_author_approval=True, required_peer_approvals=2,
             required_leader_approvals=0, project_leaders=(),
             bot_authors=(), bypass_peer_approval=False,
             bypass_leader_approval=False, bypass_author_approval=False,
             unanimity=False, robot='bert-e', admins=()):
    base_settings = {
        'robot': robot,
        'admins': list(admins),
        'project_leaders': list(project_leaders),
        'required_peer_approvals': required_peer_approvals,
        'required_leader_approvals': required_leader_approvals,
        'need_author_approval': need_author_approval,
        'bot_authors': list(bot_authors),
        'pr_author_options': {},
        'unanimity': unanimity,
        'approve': approve,
        # Per-comment bypass flags are read off settings via util helpers.
        'bypass_peer_approval': bypass_peer_approval,
        'bypass_leader_approval': bypass_leader_approval,
        'bypass_author_approval': bypass_author_approval,
        'bypass_jira_check': False,
        'bypass_build_status': False,
        'bypass_commit_size': False,
        'bypass_incompatible_branch': False,
    }
    settings = SettingsDict(base_settings)

    job = SimpleNamespace(
        pull_request=pull_request,
        settings=settings,
        approving_users=set(approving_users or set()),
        author_bypass={},
        active_options=[],
    )
    return job


def test_non_bot_author_unchanged():
    """Existing flow: a regular contributor PR works as before."""
    pr = StubPullRequest(
        author='alice',
        approvals=['alice', 'bob', 'carol'],
    )
    job = make_job(pr, approve=True, required_peer_approvals=2)
    # alice (author) approved via /approve, bob+carol provide 2 peer approvals.
    check_approvals(job)


def test_bot_author_blocked_without_assignee():
    """Bot-authored PR with no assignee can never satisfy approval."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=[],
        approvals=['bob', 'carol'],
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=2)
    with pytest.raises(messages.ApprovalRequired) as exc:
        check_approvals(job)
    assert 'assignee' in exc.value.msg
    assert 'bot account' in exc.value.msg


def test_bot_author_blocked_when_assignee_only_native_approves():
    """Native review approval from the assignee is not enough; /approve must
    be issued explicitly."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        approvals=['alice', 'bob', 'carol'],  # alice clicked native Approve
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=2, approving_users=set())
    with pytest.raises(messages.ApprovalRequired):
        check_approvals(job)


def test_bot_author_passes_when_assignee_slash_approves():
    """Assignee /approve plus enough peer approvals lets it through."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        approvals=['bob', 'carol'],
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=2,
                   approving_users={'alice'})
    # No exception => approved.
    check_approvals(job)


def test_bot_author_assignee_excluded_from_peer_count():
    """Even if the assignee leaves a native approval, that does not count
    toward required_peer_approvals."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        approvals=['alice', 'bob'],  # alice native + bob peer
        author_is_bot=True,
    )
    job = make_job(
        pr,
        required_peer_approvals=2,
        approving_users={'alice'},  # assignee /approve'd
    )
    # alice's approval is excluded; only bob counts as a peer => 1 < 2
    with pytest.raises(messages.ApprovalRequired):
        check_approvals(job)


def test_bot_detected_via_settings_list_only():
    """Detection via bot_authors list, even when author_is_bot is False."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        approvals=['bob', 'carol'],
        author_is_bot=False,  # GitHub doesn't tag this user as Bot.
    )
    job = make_job(
        pr,
        required_peer_approvals=2,
        bot_authors=['eve-scality'],
        approving_users={'alice'},
    )
    check_approvals(job)


def test_bot_detected_via_api_only():
    """Detection via author_is_bot flag, even when bot_authors is empty."""
    pr = StubPullRequest(
        author='dependabot[bot]',
        assignees=['alice'],
        approvals=['bob', 'carol'],
        author_is_bot=True,
    )
    job = make_job(
        pr,
        required_peer_approvals=2,
        bot_authors=[],
        approving_users={'alice'},
    )
    check_approvals(job)


def test_bot_author_any_assignee_suffices():
    """When there are multiple assignees, any single /approve is enough."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice', 'dan'],
        approvals=['bob', 'carol'],
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=2,
                   approving_users={'dan'})  # only one of two approves
    check_approvals(job)


def test_bot_author_message_lists_assignees():
    """The assignees should be surfaced in the rendered message so reviewers
    know who must /approve."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice', 'dan'],
        approvals=[],
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=0)
    with pytest.raises(messages.ApprovalRequired) as exc:
        check_approvals(job)
    assert '@alice' in exc.value.msg
    assert '@dan' in exc.value.msg
    # The author-approval bullet should not be rendered for bot-authored PRs.
    assert '* the author' not in exc.value.msg


def test_bot_author_with_admin_bypass():
    """An admin-issued /bypass_author_approval still works for bot PRs."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=[],
        approvals=['bob', 'carol'],
        author_is_bot=True,
    )
    job = make_job(pr, required_peer_approvals=2,
                   bypass_author_approval=True)
    check_approvals(job)
