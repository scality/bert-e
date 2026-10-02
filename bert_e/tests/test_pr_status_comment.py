"""Tests of the pinned status comment maintained by notify_user."""
from types import SimpleNamespace

from bert_e import exceptions
from bert_e.workflow.pr_utils import (
    STATUS_COMMENT_MARKER, find_comment, find_status_comment, notify_user,
    update_status_comment,
)


class FakeComment:
    def __init__(self, author, text):
        self.author = author
        self.text = text

    def edit(self, text):
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
    src = SimpleNamespace(name='x')
    dst = SimpleNamespace(name='development/1.1', allow_prefixes=['feature'])
    return exceptions.IncompatibleSourceBranchPrefix(
        active_options=[], source=src, destination=dst)


def test_status_comment_created_once_and_updated():
    pr = FakePR()
    err = _conflict()
    notify_user(SETTINGS, pr, err)
    assert len(pr.comments) == 2
    # the pinned status comment comes first
    assert pr.comments[0] is find_status_comment(pr, 'bert-e')
    assert 'IncompatibleSourceBranchPrefix' in pr.comments[0].text

    other = exceptions.MissingJiraId(
        active_options=[], source_branch='x', dest_branch='b')
    update_status_comment(SETTINGS, pr, other)
    assert len(pr.comments) == 2
    assert 'MissingJiraId' in pr.comments[0].text


def test_informational_message_leaves_status_untouched():
    pr = FakePR()
    update_status_comment(SETTINGS, pr, _conflict())
    before = pr.comments[0].text
    update_status_comment(SETTINGS, pr, exceptions.HelpMessage(
        options={}, commands={}, active_options=[]))
    assert pr.comments[0].text == before


def test_find_comment_skips_status_comment():
    pr = FakePR()
    pr.add_comment('hello')
    pr.add_comment(STATUS_COMMENT_MARKER + ' status')
    assert find_comment(pr, 'bert-e', 'hello', -1) is pr.comments[0]


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
