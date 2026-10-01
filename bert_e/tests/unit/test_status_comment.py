import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from bert_e import exceptions
from bert_e.workflow import pr_utils


class FakeComment:
    def __init__(self, author, text):
        self.author = author
        self.text = text

    def update(self, msg):
        self.text = msg


class FakePR:
    def __init__(self):
        self.comments = []
        self.description = 'original description'

    def add_comment(self, msg):
        self.comments.append(FakeComment('bert-e', msg))

    def set_bot_status(self, *args, **kwargs):
        pass


def settings(**kw):
    base = dict(robot='bert-e', no_comment=False, interactive=False,
                send_bot_status=False, status_comment=True)
    base.update(kw)
    return SimpleNamespace(**base)


def exc(cls=exceptions.QueueConflict, **kw):
    e = MagicMock(spec=cls)
    e.title = cls.__name__
    e.status = None
    e.dont_repeat_if_in_history = 0
    e.__str__ = lambda self: 'details ' + kw.get('t', '')
    return e


def test_status_comment_single_and_updated():
    pr = FakePR()
    s = settings()
    pr_utils.notify_user(s, pr, exc(t='one'))
    pr_utils.notify_user(s, pr, exc(exceptions.Conflict, t='two'))
    status = [c for c in pr.comments
              if c.text.startswith(pr_utils.STATUS_COMMENT_MARKER)]
    assert len(status) == 1
    assert 'details two' in status[0].text
    assert pr.description == 'original description'


def test_status_comment_disabled_by_default():
    pr = FakePR()
    pr_utils.notify_user(settings(status_comment=False), pr, exc())
    assert not any(c.text.startswith(pr_utils.STATUS_COMMENT_MARKER)
                   for c in pr.comments)


def test_status_comment_ignores_other_authors():
    pr = FakePR()
    pr.comments.append(FakeComment(
        'someone', pr_utils.STATUS_COMMENT_MARKER + ' fake'))
    pr_utils.notify_user(settings(), pr, exc())
    assert sum(c.author == 'bert-e' and
               c.text.startswith(pr_utils.STATUS_COMMENT_MARKER)
               for c in pr.comments) == 1


# --- real GitHub / Bitbucket comment classes -------------------------------

def _github_comment(client, body='old'):
    from bert_e.git_host.github import Comment
    return Comment(
        client=client, _validate=False,
        id=1, body=body, url='https://api.github.com/c/1',
        user={'login': 'Bert-E'}, created_at='2020-01-01T00:00:00Z')


def test_github_comment_update_sends_patch_request():
    import json
    from bert_e.git_host.github import Client
    client = Client(login='l', password='p', email='e@o.com')
    client.session = MagicMock()
    client.session.patch.return_value = MagicMock(
        text=json.dumps({'id': 1, 'body': 'new',
                         'url': 'https://api.github.com/c/1',
                         'user': {'login': 'Bert-E'},
                         'created_at': '2020-01-01T00:00:00Z'}))
    comment = _github_comment(client)
    comment.update('new')
    client.session.post.assert_not_called()
    args, kwargs = client.session.patch.call_args
    assert args[0] == 'https://api.github.com/c/1'
    assert json.loads(kwargs['data']) == {'body': 'new'}
    assert comment.text == 'new'
    assert comment.author == 'bert-e'


def test_bitbucket_comment_has_no_update():
    from bert_e.git_host.bitbucket import Comment
    comment = Comment(client=None, _validate=False)
    with pytest.raises(NotImplementedError):
        comment.update('x')


def test_notify_user_without_update_support_still_comments():
    class NoUpdateComment(FakeComment):
        def update(self, msg):
            raise NotImplementedError

    pr = FakePR()
    pr.comments.append(NoUpdateComment(
        'bert-e', pr_utils.STATUS_COMMENT_MARKER + ' stale'))
    pr_utils.notify_user(settings(), pr, exc(t='one'))
    # status was not updated, but the regular comment was still posted
    assert pr.comments[0].text.endswith('stale')
    assert pr.comments[-1].text == 'details one'


# --- interaction with comment deduplication --------------------------------

def test_status_comment_does_not_trigger_dedupe_of_regular_comment():
    pr = FakePR()
    s = settings()
    e = exc(t='one')
    e.dont_repeat_if_in_history = 10
    pr_utils.notify_user(s, pr, e)
    regular = [c for c in pr.comments if c.text == 'details one']
    assert len(regular) == 1
    # repeated notification: regular comment deduped, status stays single
    pr_utils.notify_user(s, pr, e)
    assert len([c for c in pr.comments if c.text == 'details one']) == 1
    assert len([c for c in pr.comments if c.text.startswith(
        pr_utils.STATUS_COMMENT_MARKER)]) == 1


def test_status_comment_updated_even_when_regular_comment_deduped():
    pr = FakePR()
    s = settings()
    e = exc(t='one')
    e.dont_repeat_if_in_history = 10
    pr_utils.notify_user(s, pr, e)
    e2 = exc(exceptions.Conflict, t='one')
    e2.dont_repeat_if_in_history = 10
    pr_utils.notify_user(s, pr, e2)
    status = [c for c in pr.comments
              if c.text.startswith(pr_utils.STATUS_COMMENT_MARKER)]
    assert len(status) == 1
    assert 'Conflict' in status[0].text


def test_find_comment_skips_status_comment_for_regular_lookup():
    pr = FakePR()
    pr_utils.notify_user(settings(), pr, exc(t='one'))
    found = pr_utils.find_comment(pr, 'bert-e', 'details one', 10)
    assert found is not None and found.text == 'details one'
