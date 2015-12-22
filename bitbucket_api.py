#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pybitbucket import auth
from pybitbucket.bitbucket import Client
from pybitbucket.pullrequest import PullRequest
from pybitbucket.repository import Repository
import json
import os
import unittest
from cmd import cmd

from tempfile import mkdtemp




def get_bitbucket_client(bitbucket_login, bitbucket_password, bitbucket_mail):

    authenticator = auth.BasicAuthenticator(
            bitbucket_login,
            bitbucket_password,
            bitbucket_mail)

    return Client(authenticator)

class BitbucketRepo:
    def __init__(self, client, owner, slug):
        self._client = client
        self._owner = owner
        self._slug = slug
        self._full_name = owner + '/' + slug
        self._api_url = 'https://api.bitbucket.org/2.0/repositories/' + self._full_name
        self._git_url = 'git@bitbucket.org:'+self._full_name

    def delete(self):
        assert self._slug != 'ring' # This is a security, do not remove
        response = self._client.session.delete(self._api_url)
        self._client.expect_ok(response)

    def create(self):
        payload = Repository.make_new_repository_payload(
            fork_policy='no_forks',
            is_private=True,
            scm='git',
        )
        json_str = json.dumps(payload)
        response = self._client.session.post(self._api_url, data=json_str)
        self._client.expect_ok(response)

    def init(self):
        #resetting the repo
        assert self._slug != 'ring' # This is a security, do not remove
        tmpdir = mkdtemp(self._slug)
        os.mkdir(tmpdir +'/' + self._slug)
        os.chdir(tmpdir +'/' + self._slug)
        cmd('git init')
        cmd('touch a')
        cmd('git add a')
        cmd('git commit -m "Initial commit"')
        cmd('git remote add origin ' + self._git_url)
        cmd('git push --set-upstream origin master')

    @staticmethod
    def create_branch(name, from_branch=None, file=False, do_push=True):
        if from_branch:
            cmd('git checkout '+from_branch)
        cmd('git checkout -b '+name)
        if file:
            if file is True:
                file = name.replace('/', '-')
            cmd('echo %s >  a.%s'%(name, file))
            cmd('git add a.'+file)
            cmd('git commit -m "commit %s"'%file)
        if do_push:
            cmd('git push --set-upstream origin '+name)

    def create_ring_branching_model(self):
        for version in ['4.3', '5.1', '6.0', 'trunk']:
            self.create_branch('release/'+version)
            self.create_branch('development/'+version, 'release/'+version, file=True)



class BitbucketPullRequest(PullRequest):

    @staticmethod
    def create(client, repo_full_name, source_branch_name, destination_branch_name, reviewers, title, description=''):
        _api_url = 'https://api.bitbucket.org/2.0/repositories/' + repo_full_name + '/pullrequests'
        payload = BitbucketPullRequest.make_new_pullrequest_payload(
            title=title,
            source_branch_name=source_branch_name,
            source_repository_full_name=repo_full_name,
            destination_branch_name=destination_branch_name,
            close_source_branch=True,
            description=description,
            #reviewers=['scality_wall-e']
        )
        payload['reviewers'] = [{'username': reviewer} for reviewer in reviewers]
        json_str = json.dumps(payload)
        response = client.session.post(_api_url, data=json_str)
        Client.expect_ok(response)
        return response.json()['id']

    @staticmethod
    def get_list_of_approving_reviewers(pr):
        res = []
        for participant in pr.participants:
            if not participant['role'] == 'REVIEWER':
                continue
            if not participant['approved']:
                continue
            res.append(participant['user']['username'])

        return res

    @staticmethod
    def get_participants(pr):
        return {participant['user']['username']: participant for participant in pr.participants}




def create_pullrequest_comment(connection, repo_full_name, pullrquest_id, msg):
    _api_url = 'https://bitbucket.org/api/1.0/repositories/%s/pullrequests/%s/comments'%(
        repo_full_name,
        pullrquest_id)
    data = {"content": msg}
    response = connection.session.post(_api_url, json=data)
    Client.expect_ok(response)


if __name__ == '__main__':
    unittest.main()


