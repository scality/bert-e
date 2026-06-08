"""Unit tests for ``handle_comments`` covering the new author/assignee
authorization for `/approve` and the per-user tracking of /approve calls.
"""
from types import SimpleNamespace

import pytest

from bert_e import exceptions as messages
from bert_e.lib.settings_dict import SettingsDict
from bert_e.workflow.gitwaterflow import handle_comments
from bert_e.workflow.gitwaterflow.commands import setup as setup_commands


# Ensure all gitwaterflow options (including /approve with assigned=True)
# are registered exactly once for the whole module.
setup_commands()


class StubComment:
    def __init__(self, author, text):
        self.author = author
        self.text = text


class StubPullRequest:
    def __init__(self, author, assignees, comments):
        self.id = 1
        self.author = author
        self._assignees = list(assignees)
        self.comments = list(comments)

    @property
    def assignees(self):
        return list(self._assignees)


def _make_job(pr, *, robot='bert-e', admins=()):
    settings = SettingsDict({
        'robot': robot,
        'admins': list(admins),
        'pr_author_options': {},
    })
    return SimpleNamespace(
        pull_request=pr,
        settings=settings,
        author_bypass={},
        active_options=[],
    )


def test_assignee_approve_records_comment_author():
    """Assignee posting `/approve` flips the option AND is recorded in
    ``job.approving_users``."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        comments=[StubComment(author='alice', text='/approve')],
    )
    job = _make_job(pr)
    handle_comments(job)
    assert job.settings.approve is True
    assert job.approving_users == {'alice'}


def test_random_user_approve_is_rejected():
    """A non-author / non-assignee using `/approve` raises NotAuthor."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice'],
        comments=[StubComment(author='mallory', text='/approve')],
    )
    job = _make_job(pr)
    with pytest.raises(messages.NotAuthor):
        handle_comments(job)


def test_author_approve_still_works_for_human_author():
    """A human author posting `/approve` is recorded too (existing path)."""
    pr = StubPullRequest(
        author='alice',
        assignees=[],
        comments=[StubComment(author='alice', text='/approve')],
    )
    job = _make_job(pr)
    handle_comments(job)
    assert job.settings.approve is True
    assert job.approving_users == {'alice'}


def test_multiple_assignees_each_recorded():
    """When multiple assignees /approve, all are tracked."""
    pr = StubPullRequest(
        author='eve-scality',
        assignees=['alice', 'dan'],
        comments=[
            StubComment(author='alice', text='/approve'),
            StubComment(author='dan', text='/approve'),
        ],
    )
    job = _make_job(pr)
    handle_comments(job)
    assert job.approving_users == {'alice', 'dan'}
