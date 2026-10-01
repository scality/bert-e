from unittest import mock

from bert_e.git_host.github import Client, Comment


def test_client_patch_uses_http_patch():
    client = Client.__new__(Client)
    client.session = mock.Mock()
    client.session.patch.return_value.text = '{}'
    client._patch_url = lambda url: url
    client.patch('https://api.github.com/c/1', data='{}')
    client.session.patch.assert_called_once()
    client.session.post.assert_not_called()


def test_comment_edit_sends_patch_and_refreshes_data():
    client = mock.Mock()
    client.patch.return_value = {
        'id': 1, 'url': 'https://api.github.com/c/1', 'body': 'new',
        'user': {'login': 'bert-e', 'id': 1},
        'created_at': '2020-01-01T00:00:00Z'}
    comment = Comment(client, _validate=False, id=1,
                      url='https://api.github.com/c/1', body='old',
                      user={'login': 'bert-e', 'id': 1},
                      created_at='2020-01-01T00:00:00Z')
    comment.edit('new')
    assert client.patch.call_args[0][0] == 'https://api.github.com/c/1'
    assert comment.text == 'new'
