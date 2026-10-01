"""Transient status messages edit the previous status comment."""
from types import SimpleNamespace

import pytest

from bert_e import exceptions
from bert_e.workflow import pr_utils
from bert_e.workflow.pr_utils import STATUS_MARKER, notify_user


class FakeComment:
    def __init__(self, author, text, editable=True):
        self.author = author
        self.text = text
        self.editable = editable

    def update(self, msg):
        if not self.editable:
            raise NotImplementedError
        self.text = msg


class FakePR:
    def __init__(self, editable=True):
        self.comments = []
        self.editable = editable

    def add_comment(self, msg):
        self.comments.append(FakeComment('bert-e', msg, self.editable))

    def set_bot_status(self, *args, **kwargs):
        pass


@pytest.fixture
def settings():
    return SimpleNamespace(robot='bert-e', no_comment=False,
                           interactive=False, send_bot_status=False)


class FakeStatus(Exception):
    status = None
    title = 'title'
    dont_repeat_if_in_history = 0
    updatable = True

    def __init__(self, text):
        super().__init__(text)
        self.text = text

    def __str__(self):
        return self.text


def test_updatable_flag():
    assert exceptions.BranchHistoryMismatch.updatable
    assert exceptions.Conflict.updatable
    assert not exceptions.HelpMessage.updatable
    assert not exceptions.SuccessMessage.updatable


def test_status_comment_is_edited_in_place(settings):
    pr = FakePR()
    pr_utils._send_comment(settings, pr, 'first', 0, updatable=True)
    pr_utils._send_comment(settings, pr, 'second', 0, updatable=True)
    assert len(pr.comments) == 1
    assert pr.comments[0].text == f'second\n{STATUS_MARKER}'


def test_same_status_is_not_republished(settings):
    pr = FakePR()
    pr_utils._send_comment(settings, pr, 'same', 0, updatable=True)
    with pytest.raises(exceptions.CommentAlreadyExists):
        pr_utils._send_comment(settings, pr, 'same', 0, updatable=True)
    assert len(pr.comments) == 1


def test_fallback_to_new_comment_when_edit_unsupported(settings):
    pr = FakePR(editable=False)
    pr_utils._send_comment(settings, pr, 'first', 0, updatable=True)
    pr_utils._send_comment(settings, pr, 'second', 0, updatable=True)
    assert len(pr.comments) == 2


def test_non_updatable_messages_still_create_comments(settings):
    pr = FakePR()
    pr_utils._send_comment(settings, pr, 'one', 0)
    pr_utils._send_comment(settings, pr, 'two', 0)
    assert [c.text for c in pr.comments] == ['one', 'two']


def test_other_authors_comments_are_not_edited(settings):
    pr = FakePR()
    pr.comments.append(FakeComment('someone', f'x\n{STATUS_MARKER}'))
    pr_utils._send_comment(settings, pr, 'new', 0, updatable=True)
    assert len(pr.comments) == 2
    assert pr.comments[0].text == f'x\n{STATUS_MARKER}'


def test_notify_user_uses_exception_flag(settings):
    pr = FakePR()
    notify_user(settings, pr, FakeStatus('history conflict'))
    notify_user(settings, pr, FakeStatus('reset'))
    assert len(pr.comments) == 1
    assert pr.comments[0].text.startswith('reset')


def test_status_comment_not_edited_after_user_comment(settings):
    """Commands posted after the status must still be seen as new."""
    pr = FakePR()
    pr_utils._send_comment(settings, pr, 'first', 0, updatable=True)
    pr.comments.append(FakeComment('user', '@bert-e reset'))
    pr_utils._send_comment(settings, pr, 'second', 0, updatable=True)
    assert len(pr.comments) == 3
    assert pr.comments[0].text == f'first\n{STATUS_MARKER}'
