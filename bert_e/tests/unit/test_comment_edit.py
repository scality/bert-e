"""Unit tests for AbstractComment.edit() on the GitHub and Bitbucket hosts."""
import json

import pytest
import requests_mock
from requests import HTTPError

from bert_e.git_host import base, bitbucket, github


GH_COMMENT_URL = ('https://api.github.com/repos/octo-org/Hello-World/'
                  'issues/comments/42')


def gh_comment(body):
    return {
        'id': 42,
        'body': body,
        'created_at': '2024-01-01T10:00:00Z',
        'updated_at': '2024-01-01T10:05:00Z',
        'user': {'id': 1, 'login': 'Robot_Username'},
        'url': GH_COMMENT_URL,
    }


@pytest.fixture
def gh_client():
    return github.Client(login='robot_username', password='password',
                         email='robot@example.com')


def test_github_comment_edit(gh_client):
    comment = github.Comment.load(gh_comment('old status'))
    comment.client = gh_client
    with requests_mock.Mocker() as mocker:
        mocker.patch(GH_COMMENT_URL, json=gh_comment('new status'))
        comment.edit('new status')

    assert len(mocker.request_history) == 1
    request = mocker.request_history[0]
    # GitHub documents PATCH for comment edition
    assert request.method == 'PATCH'
    assert json.loads(request.text) == {'body': 'new status'}
    assert comment.text == 'new status'
    assert comment.id == 42
    assert comment.author == 'robot_username'


def test_github_comment_edit_http_error(gh_client):
    comment = github.Comment.load(gh_comment('old status'))
    comment.client = gh_client
    with requests_mock.Mocker() as mocker:
        mocker.patch(GH_COMMENT_URL, status_code=404)
        with pytest.raises(HTTPError):
            comment.edit('new status')
    assert comment.text == 'old status'


BB_PR_URL = ('https://api.bitbucket.org/2.0/repositories/'
             'owner/repo/pullrequests/7')
BB_COMMENT_URL = BB_PR_URL + '/comments/42'


def bb_comment(raw, comment_id=42):
    href = BB_PR_URL + '/comments/%d' % comment_id
    return {
        'content': {'raw': raw, 'markup': 'markdown', 'html': raw},
        'created_on': '2024-01-01T10:00:%02d+00:00' % comment_id,
        'updated_on': None,
        'user': {'account_id': 'robot-account-id'},
        'links': {'self': {'href': href}},
        'deleted': False,
        'pullrequest': {'id': 7},
    }


@pytest.fixture
def bb_client():
    return bitbucket.Client('robot_username', 'password', 'robot@example.com')


def bb_pull_request(client):
    # test_server.py replaces bitbucket.PullRequest with the mock's class at
    # import time: look the real class up so the test is order-independent.
    pull_request_cls, = (
        cls for cls in base.AbstractPullRequest.__subclasses__()
        if cls.__module__ == bitbucket.__name__)
    return pull_request_cls(
        client, id=7,
        destination={'repository': {'full_name': 'owner/repo'},
                     'branch': {'name': 'development/1.0'}})


def test_bitbucket_comment_edit(bb_client):
    comment = bitbucket.Comment.load(bb_comment('old status'))
    comment.client = bb_client
    with requests_mock.Mocker() as mocker:
        mocker.put(BB_COMMENT_URL, json=bb_comment('new status'))
        comment.edit('new status')

    assert len(mocker.request_history) == 1
    request = mocker.request_history[0]
    # Bitbucket documents PUT for comment edition
    assert request.method == 'PUT'
    assert json.loads(request.text) == {'content': {'raw': 'new status'}}
    assert comment.text == 'new status'
    assert comment.id == '42'


def test_bitbucket_comment_edit_http_error(bb_client):
    comment = bitbucket.Comment.load(bb_comment('old status'))
    comment.client = bb_client
    with requests_mock.Mocker() as mocker:
        mocker.put(BB_COMMENT_URL, status_code=403)
        with pytest.raises(HTTPError):
            comment.edit('new status')
    assert comment.text == 'old status'


def test_bitbucket_edit_refreshes_cached_comments(bb_client):
    """PullRequest.comments is cached on Bitbucket: an edit must show."""
    pr = bb_pull_request(bb_client)
    listing = {'values': [bb_comment('greetings', 41),
                          bb_comment('old status', 42)]}
    with requests_mock.Mocker() as mocker:
        mocker.get(BB_PR_URL + '/comments', json=listing)
        mocker.put(BB_COMMENT_URL, json=bb_comment('new status'))
        status = pr.comments[1]
        status.edit('new status')
        texts = [c.text for c in pr.comments]

    assert texts == ['greetings', 'new status']
    # The cache was used: a single listing, then the edit
    assert [r.method for r in mocker.request_history] == ['GET', 'PUT']


def test_bitbucket_comment_edit_full_api_response(bb_client):
    """Bitbucket returns the comment's `id` and `type` along with the
    fields Bert-E uses: they must not make the edit fail."""
    comment = bitbucket.Comment.load(bb_comment('old status'))
    comment.client = bb_client
    response = dict(bb_comment('new status'), id=42,
                    type='pullrequest_comment')
    with requests_mock.Mocker() as mocker:
        mocker.put(BB_COMMENT_URL, json=response)
        comment.edit('new status')
    assert comment.text == 'new status'
    assert comment.id == '42'
