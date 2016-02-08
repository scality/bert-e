#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
from git_api import Repository as GitRepository, Branch as GitBranch


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
        return PullRequestController(self.client, pr)

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
            raise requests.exceptions.HTTPError(response=Error404Response())

    def set_build_status(self, revision, key, state, name, url):
        self.get_git_url()
        self.gitrepo.revisions[(revision, key)] = {'state': state}


class PullRequestController(Controller):
    def add_comment(self, msg):
        return Comment(self.client, content=msg,
                       full_name=self.controlled.full_name(),
                       pull_request_id=self.controlled.id).create()

    def get_comments(self):
        return [Controller(self.client, c) for c in Comment.get_list(
                self.client, full_name=self.controlled.full_name(),
                pull_request_id=self.controlled.id)]

    def merge(self):
        raise NotImplemented('Merge')

    def approve(self):
        self['participants'].append({
            "approved": True,
            "role": "REVIEWER",
            "user": fake_user_dict(self.client.username)
        })


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
        self.id = len(PullRequest.items)
        self.links = fake_links_dict(
            ['activity', 'approve', 'comments', 'commits',
             'decline', 'diff', 'html', 'merge', 'self'])
        self.merge_commit = None
        self.participants = []
        self.reason = ""
        self.reviewers = reviewers
        self.source = {
            "branch": source['branch'],
            "commit": Branch(self.repo.gitrepo, source['branch']['name']),
            "repository": fake_repository_dict("")
        }
        self.task_count = 1
        self.title = "Changes"
        self.type = "pullrequest"
        self.updated_on = "2016-01-12T19:31:23.673329+00:00"

    @property
    def state(self):
        dst_branch = GitBranch(self.repo.gitrepo,
                               self.destination['branch']['name'])
        if dst_branch.includes_commit(self.source['branch']['name']):
            return "FULFILLED"
        return "OPEN"

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
        self.id = len(Comment.items)

    @staticmethod
    def get_list(client, full_name, pull_request_id):
        return [c for c in Comment.items if c.full_name == full_name and
                c.pull_request_id == pull_request_id]


class BuildStatus(BitBucketObject):
    pass
