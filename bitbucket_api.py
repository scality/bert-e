#!/usr/bin/env python
# -*- coding: utf-8 -*-

from string import Template
import json
import six
import urllib

from requests import Session
from requests.auth import HTTPBasicAuth

if six.PY3:
    quote = urllib.parse.quote
    from past.builtins import xrange
else:
    quote = urllib.quote


class Client(Session):
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail):
        Session.__init__(self)
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Wall-E',
            'Content-type': 'application/json',
            'From': bitbucket_mail}
        self.mail = bitbucket_mail
        self.headers.update(headers)
        self.auth = HTTPBasicAuth(bitbucket_login, bitbucket_password)


class BitBucketObject(object):
    list_url = None
    add_url = None
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
        response = client.get(Template(cls.get_url).substitute(kwargs))
        response.raise_for_status()
        return cls(client, **response.json())

    @classmethod
    def get_list(cls, client, **kwargs):
        for page in xrange(1, 100):  # Max 100 pages retrieved
            kwargs['page'] = page
            response = client.get(Template(cls.list_url)
                                  .substitute(kwargs))
            response.raise_for_status()
            for obj in response.json()['values']:
                if obj:
                    yield cls(client, **obj)
            try:
                response.json()['next']
            except KeyError:
                return

    def create(self):
        json_str = json.dumps(self._json_data)
        response = self.client.post(Template(self.add_url)
                                    .substitute(self._json_data),
                                    json_str)
        response.raise_for_status()
        return self.__class__(self.client, **response.json())

    def delete(self):
        response = self.client.delete(Template(self.get_url)
                                      .substitute(self._json_data))
        response.raise_for_status()


class Repository(BitBucketObject):
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug'
    get_url = add_url

    def delete(self):
        try:
            assert self['slug'] != 'ring'  # This is a security, do not remove
        except KeyError:
            pass
        BitBucketObject.delete(self)

    def get_git_url(self):
        return 'https://%s:%s@bitbucket.org/%s/%s.git' % (
            quote(self.client.auth.username),
            quote(self.client.auth.password),
            self['owner'],
            self['repo_slug'])

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

    def get_build_status(self, **kwargs):
        kwargs['owner'] = self['owner']
        kwargs['repo_slug'] = self['repo_slug']
        return BuildStatus.get(self.client, **kwargs)

    def set_build_status(self, **kwargs):
        kwargs['owner'] = self['owner']
        kwargs['repo_slug'] = self['repo_slug']
        return BuildStatus(self.client, **kwargs).create()


class PullRequest(BitBucketObject):
    add_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests')
    list_url = add_url + '?page=$page'
    get_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id')

    def full_name(self):
        return self['destination']['repository']['full_name']

    def add_comment(self, msg):
        return Comment(self.client, content=msg, full_name=self.full_name(),
                       pull_request_id=self['id']).create()

    def get_comments(self):
        return Comment.get_list(self.client, full_name=self.full_name(),
                                pull_request_id=self['id'])

    def merge(self):
        self._json_data['full_name'] = self.full_name()
        self._json_data['pull_request_id'] = self['id']
        json_str = json.dumps(self._json_data)
        response = self.client.post(Template(self.get_url + '/merge')
                                    .substitute(self._json_data),
                                    json_str)
        response.raise_for_status()

    def approve(self):
        self._json_data['full_name'] = self.full_name()
        self._json_data['pull_request_id'] = self['id']
        json_str = json.dumps(self._json_data)
        response = self.client.post(Template(self.get_url + '/approve')
                                    .substitute(self._json_data),
                                    json_str)

        response.raise_for_status()

    def decline(self):
        self._json_data['full_name'] = self.full_name()
        self._json_data['pull_request_id'] = self['id']
        json_str = json.dumps(self._json_data)
        response = self.client.post(Template(self.get_url + '/decline')
                                    .substitute(self._json_data),
                                    json_str)
        response.raise_for_status()


class Comment(BitBucketObject):
    add_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id/comments')
    list_url = add_url + '?page=$page'
    get_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id/comments/$comment_id')

    def full_name(self):
        return '%s/%s' % (self._json_data['pr_repo']['owner'],
                          self._json_data['pr_repo']['slug'])

    def create(self):
        json_str = json.dumps({'content': self._json_data['content']})
        response = self.client.post(Template(self.add_url)
                                    .substitute(self._json_data)
                                    .replace('/2.0/', '/1.0/'),
                                    # The 2.0 API does not create
                                    # comments :(
                                    json_str)
        response.raise_for_status()
        return self.__class__(self.client, **response.json())

    def delete(self):
        self._json_data['full_name'] = self.full_name()
        response = self.client.delete(Template(self.get_url)
                                      .substitute(self._json_data)
                                      .replace('/2.0/', '/1.0/'))
        response.raise_for_status()


class BuildStatus(BitBucketObject):
    get_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/' \
        'commit/$revision/statuses/build/$key'
    list_url = 'https://api.bitbucket.org/2.0/repositories/$owner/' \
        '$repo_slug/commit/$revision/statuses/build'
    add_url = list_url
