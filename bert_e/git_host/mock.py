#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2016-2018 Scality
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

from datetime import datetime
import requests

from . import base
from ..exceptions import TaskAPIError
from ..lib.git import Branch as GitBranch
from ..lib.git import Repository as GitRepository
from .factory import api_client


def fake_user_dict(username):
    return {
        "username": username,
        "display_name": username,
        "uuid": "{1cd06601-cd0e-4fce-be03-e9ac226978b7}",
        "links": fake_links_dict(['avatar', 'html', 'self']),
        "id": str(hash(username)),
    }


def fake_links_dict(keys):
    return {}


def fake_repository_dict(name):
    return {
        "full_name": "teamsinspace/documentation-tests",
        "links": fake_links_dict(['avatar', 'html', 'self']),
        "name": "documentation-tests",
        "type": "repository",
        "uuid": "{b4434b4d-6a0e-4f57-8d75-e02a824abeb0}"
    }


class Error404Response:
    status_code = 404


@api_client('mock')
class Client(base.AbstractClient):
    def __init__(self, username, password, email):
        self.login = username
        self.password = password
        self.auth = self
        self.email = email

    def create_repository(self, slug, owner=None, scm='git',
                          is_private=True):
        owner = owner or self.login
        repo_key = (owner, slug)

        if repo_key in Repository.repos:
            raise base.RepositoryExists(
                "A repository with owner '{}' and slug '{}' "
                "already exist.".format(owner, slug)
            )

        new_repo = Repository(self, owner=owner, repo_slug=slug, scm=scm,
                              is_private=True)
        new_repo.create()
        return new_repo

    def get_repository(self, slug, owner=None):
        if owner is None:
            owner = self.login
        repo_key = (owner, slug)
        if repo_key not in Repository.repos:
            raise base.NoSuchRepository(
                "Could not find the repository whose owner is '{}' "
                "and slug is '{}'. Available repos are: {}".format(
                    self.login, slug, list(Repository.repos.keys()))
            )
        return Repository(self, owner=owner, repo_slug=slug, scm='git',
                          is_private=True)

    def get_user_id(self):
        return User.get(self)['id']

    def delete_repository(self, slug, owner=None):
        if owner is None:
            owner = self.login
        repo_key = (owner, slug)
        if repo_key not in Repository.repos:
            raise base.NoSuchRepository(
                "Could not find the repository whose owner is '{}' "
                "and slug is '{}'".format(self.login, slug)
            )
        Repository.repos[repo_key].delete()
        Repository.repos.pop(repo_key)


class BitBucketObject:
    def __getitem__(self, item):
        return self.__getattribute__(item)

    def __setitem__(self, item, value):
        return self.__setattr__(item, value)

    def create(self):
        self.__class__.items.insert(0, self)
        return self

    def delete(self):
        try:
            self.__class__.items.remove(self)
        except ValueError:
            raise requests.exceptions.HTTPError(response=Error404Response())


class Controller:
    def __init__(self, client, controlled):
        self.controlled = controlled
        self.client = client

    def __getitem__(self, item):
        return self.controlled.__getattribute__(item)

    def __setitem__(self, item, value):
        return self.controlled.__setattr__(item, value)


class Repository(BitBucketObject, base.AbstractRepository):
    items = []
    repos = {}

    def __init__(self, client, owner, repo_slug, scm='git', is_private=True):
        self.client = client

        #  URL params #
        self.repo_owner = owner
        self.repo_slug = repo_slug

        #  JSON params #
        self.scm = scm
        self.has_wiki = True
        self.description = "description"
        self.links = {
            key: {"href": "http://..."} for key in
            ['watchers', 'commits', 'self', 'html', 'avatar', 'forks',
             'clone', 'pullrequests']}
        self.fork_policy = "allow_forks"
        self.name = "repo name"
        self.language = "python"
        self.created_on = "2011-12-20T16:35:06.480042+00:00"
        self.full_name = "tutorials/tutorials.bitbucket.org"
        self.has_issues = True
        self._owner = fake_user_dict(client.login)
        self.updated_on = "2014-11-03T02:24:08.409995+00:00"
        self.size = 76182262
        self.is_private = is_private
        self.uuid = "{9970a9b6-2d86-413f-8555-da8e1ac0e542}"

        # ###############

    def delete(self):
        super().delete()
        PullRequest.items = []
        Task.items = []
        Comment.items = []

    def create(self):
        self.gitrepo = GitRepository(None)
        self.gitrepo.cmd('git init --bare')
        self.gitrepo.revisions = {}  # UGLY
        Repository.repos[(self.repo_owner, self.repo_slug)] = self.gitrepo
        return super().create()

    def get_git_url(self):
        self.gitrepo = Repository.repos[(self.repo_owner, self.repo_slug)]
        return self.gitrepo.tmp_directory

    @property
    def git_url(self):
        return self.get_git_url()

    def create_pull_request(self, title, src_branch, dst_branch,
                            name='name', description='',
                            close_source_branch=True, reviewers=[]):
        self.get_git_url()
        source = {'branch': {'name': src_branch}}
        destination = {'branch': {'name': dst_branch}}
        pr = PullRequest(self, title, name, source, destination,
                         close_source_branch, reviewers, description).create()
        prc = PullRequestController(self.client, pr)
        for reviewer in reviewers:
            prc.add_participant(reviewer)
        return prc

    def get_pull_requests(self, author=None, src_branch=None, status='OPEN'):
        def predicate(pr):
            if pr.status != status:
                return False
            if author is not None and pr.author != author:
                return False
            if isinstance(src_branch, str) and pr.src_branch != src_branch:
                return False
            elif src_branch is not None and pr.src_branch not in src_branch:
                return False
            return True
        return filter(
            predicate,
            [PullRequestController(self.client, item)
             for item in PullRequest.items]
        )

    def get_pull_request(self, pull_request_id):
        assert type(pull_request_id) == int
        for item in PullRequest.items:
            pr = PullRequestController(self.client, item)
            if pr.id == pull_request_id:
                return pr
        raise Exception("Did not find this pr")

    def get_commit_url(self, revision):
        return "http://host/path/to/commit/{}".format(revision)

    def get_build_url(self, revision, key):
        key = '{}-build'.format(revision)
        return self.gitrepo.revisions.get((revision, key), None)

    def get_build_status(self, revision, key):
        try:
            return self.gitrepo.revisions[(revision, key)]
        except KeyError:
            return 'NOTSTARTED'

    def invalidate_build_status_cache(self):
        pass

    def set_build_status(self, revision, key, state, **kwargs):
        self.get_git_url()
        self.gitrepo.revisions[(revision, key)] = state

    @property
    def owner(self):
        return self.repo_owner

    @property
    def slug(self):
        return self.repo_slug


class PullRequestController(Controller, base.AbstractPullRequest):
    def add_comment(self, msg):
        comment = Comment(self.client, content=msg,
                          full_name=self.controlled.full_name(),
                          pull_request_id=self.controlled.id).create()

        self.update_participant(role='PARTICIPANT')
        return CommentController(self.client, comment)

    def get_comments(self):
        return (CommentController(self.client, c)
                for c in Comment.get_list(
                    self.client, full_name=self.controlled.full_name(),
                    pull_request_id=self.controlled.id))

    def get_tasks(self):
        return [Controller(self.client, t) for t in Task.get_list(
                self.client, full_name=self.controlled.full_name(),
                pull_request_id=self.controlled.id)]

    def merge(self):
        raise NotImplemented('Merge')

    def comment_review(self):
        self.update_participant(changes_requested=False, approved=False,
                                role='REVIEWER')

    def request_changes(self):
        self.update_participant(changes_requested=True, role='REVIEWER')

    def approve(self):
        self.update_participant(approved=True, changes_requested=False,
                                role='REVIEWER')

    def dismiss(self, review):
        self.update_participant(approved=False, changes_requested=False,
                                role='REVIEWER')

    def update_participant(self, approved=None, role=None,
                           changes_requested=None):
        # locate participant
        exists = False
        for participant in self['participants']:
            if participant['user']['username'] == self.client.login:
                exists = True
                break

        if not exists:
            # new participant
            self.add_participant(fake_user_dict(self.client.login))
            participant = self['participants'][-1]

        # update it
        if approved is not None:
            participant['approved'] = approved
        if changes_requested is not None:
            participant['changes_requested'] = changes_requested
        if role is not None:
            # role cannot downgrade from REVIEWER to PARTICIPANT
            if participant['role'] == 'REVIEWER' and role == 'PARTICIPANT':
                role = 'REVIEWER'
            participant['role'] = role

    def add_participant(self, user_struct):
        self['participants'].append({
            'user': user_struct,
            'approved': False,
            'changes_requested': False,
            'role': 'PARTICIPANT'})

    def get_change_requests(self):
        for participant in self['participants']:
            if participant['changes_requested']:
                yield participant['user']['username'].lower()

    def get_approvals(self):
        for participant in self['participants']:
            if participant['approved']:
                yield participant['user']['username'].lower()

    def get_participants(self):
        for participant in self['participants']:
            yield participant['user']['username'].lower()

    def decline(self):
        self['_state'] = "DECLINED"
        # Freeze the PR's source commit
        try:
            self['source']['commit'] = {'hash': self.src_commit}
        except Exception:
            pass

    @property
    def id(self):
        return self['id']

    @property
    def title(self):
        return self['title']

    @property
    def author(self):
        return self['author']['username'].lower()

    @property
    def author_display_name(self):
        return self['author']['display_name']

    @property
    def src_branch(self):
        return self['source']['branch']['name']

    @property
    def src_commit(self):
        return self['source']['commit']['hash']

    @src_commit.setter
    def src_commit(self, sha1):
        self['source']['commit'] = {'hash': sha1}

    @property
    def dst_branch(self):
        return self['destination']['branch']['name']

    @property
    def status(self):
        return self['state']

    @property
    def description(self):
        return self['description']

    @property
    def comments(self):
        return list(self.get_comments())


class CommentController(Controller, base.AbstractComment):
    def add_task(self, msg):
        task = Task(self.client, content=msg,
                    full_name=self.controlled.full_name,
                    pr_id=self.controlled.pull_request_id,
                    comment_id=self.controlled.id).create()

        PullRequest.items[self.controlled.pull_request_id - 1].task_count += 1
        return task

    def delete(self):
        self.controlled.delete()

    @property
    def author(self):
        return self['user']['username'].lower()

    @property
    def created_on(self):
        return self['created_on']

    @property
    def text(self):
        return self['content']['raw']

    @property
    def id(self):
        return self['id']


class Branch(object):
    def __init__(self, gitrepo, branch_name):
        self.git_branch = GitBranch(gitrepo, branch_name)

    def __getitem__(self, item):
        if item == 'hash':
            return self.git_branch.get_latest_commit()
        elif item == 'links':
            return fake_repository_dict(['self'])


class PullRequest(BitBucketObject):
    items = []

    def __init__(self, repo, title, name, source, destination,
                 close_source_branch, reviewers, description):
        self.repo = repo
        self.client = repo.client

        #  JSON params #
        self.author = fake_user_dict(self.client.login)

        self.close_source_branch = False
        self.closed_by = None
        self.comment_count = 2
        self.created_on = "2015-10-15T16:38:55.491628+00:00"
        self.description = description
        self.destination = {
            "branch": destination['branch'],
            "commit": Branch(self.repo.gitrepo, destination['branch']['name']),
            "repository": fake_repository_dict("sd")
        }
        self.id = len(PullRequest.items) + 1
        self.links = fake_links_dict(
            ['activity', 'request_change', 'approve', 'comments', 'commits',
             'decline', 'diff', 'html', 'merge', 'self'])
        self.merge_commit = None
        self.participants = []
        self.reason = ""
        self.source = {
            "branch": source['branch'],
            "commit": Branch(self.repo.gitrepo, source['branch']['name']),
            "repository": fake_repository_dict("")
        }
        self.task_count = 0
        self.title = title
        self.type = "pullrequest"
        self.updated_on = "2016-01-12T19:31:23.673329+00:00"
        self._state = "OPEN"

    @property
    def state(self):
        if self._state != 'OPEN':
            return self._state

        dst_branch = GitBranch(self.repo.gitrepo,
                               self.destination['branch']['name'])
        if dst_branch.includes_commit(self.source['branch']['name']):
            self._state = "MERGED"

        return self._state

    def full_name(self):
        return self['destination']['repository']['full_name']


class Comment(BitBucketObject):
    items = []

    def __init__(self, client, content, pull_request_id, full_name):
        #  URL params #
        self.pull_request_id = pull_request_id
        self.full_name = full_name

        #  JSON params #
        self.links = fake_links_dict(['self', 'html'])
        self.content = {"raw": content, "markup": "markdown", "html": content}
        self.created_on = datetime.now()
        self.user = fake_user_dict(client.login)
        self.updated_on = "2013-11-19T21:19:24.141013+00:00"
        self.id = len(Comment.items) + 1

    def create(self):
        self.__class__.items.append(self)
        return self

    @staticmethod
    def get_list(client, full_name, pull_request_id):
        return [c for c in Comment.items if c.full_name == full_name and
                c.pull_request_id == pull_request_id]


class Task(BitBucketObject, base.AbstractTask):
    add_url = 'legit_add_url'
    list_url = 'legit_list_url'
    items = []

    def __init__(self, client, content, pr_id, full_name, comment_id):
        #  URL params #
        self.pull_request_id = pr_id
        self.full_name = full_name
        self.comment_id = comment_id

        #  JSON params #
        self.content = {"raw": content}
        self.id = len(Task.items)

    def create(self):
        if self.add_url != 'legit_add_url':
            raise TaskAPIError('create', 'url does not work')
        self.__class__.items.append(self)
        return self

    @staticmethod
    def get_list(client, full_name, pull_request_id):
        if Task.list_url != 'legit_list_url':
            raise TaskAPIError('get_list', 'url does not work')
        return [t for t in Task.items if t.full_name == full_name and
                t.pull_request_id == pull_request_id]


class BuildStatus(BitBucketObject, base.AbstractBuildStatus):
    pass


class User(BitBucketObject):
    get_url = 'legit_get_url'

    def get(self):
        return fake_user_dict(self.login)
