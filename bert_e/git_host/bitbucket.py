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

import json
import logging
from collections import defaultdict
from string import Template
from urllib.parse import quote_plus as quote

from requests import HTTPError, Session
from requests.auth import HTTPBasicAuth

from . import base, factory
from ..exceptions import TaskAPIError
from ..utils import LRUCache

MAX_PR_TITLE_LEN = 255

BUILD_STATUS_CACHE = defaultdict(LRUCache)  # type: Dict[str, LRUCache]

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
class Client(Session, base.AbstractClient):
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
        return Repository(self, repo_slug=slug, owner=owner)

    def create_repository(self, slug, scm='git', is_private=True):
        """Create a Bitbucket Repository"""
        owner = self.login
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
        LOG.debug("GET %s", request)
        response = client.get(request)
        response.raise_for_status()
        return cls(client, **response.json())

    @classmethod
    def get_list(cls, client, **kwargs):
        for page in range(1, 100):  # Max 100 pages retrieved
            kwargs['page'] = page
            request = Template(cls.list_url).substitute(kwargs)
            LOG.debug("GET %s", request)
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
        LOG.debug("POST %s", request)
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
            filters['author.username'] = [author]
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

        key = '{}-build'.format(revision)
        build_url = BUILD_STATUS_CACHE[key].get(revision, None)
        if build_url is not None:
            return build_url

        # Check against Bitbucket
        try:
            status = BuildStatus.get(self.client, **kwargs)
        except HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        else:
            return BUILD_STATUS_CACHE[key].set(revision, status['url'])

    def get_build_status(self, revision, key):
        kwargs = {
            'owner': self.owner,
            'repo_slug': self.slug,
            'revision': revision,
            'key': key
        }

        # Check if a successful build for this revision is in cache
        status = BUILD_STATUS_CACHE[key].get(revision, None)
        if status == 'SUCCESSFUL':
            LOG.debug('Build on %s: cache GET (%s)', revision, status)
            return status

        LOG.debug('Build on %s: cache MISS (%s)', revision, status)

        # Either not in cache or wasn't successful last time. Check BB again.
        try:
            status = BuildStatus.get(self.client, **kwargs)
            return BUILD_STATUS_CACHE[key].set(revision, status['state'])
        except HTTPError as e:
            if e.response.status_code == 404:
                return BUILD_STATUS_CACHE[key].set(revision, 'NOTSTARTED')
            raise

    def invalidate_build_status_cache(self):
        """Reset cache entries (useful for tests)."""
        BUILD_STATUS_CACHE.clear()

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
        return self['owner']

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
        return Comment(self.client, content=msg, full_name=self.full_name(),
                       pull_request_id=self['id']).create()

    def get_comments(self):
        return sorted(
            Comment.get_list(
                self.client, full_name=self.full_name(),
                pull_request_id=self.id),
            key=lambda c: c.id
        )

    def get_tasks(self):
        return Task.get_list(self.client, full_name=self.full_name(),
                             pull_request_id=self['id'])

    def get_approvals(self):
        for participant in self['participants']:
            if participant['approved']:
                yield participant['user']['username']

    def get_participants(self):
        for participant in self['participants']:
            yield participant['user']['username']

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

    @property
    def id(self):
        return self['id']

    @property
    def title(self):
        return self['title']

    @property
    def author(self):
        return self['author']['username']

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


class Comment(BitBucketObject, base.AbstractComment):
    add_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id/comments')
    list_url = add_url + '?page=$page'
    get_url = ('https://api.bitbucket.org/2.0/repositories/'
               '$full_name/pullrequests/$pull_request_id/comments/$comment_id')

    def full_name(self):
        return '%s/%s' % (self._json_data['pr_repo']['owner'],
                          self._json_data['pr_repo']['slug'])

    def add_task(self, msg):
        return Task(self.client, content=msg, full_name=self.full_name(),
                    pull_request_id=self['pull_request_id'],
                    comment_id=self['comment_id']).create()

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

    @property
    def author(self):
        return self['user']['username']

    @property
    def text(self):
        return self['content']['raw']

    @property
    def id(self):
        return self['id']


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


class BuildStatus(BitBucketObject):
    get_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/' \
        'commit/$revision/statuses/build/$key'
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/' \
        '$repo_slug/commit/$revision/statuses/build'
    list_url = add_url + '?page=$page'


class WebHook(BitBucketObject):
    get_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/' \
        'hooks/$uid'
    add_url = 'https://api.bitbucket.org/2.0/repositories/$owner/$repo_slug/'\
        'hooks'
    list_url = add_url + '?page=$page'