"""Tests of the pinned status comment maintained by notify_user."""
from types import SimpleNamespace

from bert_e import exceptions
from bert_e.workflow.pr_utils import (
    find_status_comment, notify_user, update_status_comment,
)


class FakeComment:
    def __init__(self, author, text):
        self.author = author
        self.text = text

    def update(self, text):
        self.text = text


class FakePR:
    def __init__(self):
        self.comments = []

    def add_comment(self, msg):
        self.comments.append(FakeComment('bert-e', msg))

    def set_bot_status(self, *args, **kwargs):
        pass


SETTINGS = SimpleNamespace(robot='bert-e', no_comment=False,
                           interactive=False, send_bot_status=False)


def _conflict():
    return exceptions.CommandNotImplemented(active_options=[])


def test_status_comment_created_once_and_updated():
    pr = FakePR()
    err = _conflict()
    notify_user(SETTINGS, pr, err)
    assert len(pr.comments) == 2
    # the pinned status comment comes first
    assert pr.comments[0] is find_status_comment(pr, 'bert-e')
    assert 'CommandNotImplemented' in pr.comments[0].text

    other = exceptions.HelpMessage(
        options={}, commands={}, active_options=[])
    update_status_comment(SETTINGS, pr, other)
    assert len(pr.comments) == 2
    assert 'HelpMessage' in pr.comments[0].text


def test_integration_prs_kept_between_updates():
    pr = FakePR()
    child = SimpleNamespace(id=7, src_branch='w/1.1/x',
                            dst_branch='development/1.1')
    err = _conflict()
    err.kwargs['child_prs'] = [child]
    update_status_comment(SETTINGS, pr, err)
    assert '#7' in pr.comments[0].text
    update_status_comment(SETTINGS, pr, _conflict())
    assert '#7' in pr.comments[0].text


def test_no_comment_setting_skips():
    pr = FakePR()
    settings = SimpleNamespace(**{**vars(SETTINGS), 'no_comment': True})
    update_status_comment(settings, pr, _conflict())
    assert pr.comments == []
