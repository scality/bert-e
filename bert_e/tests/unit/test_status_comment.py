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
