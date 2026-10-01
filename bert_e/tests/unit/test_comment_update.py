from types import SimpleNamespace

import pytest

from bert_e import exceptions
from bert_e.workflow import pr_utils


class FakeComment:
    def __init__(self, author, text, can_update=True):
        self.author = author
        self.text = text
        self.can_update = can_update

    def edit(self, text):
        if not self.can_update:
            raise NotImplementedError
        self.text = text


class FakePR:
    def __init__(self, can_update=True):
        self.comments = []
        self.can_update = can_update

    def add_comment(self, msg):
        self.comments.append(FakeComment('bert-e', msg, self.can_update))


@pytest.fixture
def settings():
    return SimpleNamespace(no_comment=False, interactive=False,
                           robot='bert-e')


def send(settings, pr, msg, update=True):
    pr_utils._send_comment(settings, pr, msg, 0, update)


def test_status_comment_is_updated_in_place(settings):
    pr = FakePR()
    send(settings, pr, 'history conflict')
    send(settings, pr, 'reset complete')
    assert len(pr.comments) == 1
    assert pr.comments[0].text.endswith('reset complete')
    assert pr.comments[0].text.startswith(pr_utils.STATUS_MARKER)


def test_status_comment_updated_even_after_other_comments(settings):
    pr = FakePR()
    send(settings, pr, 'status 1')
    pr.comments.append(FakeComment('bert-e', 'approved'))
    send(settings, pr, 'status 2')
    assert len(pr.comments) == 2
    assert pr.comments[0].text.endswith('status 2')


def test_identical_status_raises(settings):
    pr = FakePR()
    send(settings, pr, 'same')
    with pytest.raises(exceptions.CommentAlreadyExists):
        send(settings, pr, 'same')


def test_other_authors_comments_are_not_edited(settings):
    pr = FakePR()
    pr.comments.append(
        FakeComment('someone', pr_utils.STATUS_MARKER + '\nfoo'))
    send(settings, pr, 'status')
    assert len(pr.comments) == 2
    assert pr.comments[0].text.endswith('foo')


def test_regular_comments_are_not_updated(settings):
    pr = FakePR()
    send(settings, pr, 'a', update=False)
    send(settings, pr, 'b', update=False)
    assert [c.text for c in pr.comments] == ['a', 'b']


def test_fallback_when_host_cannot_edit(settings):
    pr = FakePR(can_update=False)
    send(settings, pr, 'a')
    send(settings, pr, 'b')
    assert len(pr.comments) == 2
