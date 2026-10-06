"""Comment.edit() on the GitHub and Bitbucket hosts, at the HTTP level."""
import json

import pytest
import requests_mock
from requests import HTTPError

from bert_e.git_host import bitbucket, github, mock


GH_COMMENT_URL = \
    'https://api.github.com/repos/owner/slug/issues/comments/42'
BB_COMMENT_URL = ('https://api.bitbucket.org/2.0/repositories/'
                  'owner/slug/pullrequests/1/comments/42')


def github_comment_json(body):
    return {
        'id': 42,
        'body': body,
        'created_at': '2026-10-06T10:00:00Z',
        'updated_at': '2026-10-06T11:00:00Z',
        'user': {'id': 1, 'login': 'Robot_User'},
        'url': GH_COMMENT_URL,
    }


def bitbucket_comment_json(raw):
    return {
        'content': {'raw': raw, 'markup': 'markdown', 'html': raw},
        'created_on': '2026-10-06T10:00:00+00:00',
        'updated_on': '2026-10-06T11:00:00+00:00',
        'user': {'account_id': '557058:robot'},
        'links': {'self': {'href': BB_COMMENT_URL}},
        'deleted': False,
        'pullrequest': {'id': 1},
    }


@pytest.fixture
def github_comment():
    client = github.Client(login='login', password='password',
                           email='email@org.com')
    comment = github.Comment.load(github_comment_json('old text'))
    comment.client = client
    return comment


@pytest.fixture
def bitbucket_comment():
    client = bitbucket.Client('login', 'password', 'email@org.com')
    comment = bitbucket.Comment.load(bitbucket_comment_json('old text'))
    comment.client = client
    return comment


def test_github_edit(github_comment):
    with requests_mock.Mocker() as m:
        # github.Client.patch() sends a POST, which the GitHub API accepts
        # in lieu of PATCH.
        m.post(GH_COMMENT_URL, json=github_comment_json('new text'))
        assert github_comment.edit('new text') is None
    assert m.call_count == 1
    assert json.loads(m.last_request.body) == {'body': 'new text'}
    assert github_comment.text == 'new text'
    assert github_comment.id == 42
    assert github_comment.author == 'robot_user'


def test_github_edit_http_error(github_comment):
    with requests_mock.Mocker() as m:
        m.post(GH_COMMENT_URL, status_code=404, json={})
        with pytest.raises(HTTPError):
            github_comment.edit('new text')
    assert github_comment.text == 'old text'


def test_bitbucket_edit(bitbucket_comment):
    with requests_mock.Mocker() as m:
        m.put(BB_COMMENT_URL, json=bitbucket_comment_json('new text'))
        assert bitbucket_comment.edit('new text') is None
    assert m.call_count == 1
    assert json.loads(m.last_request.body) == \
        {'content': {'raw': 'new text'}}
    assert bitbucket_comment.text == 'new text'
    assert bitbucket_comment.id == '42'
    assert bitbucket_comment.client is not None


def test_bitbucket_edit_http_error(bitbucket_comment):
    with requests_mock.Mocker() as m:
        m.put(BB_COMMENT_URL, status_code=404, json={})
        with pytest.raises(HTTPError):
            bitbucket_comment.edit('new text')
    assert bitbucket_comment.text == 'old text'


def test_mock_edit():
    client = mock.Client('login', 'password', 'email')
    repo = client.create_repository('test_comment_edit')
    try:
        pull_request = repo.create_pull_request('title', 'src', 'dst')
        first = pull_request.add_comment('first')
        second = pull_request.add_comment('second')
        first.edit('edited')
        assert first.text == 'edited'
        texts = [c.text for c in pull_request.get_comments()]
        # Edited in place: same position, other comments untouched
        assert texts == ['edited', 'second']
        assert second.text == 'second'
    finally:
        client.delete_repository('test_comment_edit')
