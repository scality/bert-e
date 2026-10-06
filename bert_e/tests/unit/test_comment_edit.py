"""Edition of pull request comments on every git host implementation."""
import json

import pytest
import requests
import requests_mock

from bert_e.git_host import bitbucket, github, mock

GH_BASE = 'https://api.github.com'
GH_COMMENT_URL = GH_BASE + '/repos/octo/repo/issues/comments/42'
BB_COMMENTS_URL = ('https://api.bitbucket.org/2.0/repositories/'
                   'octo/repo/pullrequests/7/comments')


def gh_comment(body):
    return {
        'id': 42,
        'body': body,
        'created_at': '2024-01-01T00:00:00Z',
        'updated_at': '2024-01-01T00:00:00Z',
        'user': {'id': 1, 'login': 'Robot_Username'},
        'url': GH_COMMENT_URL,
    }


def bb_comment(raw, comment_id=12):
    return {
        'content': {'raw': raw, 'markup': 'markdown', 'html': raw},
        'created_on': '2024-01-01T00:00:00+00:00',
        'updated_on': '2024-01-01T00:00:00+00:00',
        'user': {'account_id': 'robot-id'},
        'links': {'self': {'href': '%s/%d' % (BB_COMMENTS_URL, comment_id)}},
        'deleted': False,
        'type': 'pullrequest_comment',
        'pullrequest': {'id': 7},
        'id': comment_id,
        'inline': None,
    }


@pytest.fixture
def gh_client():
    return github.Client(login='login', password='password',
                         email='email@org.com', base_url=GH_BASE)


@pytest.fixture
def bb_client():
    return bitbucket.Client('login', 'password', 'email@org.com')


def test_github_comment_edit(gh_client):
    comment = github.Comment.load(gh_comment('before'))
    comment.client = gh_client
    with requests_mock.Mocker() as m:
        # github.Client.patch() sends the update as a POST on the object
        # URL (GitHub accepts POST in place of PATCH), like
        # PullRequest.decline() does through the same update() path.
        m.post(GH_COMMENT_URL, json=gh_comment('after'))
        comment.edit('after')

    assert m.call_count == 1
    assert json.loads(m.last_request.body) == {'body': 'after'}
    assert comment.text == 'after'
    assert comment.id == 42
    assert comment.author == 'robot_username'


def test_github_comment_edit_http_error(gh_client):
    comment = github.Comment.load(gh_comment('before'))
    comment.client = gh_client
    with requests_mock.Mocker() as m:
        m.post(GH_COMMENT_URL, status_code=403, json={})
        with pytest.raises(requests.HTTPError):
            comment.edit('after')
    assert comment.text == 'before'


def test_bitbucket_comment_edit_refreshes_pr_cache(bb_client):
    pr = bitbucket.PullRequest(
        bb_client, id=7,
        destination={'repository': {'full_name': 'octo/repo'}})
    with requests_mock.Mocker() as m:
        m.get(BB_COMMENTS_URL, json={'values': [bb_comment('before')]})
        cached = pr.comments
        assert [c.text for c in cached] == ['before']

        m.put(BB_COMMENTS_URL + '/12', json=bb_comment('after'))
        cached[0].edit('after')

        put = [r for r in m.request_history if r.method == 'PUT']
        assert len(put) == 1
        assert json.loads(put[0].body) == {'content': {'raw': 'after'}}
        # The cached list of the pull request now holds the new text, no
        # further GET request is needed to see it.
        gets = len([r for r in m.request_history if r.method == 'GET'])
        assert [c.text for c in pr.comments] == ['after']
        assert len([r for r in m.request_history
                    if r.method == 'GET']) == gets
    assert pr.comments[0].id == '12'
    assert pr.comments[0].author == 'robot-id'


def test_bitbucket_comment_edit_http_error(bb_client):
    comment = bitbucket.Comment.load(bb_comment('before'))
    comment.client = bb_client
    with requests_mock.Mocker() as m:
        m.put(BB_COMMENTS_URL + '/12', status_code=404, json={})
        with pytest.raises(requests.HTTPError):
            comment.edit('after')
    assert comment.text == 'before'


def test_mock_comment_edit():
    client = mock.Client('robot', 'password', 'robot@example.com')
    repo = client.create_repository('test_mock_comment_edit')
    try:
        repo.get_git_url()
        pr = mock.PullRequest(
            repo, 'title', 'name', {'branch': {'name': 'feature'}},
            {'branch': {'name': 'master'}}, False, [], 'description'
        ).create()
        pr = mock.PullRequestController(client, pr)
        pr.add_comment('first')
        comment = pr.add_comment('before')
        comment.edit('after')
        assert [c.text for c in pr.get_comments()] == ['first', 'after']
        assert pr.comments[-1].author == 'robot'
        assert pr.comments[-1].id == comment.id
    finally:
        client.delete_repository('test_mock_comment_edit')
