"""Status comments are edited in place instead of being re-posted."""
from types import SimpleNamespace

import pytest

from bert_e import exceptions
from bert_e.workflow import pr_utils


class FakeComment:
    def __init__(self, author, text, editable=True):
        self.author = author
        self.text = text
        self.editable = editable

    def edit(self, msg):
        if not self.editable:
            raise NotImplementedError
        self.text = msg


class FakePR:
    def __init__(self, editable=True):
        self.comments = []
        self.editable = editable

    def add_comment(self, msg):
        self.comments.append(FakeComment('bert-e', msg, self.editable))


@pytest.fixture
def settings():
    return SimpleNamespace(no_comment=False, interactive=False,
                           robot='bert-e')


def _send(settings, pr, msg, exc_cls):
    pr_utils._send_comment(settings, pr, msg,
                           exc_cls.dont_repeat_if_in_history,
                           updatable=exc_cls.updatable)


def test_updatable_classes():
    assert exceptions.ResetComplete.updatable
    assert exceptions.BranchHistoryMismatch.updatable
    assert exceptions.IncorrectFixVersion.updatable
    assert exceptions.IntegrationDataCreated.updatable
    assert not exceptions.HelpMessage.updatable
    assert not exceptions.StatusReport.updatable


def test_status_comment_is_updated(settings):
    pr = FakePR()
    _send(settings, pr, 'reset', exceptions.ResetComplete)
    _send(settings, pr, 'history mismatch', exceptions.BranchHistoryMismatch)
    assert len(pr.comments) == 1
    assert pr.comments[0].text.startswith('history mismatch')
    assert pr.comments[0].text.endswith(pr_utils.STATUS_MARKER)


def test_identical_status_not_reposted(settings):
    pr = FakePR()
    _send(settings, pr, 'reset', exceptions.ResetComplete)
    with pytest.raises(exceptions.CommentAlreadyExists):
        _send(settings, pr, 'reset', exceptions.ResetComplete)
    assert len(pr.comments) == 1


def test_non_updatable_message_is_posted(settings):
    pr = FakePR()
    _send(settings, pr, 'reset', exceptions.ResetComplete)
    _send(settings, pr, 'help', exceptions.HelpMessage)
    assert len(pr.comments) == 2
    assert pr_utils.STATUS_MARKER not in pr.comments[1].text


def test_fallback_when_edit_unsupported(settings):
    pr = FakePR(editable=False)
    _send(settings, pr, 'reset', exceptions.ResetComplete)
    _send(settings, pr, 'other', exceptions.BranchHistoryMismatch)
    assert len(pr.comments) == 2


def test_other_authors_comments_untouched(settings):
    pr = FakePR()
    pr.comments.append(FakeComment('someone', 'hi ' + pr_utils.STATUS_MARKER))
    _send(settings, pr, 'reset', exceptions.ResetComplete)
    assert len(pr.comments) == 2
    assert pr.comments[0].text.startswith('hi')
