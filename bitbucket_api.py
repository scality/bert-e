#!/usr/bin/env python
# -*- coding: utf-8 -*-

from string import Template
import json
import six
import urllib
from pybitbucket import auth
from pybitbucket.bitbucket import Client

if six.PY3:
    quote = urllib.parse.quote
else:
    quote = urllib.quote

def get_bitbucket_client(bitbucket_login, bitbucket_password, bitbucket_mail):
    authenticator = auth.BasicAuthenticator(
            bitbucket_login,
            bitbucket_password,
            bitbucket_mail)

    return Client(authenticator)


class BitBucketObject:
    main_url = None
    get_url = None

    def __init__(self, client, **kwargs):
        self.client = client
        self.reinit_json_data(kwargs)

    def reinit_json_data(self, json_data):
        self._json_data = json_data

    def __getitem__(self, item):
        return self._json_data[item]

    def __setitem__(self, item, value):
        self._json_data[item] = value

    @classmethod
    def get(cls, client, **kwargs):
        response = client.session.get(Template(cls.get_url).substitute(kwargs))
        client.expect_ok(response)
        return cls(client, **response.json())

    @classmethod
    def get_list(cls, client, **kwargs):
        response = client.session.get(Template(cls.main_url).substitute(kwargs))
        client.expect_ok(response)
        return [cls(client, **obj) for obj in response.json()['values'] if obj]  # FIXME: This code does not handle pagination!!!

    def create(self):
        json_str = json.dumps(self._json_data)
        response = self.client.session.post(
                Template(self.main_url).substitute(self._json_data),
                json_str
        )
        self.client.expect_ok(response)
        return self.__class__(self.client, **response.json())

    def delete(self):
        response = self.client.session.delete(Template(self.main_url).substitute(self._json_data))
        self.client.expect_ok(response)


class Repository(BitBucketObject):
    main_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug'

    def delete(self):
        try:
            assert self['slug'] != 'ring'  # This is a security, do not remove
        except KeyError:
            pass
        BitBucketObject.delete(self)

    def get_git_url(self):
        url = 'https://%s:%s@bitbucket.org/%s/%s.git' % (
            quote(self.client.config.username),
            quote(self.client.config.password),
            self['owner'],
            self['repo_slug'])
        return 'git@bitbucket.org:%s/%s' % (self['owner'], self['repo_slug'])

    def create_pull_request(self, **kwargs):
        # Documentation here
        # https://confluence.atlassian.com/bitbucket/pullrequests-resource-423626332.html#pullrequestsResource-POST(create)anewpullrequest
        kwargs['full_name'] = self['owner'] + '/' + self['repo_slug']
        return PullRequest(self.client, **kwargs).create()

    def get_pull_requests(self, **kwargs):
        kwargs['full_name'] = self['owner'] + '/' + self['repo_slug']
        return PullRequest.get_list(self.client, **kwargs)

    def get_pull_request(self, **kwargs):
        kwargs['full_name'] = self['owner'] + '/' + self['repo_slug']
        return PullRequest.get(self.client, **kwargs)


class PullRequest(BitBucketObject):
    main_url = 'https://api.bitbucket.org/2.0/repositories/$full_name/pullrequests'
    get_url = 'https://api.bitbucket.org/2.0/repositories/$full_name/pullrequests/$pull_request_id'

    def full_name(self):
        return self['destination']['repository']['full_name']

    def add_comment(self, msg):
        return Comment(self.client, content=msg, full_name=self.full_name(), pull_request_id=self['id']).create()

    def get_comments(self):
        return Comment.get_list(self.client, full_name=self.full_name(), pull_request_id=self['id'])

    def merge(self):
        self._json_data['full_name'] = self.full_name()
        self._json_data['pull_request_id'] = self['id']
        json_str = json.dumps(self._json_data)
        response = self.client.session.post(
                Template(self.get_url + '/merge').substitute(self._json_data),
                json_str)
        self.client.expect_ok(response)


class Comment(BitBucketObject):
    main_url = 'https://api.bitbucket.org/2.0/repositories/$full_name/pullrequests/$pull_request_id/comments'

    def create(self):
        json_str = json.dumps({'content': self._json_data['content']})
        response = self.client.session.post(
                Template(self.main_url).substitute(self._json_data).replace('/2.0/', '/1.0/'),
                # The 2.0 API does not create comments :(
                json_str
        )
        self.client.expect_ok(response)
        return self.__class__(self.client, **response.json())
