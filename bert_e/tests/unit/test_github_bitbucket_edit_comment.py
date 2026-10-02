"""Unit tests of the `edit` method of the pull request comments."""
import json

import pytest
import requests
import requests_mock

from bert_e.git_host import bitbucket, github, mock
from bert_e.git_host.base import AbstractComment

GITHUB_URL = 'https://api.github.com/repos/octo/repo/issues/comments/42'
BITBUCKET_URL = ('https://api.bitbucket.org/2.0/repositories/octo/repo/'
                 'pullrequests/7/comments/42')


def test_edit_is_part_of_the_abstract_interface():
    assert 'edit' in AbstractComment.__abstractmethods__


def make_github_comment():
    client = github.Client('login', 'password', 'login@example.com')
    return github.Comment(
        client=client, _validate=False, id=42, body='old', url=GITHUB_URL,
        user={'login': 'Robot'})


def make_bitbucket_comment():
    client = bitbucket.Client('login', 'password', 'login@example.com')
    return bitbucket.Comment(
        client=client, _validate=False, deleted=False,
        content={'raw': 'old'}, pullrequest={'id': 7},
        links={'self': {'href': BITBUCKET_URL}},
        user={'account_id': 'robot'})


def test_github_edit_patches_the_comment():
    comment = make_github_comment()
    with requests_mock.Mocker() as mocker:
        mocker.patch(GITHUB_URL, json={'id': 42, 'body': 'new'})
        comment.edit('new')

    assert mocker.call_count == 1
    request = mocker.request_history[0]
    assert request.method == 'PATCH'
    assert request.url == GITHUB_URL
    assert json.loads(request.text) == {'body': 'new'}
    assert comment.text == 'new'


def test_github_edit_http_error_is_raised_and_text_kept():
    comment = make_github_comment()
    with requests_mock.Mocker() as mocker:
        mocker.patch(GITHUB_URL, status_code=404, json={})
        with pytest.raises(requests.HTTPError):
            comment.edit('new')
    assert comment.text == 'old'


def test_bitbucket_edit_puts_the_comment():
    comment = make_bitbucket_comment()
    assert comment.id == '42'
    with requests_mock.Mocker() as mocker:
        mocker.put(BITBUCKET_URL, json={})
        comment.edit('new')

    assert mocker.call_count == 1
    request = mocker.request_history[0]
    assert request.method == 'PUT'
    assert request.url == BITBUCKET_URL
    assert json.loads(request.text) == {'content': {'raw': 'new'}}
    assert comment.text == 'new'


def test_bitbucket_edit_http_error_is_raised_and_text_kept():
    comment = make_bitbucket_comment()
    with requests_mock.Mocker() as mocker:
        mocker.put(BITBUCKET_URL, status_code=403, json={})
        with pytest.raises(requests.HTTPError):
            comment.edit('new')
    assert comment.text == 'old'


def test_bitbucket_pull_request_keeps_its_cache_of_comments_up_to_date():
    client = bitbucket.Client('login', 'password', 'login@example.com')
    pull_request = bitbucket.PullRequest(
        client, id=7,
        destination={'repository': {'full_name': 'octo/repo'}})
    existing = make_bitbucket_comment()
    pull_request._comments = [existing]
    created = {'content': {'raw': 'hello'}, 'deleted': False,
               'pullrequest': {'id': 7}, 'links': {'self': {
                   'href': BITBUCKET_URL.replace('42', '43')}},
               'user': {'account_id': 'robot'},
               'created_on': '2024-01-01T00:00:00+00:00'}
    with requests_mock.Mocker() as mocker:
        mocker.post(BITBUCKET_URL.rsplit('/', 1)[0], json=created)
        comment = pull_request.add_comment('hello')

    assert pull_request.comments == [existing, comment]


def test_mock_edit_replaces_the_text_in_place():
    client = mock.Client('robot', 'password', 'robot@example.com')
    stored = mock.Comment(
        client, content='old', pull_request_id=1, full_name='o/r').create()
    try:
        comment = mock.CommentController(client, stored)
        comment.edit('new')
        assert comment.text == 'new'
        listed = mock.Comment.get_list(client, 'o/r', 1)
        assert [c.content['raw'] for c in listed] == ['new']
    finally:
        mock.Comment.items = []
