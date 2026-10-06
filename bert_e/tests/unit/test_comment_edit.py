"""Unit tests of the comment edition on the GitHub and Bitbucket hosts."""
import json
from unittest.mock import patch

import pytest
from requests import HTTPError, Response

from bert_e.git_host import bitbucket, github


def make_response(status_code, payload):
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    response.headers['Content-Type'] = 'application/json'
    return response


GH_COMMENT_URL = \
    'https://api.github.com/repos/octo-org/hello/issues/comments/42'


def github_comment_json(body):
    return {
        'id': 42,
        'body': body,
        'created_at': '2026-10-06T10:00:00Z',
        'updated_at': '2026-10-06T10:00:00Z',
        'user': {'id': 1, 'login': 'Robot', 'type': 'User'},
        'url': GH_COMMENT_URL,
    }


@pytest.fixture
def github_client():
    return github.Client(login='login', password='password',
                         email='email@org.com',
                         base_url='http://localhost:4010',
                         accept_header='application/json')


def test_github_comment_edit(github_client):
    comment = github.Comment(client=github_client,
                             **github_comment_json('old status'))
    with patch.object(github_client.session, 'post',
                      return_value=make_response(
                          200, github_comment_json('new status'))) as post:
        comment.edit('new status')

    post.assert_called_once()
    url = post.call_args.args[0]
    assert url == GH_COMMENT_URL
    assert json.loads(post.call_args.kwargs['data']) == {'body': 'new status'}
    assert comment.text == 'new status'
    assert comment.id == 42
    assert comment.author == 'robot'
    assert comment.client is github_client


def test_github_comment_edit_http_error(github_client):
    comment = github.Comment(client=github_client,
                             **github_comment_json('old status'))
    with patch.object(github_client.session, 'post',
                      return_value=make_response(
                          404, {'message': 'Not Found'})):
        with pytest.raises(HTTPError):
            comment.edit('new status')
    assert comment.text == 'old status'


BB_PR_API = ('https://api.bitbucket.org/2.0/repositories/'
             'test_owner/test_repo/pullrequests/4')


def bitbucket_comment_json(comment_id, raw, created_on):
    return {
        'id': comment_id,
        'content': {'raw': raw, 'markup': 'markdown', 'html': raw},
        'created_on': created_on,
        'updated_on': created_on,
        'user': {'account_id': '557058:robot', 'display_name': 'Robot'},
        'links': {
            'self': {'href': '%s/comments/%d' % (BB_PR_API, comment_id)},
            'html': {'href': 'https://bitbucket.org/test_owner/test_repo/'
                             'pull-requests/4/_/diff#comment-%d'
                             % comment_id},
        },
        'deleted': False,
        'type': 'pullrequest_comment',
        'pullrequest': {'id': 4},
    }


@pytest.fixture
def bitbucket_client():
    return bitbucket.Client('login', 'password', 'login@example.com')


def test_bitbucket_comment_edit(bitbucket_client):
    comment = bitbucket.Comment.load(
        bitbucket_comment_json(7, 'old status', '2026-10-06T10:00:00+00:00'))
    comment.client = bitbucket_client
    updated = bitbucket_comment_json(7, 'new status',
                                     '2026-10-06T10:00:00+00:00')
    with patch.object(bitbucket_client, 'put',
                      return_value=make_response(200, updated)) as put:
        comment.edit('new status')

    put.assert_called_once()
    assert put.call_args.args[0] == BB_PR_API + '/comments/7'
    assert json.loads(put.call_args.kwargs['data']) == \
        {'content': {'raw': 'new status'}}
    assert comment.text == 'new status'
    assert comment.id == '7'
    assert comment.client is bitbucket_client


def test_bitbucket_comment_edit_http_error(bitbucket_client):
    comment = bitbucket.Comment.load(
        bitbucket_comment_json(7, 'old status', '2026-10-06T10:00:00+00:00'))
    comment.client = bitbucket_client
    with patch.object(bitbucket_client, 'put',
                      return_value=make_response(403, {'error': {}})):
        with pytest.raises(HTTPError):
            comment.edit('new status')
    assert comment.text == 'old status'


def test_bitbucket_cached_comments_refreshed_after_edit(bitbucket_client):
    """The comments cached on a pull request reflect an edition."""
    pull_request = bitbucket.PullRequest(
        bitbucket_client, id=4,
        destination={'repository': {'full_name': 'test_owner/test_repo'}})
    listed = [
        bitbucket_comment_json(7, 'hello', '2026-10-06T10:00:00+00:00'),
        bitbucket_comment_json(8, 'old status', '2026-10-06T11:00:00+00:00'),
    ]
    with patch.object(bitbucket_client, 'iter_get',
                      return_value=iter(listed)) as iter_get:
        comments = pull_request.comments
        assert [c.text for c in comments] == ['hello', 'old status']

        updated = bitbucket_comment_json(8, 'new status',
                                         '2026-10-06T11:00:00+00:00')
        with patch.object(bitbucket_client, 'put',
                          return_value=make_response(200, updated)):
            comments[-1].edit('new status')

        # Still served from the cache, without any new listing request
        assert [c.text for c in pull_request.comments] == \
            ['hello', 'new status']
        iter_get.assert_called_once()
