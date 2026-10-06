"""Unit tests of AbstractComment.update() on every git host."""
import json
from unittest.mock import MagicMock

import pytest
from requests import HTTPError, Response

from bert_e.git_host import bitbucket, github, mock


def _response(status_code, payload):
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    return response


GH_COMMENT_URL = ('https://api.github.com/repos/octo-org/hello/'
                  'issues/comments/42')


def github_comment_json(body):
    return {
        'id': 42,
        'body': body,
        'created_at': '2024-01-01T00:00:00Z',
        'updated_at': '2024-01-02T00:00:00Z',
        'user': {'id': 1, 'login': 'Robot'},
        'url': GH_COMMENT_URL,
    }


@pytest.fixture
def github_client():
    return github.Client(login='login', password='password',
                         email='email@org.com',
                         base_url='https://api.github.com',
                         accept_header='application/json')


def test_github_comment_update(github_client):
    comment = github.Comment(client=github_client,
                             **github_comment_json('old'))
    github_client.session = MagicMock()
    github_client.session.patch.return_value = _response(
        200, github_comment_json('new'))

    comment.update('new')

    github_client.session.post.assert_not_called()
    github_client.session.patch.assert_called_once()
    args, kwargs = github_client.session.patch.call_args
    assert args[0] == GH_COMMENT_URL
    assert json.loads(kwargs['data']) == {'body': 'new'}
    assert comment.text == 'new'
    assert comment.id == 42
    assert comment.author == 'robot'


def test_github_comment_update_http_error(github_client):
    comment = github.Comment(client=github_client,
                             **github_comment_json('old'))
    github_client.session = MagicMock()
    github_client.session.patch.return_value = _response(
        404, {'message': 'Not Found'})

    with pytest.raises(HTTPError):
        comment.update('new')
    assert comment.text == 'old'


BB_COMMENT_URL = ('https://api.bitbucket.org/2.0/repositories/'
                  'owner/slug/pullrequests/4/comments/21710334')


def bitbucket_comment_json(raw):
    return {
        'content': {'raw': raw, 'markup': 'markdown', 'html': raw},
        'created_on': '2016-07-30T14:17:11.953311+00:00',
        'updated_on': '2016-07-31T14:17:11.953311+00:00',
        'user': {'account_id': 'ROBOT-ID'},
        'links': {'self': {'href': BB_COMMENT_URL}},
        'deleted': False,
        'pullrequest': {'id': 4},
    }


@pytest.fixture
def bitbucket_client():
    client = bitbucket.Client('login', 'password', 'email@org.com')
    client.put = MagicMock()
    return client


def test_bitbucket_comment_update(bitbucket_client):
    comment = bitbucket.Comment(bitbucket_client,
                                **bitbucket_comment_json('old'))
    bitbucket_client.put.return_value = _response(
        200, bitbucket_comment_json('new'))

    comment.update('new')

    bitbucket_client.put.assert_called_once()
    args, kwargs = bitbucket_client.put.call_args
    assert args[0] == BB_COMMENT_URL
    assert json.loads(kwargs['data']) == {'content': {'raw': 'new'}}
    assert comment.text == 'new'
    assert comment.id == '21710334'
    assert comment.author == 'robot-id'


def test_bitbucket_comment_update_http_error(bitbucket_client):
    comment = bitbucket.Comment(bitbucket_client,
                                **bitbucket_comment_json('old'))
    bitbucket_client.put.return_value = _response(404, {})

    with pytest.raises(HTTPError):
        comment.update('new')
    assert comment.text == 'old'


@pytest.fixture
def mock_pull_request():
    client = mock.Client('robot', 'password', 'robot@example.com')
    repo = client.create_repository('_test_comment_update')
    yield repo.create_pull_request('title', 'feature', 'master')
    client.delete_repository('_test_comment_update')


def test_mock_comment_update(mock_pull_request):
    comment = mock_pull_request.add_comment('old')
    other = mock_pull_request.add_comment('other')

    comment.update('new')

    comments = list(mock_pull_request.get_comments())
    assert [c.id for c in comments] == [comment.id, other.id]
    assert [c.text for c in comments] == ['new', 'other']
    assert comments[0].author == 'robot'


def test_mock_comment_update_deleted(mock_pull_request):
    comment = mock_pull_request.add_comment('old')
    comment.delete()

    with pytest.raises(HTTPError):
        comment.update('new')
