#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import requests

from ...api.git import Repository as GitRepository, Branch as GitBranch


def fake_user_dict(username):
    return {
        "username": username,
        "display_name": username,
        "uuid": "{1cd06601-cd0e-4fce-be03-e9ac226978b7}",
        "links": fake_links_dict(['avatar', 'html', 'self']),
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


class Client:
    def __init__(self, username, password, email):
        self.username = username
        self.password = password
        self.auth = self


class BitBucketObject(object):
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


class Controller(object):
    def __init__(self, client, controlled):
        self.controlled = controlled
        self.client = client

    def __getitem__(self, item):
        return self.controlled.__getattribute__(item)

    def __setitem__(self, item, value):
        return self.controlled.__setattr__(item, value)


class Repository(BitBucketObject):
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
        self.owner = fake_user_dict(client.username)
        self.updated_on = "2014-11-03T02:24:08.409995+00:00"
        self.size = 76182262
        self.is_private = is_private
        self.uuid = "{9970a9b6-2d86-413f-8555-da8e1ac0e542}"

        # ###############

    def delete(self):
        BitBucketObject.delete(self)
        PullRequest.items = []
        Comment.items = []

    def create(self):
        self.gitrepo = GitRepository(None)
        self.gitrepo.cmd('git init')
        self.gitrepo.revisions = {}  # UGLY
        Repository.repos[(self.repo_owner, self.repo_slug)] = self.gitrepo
        return BitBucketObject.create(self)

    def get_git_url(self):
        self.gitrepo = Repository.repos[(self.repo_owner, self.repo_slug)]
        return self.gitrepo.tmp_directory

    def create_pull_request(self, title, name, source, destination,
                            close_source_branch, description, reviewers=[]):
        self.get_git_url()
        pr = PullRequest(self, title, name, source, destination,
                         close_source_branch, reviewers, description).create()
        prc = PullRequestController(self.client, pr)
        for reviewer in reviewers:
            prc.add_participant(reviewer)
        return prc

    def get_pull_requests(self):
        return [PullRequestController(self.client, item)
                for item in PullRequest.items]

    def get_pull_request(self, pull_request_id):
        assert type(pull_request_id) == int
        for pr in self.get_pull_requests():
            if pr['id'] == pull_request_id:
                return pr
        raise Exception("Did not find this pr")

    def get_build_status(self, revision, key):
        try:
            return self.gitrepo.revisions[(revision, key)]
        except KeyError:
            return 'NOTSTARTED'

    def invalidate_build_status_cache(self):
        pass

    def set_build_status(self, revision, key, state, name, url):
        self.get_git_url()
        self.gitrepo.revisions[(revision, key)] = state


class PullRequestController(Controller):
    def add_comment(self, msg):
        comment = Comment(self.client, content=msg,
                          full_name=self.controlled.full_name(),
                          pull_request_id=self.controlled.id).create()

        self.update_participant(role='PARTICIPANT')
        return comment

    def get_comments(self):
        return [Controller(self.client, c) for c in Comment.get_list(
                self.client, full_name=self.controlled.full_name(),
                pull_request_id=self.controlled.id)]

    def merge(self):
        raise NotImplemented('Merge')

    def approve(self):
        self.update_participant(approved=True, role='REVIEWER')

    def update_participant(self, approved=None, role=None):
        # locate participant
        exists = False
        for participant in self['participants']:
            if participant['user']['username'] == self.client.username:
                exists = True
                break

        if not exists:
            # new participant
            self.add_participant(fake_user_dict(self.client.username))
            participant = self['participants'][-1]

        # update it
        if approved is not None:
            participant['approved'] = approved
        if role is not None:
            # role cannot downgrade from REVIEWER to PARTICIPANT
            if participant['role'] == 'REVIEWER' and role == 'PARTICIPANT':
                role = 'REVIEWER'
            participant['role'] = role

    def add_participant(self, user_struct):
        self['participants'].append({
            'user': user_struct,
            'approved': False,
            'role': 'PARTICIPANT'})

    def decline(self):
        self['_state'] = "DECLINED"


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
        self.author = fake_user_dict(self.client.username)

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
            ['activity', 'approve', 'comments', 'commits',
             'decline', 'diff', 'html', 'merge', 'self'])
        self.merge_commit = None
        self.participants = []
        self.reason = ""
        self.source = {
            "branch": source['branch'],
            "commit": Branch(self.repo.gitrepo, source['branch']['name']),
            "repository": fake_repository_dict("")
        }
        self.task_count = 1
        self.title = "Changes"
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
        self.created_on = "2013-11-19T21:19:24.138375+00:00"
        self.user = fake_user_dict(client.username)
        self.updated_on = "2013-11-19T21:19:24.141013+00:00"
        self.id = len(Comment.items) + 1

    def create(self):
        self.__class__.items.append(self)
        return self

    @staticmethod
    def get_list(client, full_name, pull_request_id):
        return [c for c in Comment.items if c.full_name == full_name and
                c.pull_request_id == pull_request_id]


class BuildStatus(BitBucketObject):
    pass