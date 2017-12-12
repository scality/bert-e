# Copyright 2016 Scality
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from os import environ
from time import sleep
from types import SimpleNamespace

import pytest

from bert_e.git_host import NoSuchRepository, RepositoryExists, client_factory
from bert_e.lib.git import Repository as GitRepository


def github_client_args():
    return (environ['GH_LOGIN'],
            environ['GH_PASSWORD'],
            environ['GH_EMAIL'])


def bitbucket_client_args():
    return (environ['BB_LOGIN'],
            environ['BB_PASSWORD'],
            environ['BB_EMAIL'])


def mock_client_args():
    return ('login', 'password', 'login@example.com')


CLIENT_PARAMS = [
    ('mock', mock_client_args),
    ('github', github_client_args),
    ('bitbucket', bitbucket_client_args)
]


@pytest.fixture(scope='module', params=CLIENT_PARAMS, ids=lambda p: p[0])
def client_host(request):
    key, func = request.param
    try:
        return client_factory(key, *func()), key
    except KeyError as err:
        pytest.skip("Missing environment value: {}".format(err))


@pytest.fixture(scope='class')
def repository_host(client_host):
    client, host = client_host
    repo_name = '_test_git_host_api_{}'.format(host)
    try:
        repo = client.create_repository(repo_name)
    except RepositoryExists:
        client.delete_repository(repo_name)
        repo = client.create_repository(repo_name)
    yield repo, host
    client.delete_repository(repo_name)


@pytest.fixture(scope='class')
def configured_repo(repository_host):
    repository, host = repository_host
    gitrepo = GitRepository(repository.git_url)
    gitrepo.clone()
    owner = repository.client.login
    email = repository.client.email

    with gitrepo:
        gitrepo.cmd('git checkout -b master')
        gitrepo.cmd('git config user.email {}'.format(email))
        gitrepo.cmd('git config user.name {}'.format(owner))
        gitrepo.cmd('touch a')
        gitrepo.cmd('git add a')
        gitrepo.cmd('git commit -m "Initial commit"')
        gitrepo.cmd('git push -u origin master')
        yield gitrepo, repository, host


@pytest.fixture(scope='class')
def workspace(configured_repo):
    gitrepo, repo, host = configured_repo
    wsp = SimpleNamespace(
        host=host,
        gitrepo=gitrepo,
        repo=repo,
        client=repo.client
    )
    return wsp


def make_pull_request(workspace, src_branch, dst_branch='master',
                      title=None, body='', filename=None, contents=None):
    gitrepo, repo = workspace.gitrepo, workspace.repo
    title = title or src_branch
    if filename is None:
        filename = src_branch
    if contents is None:
        contents = title

    gitrepo.cmd('git fetch --prune')
    gitrepo.cmd('git checkout {}'.format(dst_branch))
    gitrepo.cmd('git pull')
    gitrepo.cmd('git checkout -b {}'.format(src_branch))
    gitrepo.cmd('echo {0} > {1} && git add {1}'.format(contents, filename))
    gitrepo.cmd('git commit -m "{}"'.format(title))
    gitrepo.cmd('git push -u origin {}'.format(src_branch))

    return repo.create_pull_request(
        title, src_branch, dst_branch, body
    )


# Classes of test are made to avoid rebuilding/destroying whole workspaces
# once per test. Please make sure that all tests within a class do not clash
# with each other.
# One easy way to do that when using the workspace fixture is to give the pull
# request the name of the test.
class TestBasicFunctionality:
    @classmethod
    def setup_class(cls):
        logging.basicConfig(level=logging.DEBUG)

    def test_repository_exceptions(self, client_host):
        client, _ = client_host
        with pytest.raises(NoSuchRepository):
            client.delete_repository('_test_repo_that_doesnt_exist')

        with pytest.raises(NoSuchRepository):
            client.get_repository('_test_repo_that_doesnt_exist')

        try:
            client.create_repository('_test_repo_in_git_api')
            client.get_repository('_test_repo_in_git_api')  # Should not raise
            with pytest.raises(RepositoryExists):
                client.create_repository('_test_repo_in_git_api')
        finally:
            try:
                client.delete_repository('_test_repo_in_git_api')
            except:
                pass

    def test_create_and_decline_pull_request(self, workspace):
        repo = workspace.repo
        branch_name = 'test_create_and_decline_pull_request'

        existing_prs = list(repo.get_pull_requests(src_branch=branch_name))
        assert not existing_prs

        pr_title = 'Test create and close PR'
        pull_request = make_pull_request(
            workspace, branch_name, title=pr_title,
            body='Test: open and close a pull request'
        )

        assert pull_request.src_branch == branch_name
        assert pull_request.dst_branch == 'master'
        assert pull_request.title == pr_title
        assert pull_request.status == 'OPEN'

        # Check that the created pull request is listed
        existing_prs = list(repo.get_pull_requests(src_branch=branch_name))
        assert any(pr.id == pull_request.id for pr in existing_prs)

        pull_request.decline()
        pull_request = repo.get_pull_request(pull_request.id)
        assert pull_request.status == 'DECLINED'
        assert not list(repo.get_pull_requests(src_branch=branch_name))
        assert list(repo.get_pull_requests(src_branch=branch_name,
                                           status='DECLINED'))

    def test_merge_pull_request_manually(self, workspace):
        branch_name = 'test_merge_pull_request_manually'
        repo = workspace.repo
        pull_request = make_pull_request(
            workspace, branch_name, 'master'
        )
        cmd = workspace.gitrepo.cmd
        cmd('git checkout master')
        cmd('git pull')
        cmd('git merge {}'.format(branch_name))
        cmd('git push origin master')

        # Detection of merged pull requests can take time.
        # Let's give the remote host a few retries.
        for _ in range(10):
            pull_request = workspace.repo.get_pull_request(pull_request.id)
            if pull_request.status == 'MERGED':
                break
            sleep(1)

        assert pull_request.status == 'MERGED'
        assert not list(repo.get_pull_requests(src_branch=branch_name))
        assert list(repo.get_pull_requests(src_branch=branch_name,
                                           status='MERGED'))

    def test_pull_request_comments(self, workspace):
        pull_request = make_pull_request(
            workspace, 'test_pull_request_comments', 'master'
        )
        comments = list(pull_request.get_comments())
        assert not comments

        pull_request.add_comment('First comment')
        comments = list(pull_request.get_comments())
        assert len(comments) == 1
        assert comments[0].author == workspace.client.login

        pull_request.add_comment('Second comment')
        pull_request.add_comment('Third comment')
        pull_request.add_comment('Last comment')

        # Check that multiple calls to the same request yield the same result
        # Basically, if the host implements a cache, check that it works well
        # on paginated results.
        comments = list(pull_request.get_comments())
        comments2 = list(pull_request.get_comments())
        assert [cmt.id for cmt in comments] == [cmt.id for cmt in comments2]

        # Comments should be received in chronological order
        assert all(comments[i].id < comments[i + 1].id
                   for i in range(len(comments) - 1))

        # Delete a comment
        comments[0].delete()
        # Check deleted comments are not shown by default
        assert len(comments) != len(list(pull_request.get_comments()))
        # But can be on bitbucket
        if workspace.host == 'bitbucket':
            assert (len(comments) ==
                    len(list(pull_request.get_comments(deleted=True))))

        cmt1, *_, cmt2 = comments
        assert cmt1.text == 'First comment'
        assert cmt2.text == 'Last comment'

    def test_tasks(self, workspace):
        if workspace.host == 'github':
            pytest.skip('Tasks are not supported by this host.')

        pull_request = make_pull_request(workspace, 'test_tasks', 'master')
        pull_request.get_tasks()

        comment = pull_request.add_comment('Some comment')
        comment2 = pull_request.add_comment('Some other comment')
        comment.add_task('do spam')
        comment.add_task('do egg')
        comment2.add_task('do bacon')
        assert len(list(pull_request.get_tasks())) == 3

    def test_build_status(self, workspace):
        pull_request = make_pull_request(workspace, 'test_build_status',
                                         'master')

        ref = pull_request.src_commit
        repo = workspace.repo
        repo.set_build_status(ref, 'some_key', 'FAILED',
                              url='https://key.domain.org/build/1')
        repo.set_build_status(ref, 'key', 'SUCCESSFUL',
                              url='https://key.domain.org/build/2')

        assert repo.get_build_status(ref, 'some_key') == 'FAILED'
        assert repo.get_build_status(ref, 'key') == 'SUCCESSFUL'
        assert repo.get_build_status(ref, 'nah') == 'NOTSTARTED'
        assert repo.get_build_status('doesntexist', 'key') == 'NOTSTARTED'

    def test_approvals(self, workspace):
        if workspace.host == 'github':
            pytest.skip('Not supported: Cannot approve own pull request.')
        pull_request = make_pull_request(workspace, 'test_approvals', 'master')

        assert not list(pull_request.get_approvals())
        pull_request.approve()
        # update pull_request
        pull_request = workspace.repo.get_pull_request(pull_request.id)

        assert len(list(pull_request.get_approvals())) == 1
        assert workspace.client.login in list(pull_request.get_participants())
