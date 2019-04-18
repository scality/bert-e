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

import json
import logging
from pathlib import Path
from string import Template
from urllib.parse import quote_plus as quote, urlparse

from requests import HTTPError
from requests.auth import HTTPBasicAuth

from . import schema
from .. import base, cache, factory
from bert_e.exceptions import TaskAPIError

MAX_PR_TITLE_LEN = 255

LOG = logging.getLogger(__name__)


def fix_pull_request_title(title):
    if len(title) < MAX_PR_TITLE_LEN:
        return title
    return title[:MAX_PR_TITLE_LEN - 4] + '...'


def build_filter_query(filters):
    """Build a filter query based on a filter dict."""
    predicates = []
    for key, val in filters.items():

        pred_str = ' OR '.join('{} = "{}"'.format(key, sub) for sub in val)
        if len(val) > 1:
            pred_str = "({})".format(pred_str)
        predicates.append(pred_str)

    return quote(' AND '.join(predicates))


@factory.api_client('bitbucket')
class Client(base.BertESession, base.AbstractClient):
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail):
        super().__init__()
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Bert-E',
            'Content-type': 'application/json',
            'From': bitbucket_mail
        }
        self.login = bitbucket_login
        self.email = bitbucket_mail
        self.headers.update(headers)
        self.auth = HTTPBasicAuth(bitbucket_login, bitbucket_password)

    def get_repository(self, slug, owner=None):
        """Get the repository with the associated owner and slug."""
        if owner is None:
            owner = self.login
        try:
            repo = Repository.get(self, repo_slug=slug, owner=owner)
        except HTTPError as err:
            raise base.NoSuchRepository('/'.join((owner, slug))) from err

        repo['repo_slug'] = slug
        return repo

    def create_repository(self, slug, owner=None, scm='git', is_private=True):
        """Create a Bitbucket Repository"""
        owner = owner or self.login
        repo = Repository(self, repo_slug=slug, owner=owner, scm=scm,
                          is_private=is_private)
        try:
            repo.create()
        except HTTPError as err:
            if err.response.status_code == 400:
                raise base.RepositoryExists('/'.join((owner, slug))) from err
            raise
        return repo

    def delete_repository(self, slug, owner=None):
        """Delete a bitbucket repository"""
        if owner is None:
            owner = self.login
        repo = Repository(self, repo_slug=slug, owner=owner)
        try:
            repo.delete()
        except HTTPError as err:
            if err.response.status_code == 404:
                raise base.NoSuchRepository('/'.join((owner, slug))) from err
            raise

    def _get(self, url, **kwargs):
        """Perform an HTTP GET request to the bitbucket API.

        Args: same as requests.get()

        Returns: a deserialized json structure

        Raises: requests.HTTPError

        """
        response = super().get(url, **kwargs)
        response.raise_for_status()
        return json.loads(response.text)

    def iter_get(self, url, **kwargs):
        next_page = url
        while next_page:
            result = self._get(next_page)
            try:
                next_page = result['next']
            except KeyError:
                next_page = None
            yield from result['values']


class BitBucketObject(object):
    list_url = None  # type: str
    add_url = None   # type: str
    get_url = None   # type: str

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
        request = Template(cls.get_url).substitute(kwargs)
        response = client.get(request)
        response.raise_for_status()
        return cls(client, **response.json())

    @classmethod
    def get_list(cls, client, **kwargs):
        for page in range(1, 100):  # Max 100 pages retrieved
            kwargs['page'] = page
            request = Template(cls.list_url).substitute(kwargs)
            response = client.get(request)
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
        request = Template(self.add_url).substitute(self._json_data)
        response = self.client.post(request, json_str)
        try:
            response.raise_for_status()
        except HTTPError:
            LOG.error(response.text)
            raise
        return self.__class__(self.client, **response.json())

    def delete(self):
        response = self.client.delete(Template(self.get_url)
                                      .substitute(self._json_data))
        response.raise_for_status()


class Repository(BitBucketObject, base.AbstractRepository):
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug'
    get_url = add_url

    def get_git_url(self):
        return 'https://%s:%s@bitbucket.org/%s/%s.git' % (
            quote(self.client.auth.username),
            quote(self.client.auth.password),
            self.owner,
            self.slug)

    def get_commit_url(self, revision):
        return 'https://bitbucket.org/%s/%s/commits/%s' % (
            self.owner,
            self.slug,
            revision)

    def create_pull_request(self, title, src_branch, dst_branch,
                            description, **kwargs):
        kwargs.update({
            'title': fix_pull_request_title(title),
            'source': {'branch': {'name': src_branch}},
            'destination': {'branch': {'name': dst_branch}},
            'description': description,
            'full_name': self.full_name
        })
        return PullRequest(self.client, **kwargs).create()

    def get_pull_requests(self, author=None, src_branch=None, status='OPEN'):
        filters = {'state': [status.lower()]}
        if author:
            filters['author.account_id'] = [author]
        if isinstance(src_branch, str):
            filters['source.branch.name'] = [src_branch]
        elif src_branch is not None:
            filters['source.branch.name'] = list(src_branch)

        filter_query = ''
        if filters:
            filter_query = 'q={}&'.format(build_filter_query(filters))

        return PullRequest.get_list(self.client, full_name=self.full_name,
                                    filters=filter_query)

    def get_pull_request(self, pull_request_id):
        return PullRequest.get(self.client,
                               pull_request_id=pull_request_id,
                               full_name=self.full_name)

    def get_build_url(self, revision, key):

        kwargs = {
            'owner': self.owner,
            'repo_slug': self.slug,
            'revision': revision,
            'key': key
        }

        status = cache.BUILD_STATUS_CACHE[key].get(revision, None)
        if status is not None:
            return status.url

        # Check against Bitbucket
        try:
            status = BuildStatus.get(self.client, **kwargs)
        except HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        else:
            return cache.BUILD_STATUS_CACHE[key].set(revision, status).url

    def get_build_status(self, revision, key):
        kwargs = {
            'owner': self.owner,
            'repo_slug': self.slug,
            'revision': revision,
            'key': key
        }

        # Check if a successful build for this revision is in cache
        cached = cache.BUILD_STATUS_CACHE[key].get(revision, None)
        if cached and cached.state == 'SUCCESSFUL':
            LOG.debug('Build on %s: cache GET (%s)', revision, cached.state)
            return cached.state

        LOG.debug('Build on %s: cache MISS', revision)

        # Either not in cache or wasn't successful last time. Check BB again.
        try:
            status = BuildStatus.get(self.client, **kwargs)
        except HTTPError as e:
            if e.response.status_code == 404:
                return 'NOTSTARTED'
            raise
        else:
            return cache.BUILD_STATUS_CACHE[key].set(revision, status).state

    def invalidate_build_status_cache(self):
        """Reset cache entries (useful for tests)."""
        cache.BUILD_STATUS_CACHE.clear()

    def set_build_status(self, revision, key, state, **kwargs):
        kwargs.update({
            'owner': self.owner,
            'repo_slug': self.slug,
            'revision': revision,
            'key': key,
            'state': state
        })
        return BuildStatus(self.client, **kwargs).create()

    def get_webhooks(self, **kwargs):
        kwargs.update({'owner': self.owner, 'repo_slug': self.slug})
        return WebHook.get_list(self.client, **kwargs)

    def create_webhook(self, **kwargs):
        kwargs.update({'owner': self.owner, 'repo_slug': self.slug})
        return WebHook(self.client, **kwargs).create()

    def delete_webhooks_with_title(self, title):
        kwargs = {'owner': self.owner, 'repo_slug': self.slug}
        for webhook in self.get_webhooks(**kwargs):
            if webhook['description'] == title:
                webhook['owner'] = self['owner']
                webhook['repo_slug'] = self['repo_slug']
                webhook['uid'] = webhook['uuid']
                webhook.delete()

    @property
    def full_name(self):
        return '/'.join((self.owner, self.slug))

    @property
    def owner(self):
        owner = self['owner']
        if isinstance(owner, dict):
            owner = owner['username']
        return owner

    @property
    def slug(self):
        return self['repo_slug']

    @property
    def git_url(self):
        return self.get_git_url()


class PullRequest(BitBucketObject, base.AbstractPullRequest):
    add_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests')
    list_url = add_url + '?${filters}page=$page'
    get_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id')

    def full_name(self):
        return self['destination']['repository']['full_name']

    def add_comment(self, msg):
        return Comment.create(
            self.client,
            data=msg,
            full_name=self.full_name(),
            pull_request_id=self['id']
        )

    def get_comments(self, deleted=False):
        return sorted(
            (comment
             for comment
             in Comment.list(
                 self.client, full_name=self.full_name(),
                 pull_request_id=self.id)
             if not comment.deleted or deleted),
            key=lambda c: c.id
        )

    def get_tasks(self):
        return Task.get_list(self.client, full_name=self.full_name(),
                             pull_request_id=self['id'])

    def get_change_requests(self):
        # Not supported by bitbucket, default to an empty tuple of usernames
        return tuple()

    def get_approvals(self):
        for participant in self['participants']:
            if participant['approved']:
                yield participant['user']['account_id'].lower()

    def get_participants(self):
        for participant in self['participants']:
            yield participant['user']['account_id'].lower()

    def merge(self):
        self._json_data['full_name'] = self.full_name()
        self._json_data['pull_request_id'] = self['id']
        json_str = json.dumps(self._json_data)
        response = self.client.post(Template(self.get_url + '/merge')
                                    .substitute(self._json_data),
                                    json_str)
        response.raise_for_status()

    def comment_review(self):
        raise NotImplementedError('"Commented review" feature '
                                  'is not available in bitbucket')

    def request_changes(self):
        raise NotImplementedError('"request changes" feature '
                                  'is not available in bitbucket')

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

    def dismiss(self):
        raise NotImplementedError('"dismiss" feature '
                                  'is not available in bitbucket')

    @property
    def id(self):
        return self['id']

    @property
    def title(self):
        return self['title']

    @property
    def author(self):
        return self['author']['account_id'].lower()

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
        self['source']['commit']['hash'] = sha1

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
        if not hasattr(self, '_comments') or not(self._comments):
            self._comments = list(self.get_comments())
        return self._comments


class Comment(base.AbstractGitHostObject, base.AbstractComment):
    CREATE_URL = ('https://api.bitbucket.org/2.0/repositories/'
                  '{full_name}/pullrequests/{pull_request_id}/comments')
    LIST_URL = CREATE_URL
    GET_URL = CREATE_URL + '/{comment_id}'
    DELETE_URL = GET_URL

    SCHEMA = schema.Comment
    CREATE_SCHEMA = schema.CreateComment

    def full_name(self):
        p = Path(urlparse(self.data['links']['self']['href']).path).resolve()
        return '%s/%s' % p.parts[3:5]

    def add_task(self, msg):
        return Task(self.client, content=msg, full_name=self.full_name(),
                    pull_request_id=self.data['pullrequest']['id'],
                    comment_id=self.id).create()

    def delete(self):
        return super().delete(self.client, full_name=self.full_name(),
                              pull_request_id=self.data['pullrequest']['id'],
                              comment_id=self.id)

    @classmethod
    def create(cls, client, data, **kwargs):
        return super().create(client, {'content': {'raw': data}}, **kwargs)

    @property
    def author(self):
        return self.data['user']['account_id'].lower()

    @property
    def text(self):
        return self.data['content']['raw']

    @property
    def id(self):
        return self.data['links']['self']['href'].rsplit('/', 1)[-1]

    @property
    def deleted(self):
        return self.data['deleted']


class Task(BitBucketObject, base.AbstractTask):
    get_url = 'https://bitbucket.org/!api/internal/repositories/$full_name/' \
        'pullrequests/$pull_request_id/tasks/$task_id'
    add_url = 'https://bitbucket.org/!api/internal/repositories/$full_name/' \
        'pullrequests/$pull_request_id/tasks'
    list_url = add_url + '?page=$page'

    def __init__(self, client, **kwargs):
        super().__init__(client, **kwargs)
        if 'comment_id' in self._json_data:
            self._json_data['comment'] = {'id': self._json_data['comment_id']}
        if 'content' in self._json_data:
            self._json_data['content'] = {'raw': self._json_data['content']}

    def create(self, *args, **kwargs):
        try:
            return super().create(*args, **kwargs)
        except Exception as err:
            raise TaskAPIError('create', err)

    def delete(self, *args, **kwargs):
        try:
            return super().delete(*args, **kwargs)
        except Exception as err:
            raise TaskAPIError('delete', err)

    def get(self, *args, **kwargs):
        try:
            return super().get(*args, **kwargs)
        except Exception as err:
            raise TaskAPIError('get', err)

    @classmethod
    def get_list(self, *args, **kwargs):
        try:
            return list(super().get_list(*args, **kwargs))
        except Exception as err:
            raise TaskAPIError('get_list', err)


class BuildStatus(BitBucketObject, base.AbstractBuildStatus):
    get_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/' \
        'commit/$revision/statuses/build/$key'
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/' \
        '$repo_slug/commit/$revision/statuses/build'
    list_url = add_url + '?page=$page'

    @property
    def state(self) -> str:
        return self._json_data['state']

    @property
    def url(self) -> str:
        return self._json_data['url']

    @property
    def description(self) -> str:
        return self._json_data['description']

    @property
    def key(self) -> str:
        return self._json_data['key']

    def __str__(self) -> str:
        return self.state


class WebHook(BitBucketObject):
    get_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/' \
        'hooks/$uid'
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/'\
        'hooks'
    list_url = add_url + '?page=$page'
