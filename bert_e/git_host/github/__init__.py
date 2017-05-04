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
from collections import defaultdict, namedtuple

from requests import HTTPError, Session
from requests.auth import HTTPBasicAuth

from bert_e.exceptions import TaskAPIError
from bert_e.lib.lru_cache import LRUCache
from bert_e.lib.schema import (load as load_schema,
                               validate as validate_schema,
                               dumps as dump_schema)
from . import schema
from .. import base, factory

LOG = logging.getLogger(__name__)

BUILD_STATUS_CACHE = defaultdict(LRUCache)  # type: Dict[str, LRUCache]


class Error(base.Error):
    pass


class InvalidOperation(Error):
    pass


CacheEntry = namedtuple('CacheEntry', ['obj', 'etag', 'date'])


@factory.api_client('github')
class Client(base.AbstractClient):

    def __init__(self, login: str, password: str, email: str, org=None,
                 base_url='https://api.github.com'):
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Bert-E',
            'Content-Type': 'application/json',
            'From': email
        }

        rlog = logging.getLogger('requests.packages.urllib3.connectionpool')
        rlog.setLevel(logging.CRITICAL)
        self.session = Session()
        self.session.headers.update(headers)
        self.session.auth = HTTPBasicAuth(login, password)

        self.login = login
        self.email = email
        self.org = org
        self.base_url = base_url.rstrip('/')
        self.query_cache = defaultdict(LRUCache)

    def _patch_url(self, url):
        """Patch URLs if it is relative to the API root.

        Returns: an absolute url corresponding to client.base_url / url

        """
        if not url.startswith('http'):
            url = '/'.join((self.base_url, url.lstrip('/')))
        return url

    @staticmethod
    def _mk_key(url, params):
        return (url,) + tuple(sorted(params.items()))

    def _cache_value(self, method, url, params, res):
        """Put a request result in the query cache.

        If the response's headers contain an ETag or a Last-Modified field,
        the response can be used in subsequent calls to avoid hitting github's
        rate limit.

        Args:
            - method (str): request method (e.g. GET)
            - url (str): request url
            - params (dict): request parameter dict as per requests library's
                             params argument
            - res (requests.Response): the request's response

        Returns:
            The response that was put in cache.

        """
        key = self._mk_key(url, params)
        headers = res.headers
        etag = headers.get('ETag', None)
        date = headers.get('Last-Modified', None)
        if etag or date:
            self.query_cache[method].set(key, CacheEntry(res, etag, date))
        return res

    def _get_cached_value(self, method, url, params):
        """Get a value from the cache if any.

        This method is intended to be called before performing an HTTP request,
        in order to define the special headers used by GitHub's rate-limit
        system.

        If the request that follows returns a HTTP 304 code, this means that:
            - the cached value returned by this method can be returned as a
              valid result
            - the request wasn't decremented from GitHub's rate limit counter

        Args:
            - method (str): request method (e.g. GET)
            - url (str): request url
            - params (dict): request parameter dict as per requests library's
                             params argument

        Returns:
            A (response, headers) tuple.

            - response is the last response we've received for this request
              (possibly None).
            - headers is a dictionary defining 'If-None-Match' and
              'If-Modified-Since' headers to add to the request.

        See: the _get() method to understand how it is used.

        """

        key = self._mk_key(url, params)
        entry = self.query_cache[method].get(key, None)
        headers = {
            'If-None-Match': None,
            'If-Modified-Since': None
        }
        if entry is None:
            return None, headers
        if entry.etag:
            headers['If-None-Match'] = entry.etag
        elif entry.date:
            headers['If-Modified-Since'] = entry.date
        return entry.obj, headers

    def _get(self, url, **kwargs):
        """Perform a GET request using the rate-limit cache system.

        This method is not supposed to be called by other objects. Instead, it
        is wrapped by the get() and iter_get() methods.

        Returns:
            A requests.Response object

        """
        params = kwargs.get('params', {})
        url = self._patch_url(url)
        res, headers = self._get_cached_value('GET', url, params)
        if headers:
            kwargs.setdefault('headers', {}).update(headers)
        response = self.session.get(url, **kwargs)
        LOG.debug("GET %s %r -> %d", url, params, response.status_code)
        if response.status_code == 304:
            LOG.debug('Not Modified. Returning cached result')
            return res
        response.raise_for_status()
        return self._cache_value('GET', url, params, response)

    def get(self, url, **kwargs):
        """Perform an HTTP GET request to the github API.

        This method handles cache verfication and uses conditional requests
        + a local cache to avoid consuming API calls as counted by Github's
        rate limit system.

        Args: same as requests.get()

        Returns: a deserialized json structure

        Raises: requests.HTTPError

        """
        return json.loads(self._get(url, **kwargs).text)

    def post(self, url, data, **kwargs):
        """Perform a POST request to the github API.

        Args: same as requests.post()

        Returns: a deserialized json structure

        Raises:
            requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.post(url, data=data, **kwargs)
        LOG.debug("POST %s -> %d", url, response.status_code)
        response.raise_for_status()
        return json.loads(response.text)

    def patch(self, url, data, **kwargs):
        """Perform a PATCH request to the github API.

        Args: same as requests.patch()

        Returns: a deserialized json structure

        Raises:
            requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.post(url, data=data, **kwargs)
        LOG.debug("PATCH %s -> %d", url, response.status_code)
        response.raise_for_status()
        return json.loads(response.text)

    def delete(self, url, **kwargs):
        """Perform a DELETE request on the github API.

        Args: same as requests.delete()

        Raises: requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.delete(url, **kwargs)
        LOG.debug("DELETE %s -> %d", url, response.status_code)
        response.raise_for_status()

    def put(self, url, **kwargs):
        """Perform a PUT request to the Github API.

        Args: same as requests.put()

        Raises: requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.put(url, **kwargs)
        LOG.debug("PUT %s -> %d", url, response.status_code)
        response.raise_for_status()

    def iter_get(self, url, per_page=100, **kwargs):
        """Perform a paginated GET request to the Github API.

        This method handles cache verfication and uses conditional requests
        + a local cache to avoid consuming API calls as counted by Github's
        rate limit system.

        Args:
            - per_page: number of objects to get per page (max & default: 100)
            - same as requests.get()

        Yields: deserialized json structures

        Raises: requests.HTTPError

        """
        params = kwargs.setdefault('params', {})
        params.setdefault('per_page', per_page)
        next_page = url
        while next_page:
            response = self._get(next_page, **kwargs)
            yield from json.loads(response.text)

            next_page = None
            if 'link' not in response.headers:
                break
            for link_rel in response.headers['link'].split(','):
                link, rel = link_rel.split(';')
                if 'rel="next"' in rel.strip():
                    next_page = link.strip(' <>')
                    break

            # Params are already contained in the next page's url
            params.clear()

    def get_repository(self, slug: str, owner=None) -> base.AbstractRepository:
        """See AbstractClient.get_repository()"""
        if owner is None:
            owner = self.org or self.login
        try:
            return Repository.get(self, owner=owner, repo=slug)
        except HTTPError as err:
            if err.response.status_code == 404:
                raise base.NoSuchRepository(
                    '{}/{}'.format(owner, slug)) from err
            raise

    def create_repository(self, slug: str, owner=None, **kwargs):
        """See AbstractClient.create_repository()"""
        url = Repository.CREATE_URL
        owner = owner or self.login
        if owner != self.login:
            url = Repository.CREATE_ORG_URL
        kwargs['name'] = slug
        try:
            return Repository.create(self, kwargs, url=url, owner=owner)
        except HTTPError as err:
            if err.response.status_code == 422:
                raise base.RepositoryExists(slug) from err
            raise

    def delete_repository(self, slug: str, owner=None):
        """See AbstractClient.delete_repository()"""
        if owner is None:
            owner = self.login

        try:
            Repository.delete(self, owner=owner, repo=slug)
        except HTTPError as err:
            if err.response.status_code == 404:
                raise base.NoSuchRepository(
                    '{}/{}'.format(owner, slug)) from err
            raise


class GithubObject:
    """Generic implementation of a Github API object.

    A Github API object is basically a collection of classmethods to list, get,
    create or delete objects of this kind.

    To make concrete implementations shorter, any action that can be performed
    should define:
        - the URL to perform the action.
        - an optional schema to validate the request's data.
        - an optional schema to parse the response.

    GithubObject instances encapulate json-like data in their obj.data
    attribute.

    """

    LIST_URL = None         # URL used to list objects
    GET_URL = None          # URL used to get a specific object
    CREATE_URL = None       # URL used to create an object
    DELETE_URL = None       # URL used to delete an object
    UPDATE_URL = None       # URL used to update an object

    SCHEMA = None           # Default schema
    GET_SCHEMA = None       # Specific schema returned by GET requests
    LIST_SCHEMA = None      # Specific schema returned by LIST requests
    CREATE_SCHEMA = None    # Specific schema to create new objects
    UPDATE_SCHEMA = None    # Specific schema to update objects

    def __init__(self, client=None, _validate=True, **data):
        self.client = client
        if _validate and self.SCHEMA is not None:
            validate_schema(self.SCHEMA, data)
        self.data = data

    @classmethod
    def get(cls, client: Client, url=None, params={}, headers={}, **kwargs):
        """Get a Github API object.

        The result is parsed using cls.GET_SCHEMA, or cls.SCHEMA if absent.

        Args:
            - client: the Github client to use to perform the request.
            - url: a specific url to use for this request. Defaults to GET_URL.
            - params: the parameters of the GET request.
            - **kwargs: the parameters of the URL (named str.format style).

        Returns:
            The result of the query, parsed by the schema.

        """
        url = url or cls.GET_URL
        if url is None:
            raise InvalidOperation(
                'GET is not supported on {} objects'.format(cls.__name__))
        schema_cls = cls.GET_SCHEMA or cls.SCHEMA
        obj = cls.load(client.get(url.format(**kwargs), params=params,
                                  headers=headers),
                       schema_cls)
        obj.client = client
        return obj

    @classmethod
    def list(cls, client: Client, url=None, params={}, headers={}, **kwargs):
        """List objects.

        The result is parsed using cls.LIST_SCHEMA, or cls.GET_SCHEMA if
        absent, or cls.SCHEMA if both are absent.

        Args:
            - same as get()

        Yields:
            The elements of the response as they are parsed by the schema.

        """
        url = url or cls.LIST_URL
        if url is None:
            raise InvalidOperation(
                'LIST is not supported on {} objects.'.format(cls.__name__))
        schema_cls = cls.LIST_SCHEMA or cls.GET_SCHEMA or cls.SCHEMA
        for data in client.iter_get(url.format(**kwargs),
                                    params=params,
                                    headers=headers):
            obj = cls.load(data, schema_cls)
            obj.client = client
            yield obj

    @classmethod
    def load(cls, data, schema_cls=None, **kwargs):
        """Load data using the class' schema.

        Return a Github object
        """
        if schema_cls is None:
            schema_cls = cls.SCHEMA
        return cls(**load_schema(schema_cls, data, **kwargs), _validate=False)

    @classmethod
    def create(cls, client: Client, data, headers={}, url=None, **kwargs):
        """Create an object."""
        url = url or cls.CREATE_URL
        if url is None:
            raise InvalidOperation(
                'CREATE is not supported on {} objects.'.format(cls.__name__))

        create_schema_cls = cls.CREATE_SCHEMA or cls.SCHEMA
        json = dump_schema(create_schema_cls, data)
        obj = cls.load(
            client.post(url.format(**kwargs), data=json, headers=headers)
        )
        obj.client = client
        return obj

    @classmethod
    def update(cls, client: Client, data, headers={}, url=None, **kwargs):
        """Update an object."""
        url = url or cls.UPDATE_URL or cls.GET_URL
        if url is None:
            raise InvalidOperation(
                'CREATE is not supported on {} objects.'.format(cls.__name__))

        create_schema_cls = cls.UPDATE_SCHEMA or cls.SCHEMA
        json = dump_schema(create_schema_cls, data)
        obj = cls.load(
            client.patch(url.format(**kwargs), data=json, headers=headers)
        )
        obj.client = client
        return obj

    @classmethod
    def delete(cls, client: Client, **kwargs):
        """Delete an object."""
        if cls.DELETE_URL is None:
            raise InvalidOperation(
                'DELETE is not supported on {} objects.'.format(cls.__name__))
        client.delete(cls.DELETE_URL.format(**kwargs))


class Repository(GithubObject, base.AbstractRepository):
    GET_URL = '/repos/{owner}/{repo}'
    DELETE_URL = GET_URL
    CREATE_URL = '/user/repos'
    CREATE_ORG_URL = '/orgs/{owner}/repos'

    SCHEMA = schema.Repo
    GET_SCHEMA = schema.Repo
    CREATE_SCHEMA = schema.CreateRepo

    @property
    def full_name(self) -> str:
        return self.data['full_name']

    @property
    def owner(self) -> str:
        return self.data['owner']['login']

    @property
    def slug(self) -> str:
        return self.data['name']

    @property
    def git_url(self) -> str:
        return 'git@github.com:{}/{}'.format(self.owner, self.slug)

    def get_commit_url(self, revision):
        return 'https://github.com/{}/{}/commit/{}'.format(self.owner,
                                                           self.slug,
                                                           revision)

    def get_commit_status(self, ref):
        try:
            combined = AggregatedStatus.get(self.client,
                                            owner=self.owner,
                                            repo=self.slug, ref=ref)
        except HTTPError as err:
            if err.response.status_code == 404:
                return None
            raise

        for key, status in combined.status.items():
            BUILD_STATUS_CACHE[key].set(combined.commit, status)

        return combined

    def get_build_status(self, revision: str, key: str) -> str:
        status = BUILD_STATUS_CACHE[key].get(revision, None)
        if status and status.state == 'SUCCESSFUL':
            return status.state
        try:
            return self.get_commit_status(revision).status.get(key, None).state
        except AttributeError:
            return 'NOTSTARTED'

    def get_build_url(self, revision: str, key: str) -> str:
        # Only look inside the cache. There is no need for an API call for this
        # build's URL.
        status = BUILD_STATUS_CACHE[key].get(revision, None)
        if status:
            return status.url

    def get_build_description(self, revision: str, key: str) -> str:
        status = BUILD_STATUS_CACHE[key].get(revision, None)
        if status:
            return status.description

    def set_build_status(self, revision: str, key: str, state: str,
                         url='', description=''):
        trans = {
            'INPROGRESS': 'pending',
            'SUCCESSFUL': 'success',
            'FAILED': 'failure',
            'STOPPED': 'error',
            'NOTSTARTED': 'pending'
        }

        data = {
            'state': trans[state],
            'target_url': url,
            'description': description,
            'context': key
        }

        return Status.create(
            self.client, data=data, owner=self.owner, repo=self.slug,
            sha=revision
        )

    def get_pull_requests(self, author=None, src_branch=None, status='OPEN'):
        if author is None:
            author = self.owner

        query_state = {
            'OPEN': 'open',
            'MERGED': 'closed',
            'DECLINED': 'closed'
        }[status]

        if isinstance(src_branch, str):
            src_branch = [src_branch]
        if not src_branch:
            args = [{'state': query_state}]
        else:
            args = [{'head': '{}:{}'.format(author, b),
                     'state': query_state} for b in src_branch]

        for arg in args:
            for pull_request in PullRequest.list(self.client, params=arg,
                                                 owner=self.owner,
                                                 repo=self.slug):
                if pull_request.status == status:
                    yield pull_request

    def get_pull_request(self, pull_request_id):
        return PullRequest.get(self.client, owner=self.owner, repo=self.slug,
                               number=pull_request_id)

    def create_pull_request(self, title, src_branch, dst_branch, description,
                            **kwargs):
        kwargs.update({
            'title': title,
            'head': src_branch,
            'base': dst_branch,
            'body': description
        })
        return PullRequest.create(self.client, data=kwargs, owner=self.owner,
                                  repo=self.slug)


class AggregatedStatus(GithubObject):
    GET_URL = '/repos/{owner}/{repo}/commits/{ref}/status'
    SCHEMA = schema.AggregatedStatus

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._status = {}
        for status_data in self.data.get('statuses', []):
            status = Status(**status_data, _validate=False)
            self._status[status_data['context']] = status

    @property
    def commit(self) -> str:
        return self.data['sha']

    @property
    def status(self):
        return self._status


class Status(GithubObject):
    CREATE_URL = '/repos/{owner}/{repo}/statuses/{sha}'

    SCHEMA = schema.Status
    CREATE_SCHEMA = schema.Status

    @property
    def state(self) -> str:
        trans = {
            'pending': 'INPROGRESS',
            'success': 'SUCCESSFUL',
            'error': 'FAILED',
            'failure': 'FAILED',
            None: 'NOTSTARTED'
        }
        return trans[self.data['state']]

    @property
    def url(self):
        return self.data['target_url']

    @property
    def description(self):
        return self.data['description']

    @property
    def key(self):
        return self.data['context']


class PullRequest(GithubObject, base.AbstractPullRequest):
    LIST_URL = '/repos/{owner}/{repo}/pulls'
    GET_URL = '/repos/{owner}/{repo}/pulls/{number}'
    CREATE_URL = LIST_URL

    SCHEMA = schema.PullRequest
    CREATE_SCHEMA = schema.CreatePullRequest

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reviews = None

    @property
    def id(self) -> int:
        return int(self.data['number'])

    @property
    def title(self) -> str:
        return self.data['title']

    @property
    def author(self) -> str:
        return self.data['user']['login']

    @property
    def author_display_name(self) -> str:
        return self.data['user'].get('name', self.author)

    @property
    def description(self) -> str:
        return self.data.get('body', '')

    @property
    def src_branch(self) -> str:
        return self.data['head']['ref']

    @property
    def dst_branch(self) -> str:
        return self.data['base']['ref']

    @property
    def src_commit(self) -> str:
        return self.data['head']['sha']

    @src_commit.setter
    def src_commit(self, sha1):
        self.data['head']['sha'] = sha1

    @property
    def status(self) -> str:
        state = self.data['state']
        if state == 'open':
            return 'OPEN'
        elif self.data['merged_at']:
            return 'MERGED'
        else:
            return 'DECLINED'

    @property
    def url(self) -> str:
        return self.data['html_url']

    def add_comment(self, msg: str):
        url = self.data['comments_url']
        return Comment.create(self.client, {'body': msg}, url=url)

    def get_comments(self):
        return Comment.list(self.client, url=self.data['comments_url'])

    @property
    def comments(self):
        return list(self.get_comments())

    @property
    def repo(self):
        return Repository(**self.data['base']['repo'], client=self.client)

    def get_tasks(self):
        raise TaskAPIError("PullRequest.get_tasks", NotImplemented)

    def get_reviews(self):
        repo = self.repo
        self._reviews = list(Review.list(
            self.client,
            # Special header needed to use Reviews API
            headers={
                'Accept': 'application/vnd.github.black-cat-preview+json'
            },
            owner=repo.owner, repo=repo.slug, number=self.id)
        )
        return self._reviews

    def get_participants(self):
        reviews = self._reviews or self.get_reviews()
        return (r.author for r in reviews)

    def get_approvals(self):
        reviews = self._reviews or self.get_reviews()
        return (r.author for r in reviews if r.approved)

    def approve(self):
        rev = Review.create(
            client=self.client,
            data={'body': 'LGTM', 'event': 'APPROVE'},
            headers={
                'Accept': 'application/vnd.github.black-cat-preview+json'
            },
            owner=self.repo.owner, repo=self.repo.slug, number=self.id
        )
        return rev

    def decline(self):
        self.update(client=self.client, owner=self.repo.owner,
                    repo=self.repo.slug, number=self.id,
                    data={'state': 'closed'})


class Comment(GithubObject, base.AbstractComment):
    GET_URL = '/repos/{owner}/{repo}/issues/{number}/comments/{id}'
    LIST_URL = '/repos/{owner}/{repo}/issues/{number}/comments'
    CREATE_URL = LIST_URL

    SCHEMA = schema.Comment
    CREATE_SCHEMA = schema.CreateComment

    def add_task(self, *args):
        raise TaskAPIError("Comment.add_task", NotImplemented)

    @property
    def author(self) -> str:
        return self.data['user']['login']

    @property
    def text(self) -> str:
        return self.data['body']

    @property
    def id(self) -> int:
        return self.data['id']

    def delete(self) -> None:
        self.client.delete(self.data['url'])


class Review(GithubObject):
    LIST_URL = '/repos/{owner}/{repo}/pulls/{number}/reviews'
    CREATE_URL = LIST_URL
    APPROVE_URL = '/repos/{owner}/{repo}/pulls/{number}/reviews/{id}/events'

    SCHEMA = schema.Review
    CREATE_SCHEMA = schema.CreateReview

    @property
    def author(self) -> str:
        return self.data['user']['login']

    @property
    def approved(self) -> str:
        return self.data['state'].lower() == 'approved'


class PullRequestEvent(GithubObject):
    SCHEMA = schema.PullRequestEvent

    @property
    def action(self) -> str:
        return self.data['action']

    @property
    def pull_request(self) -> PullRequest:
        return PullRequest(client=self.client, _validate=False,
                           **self.data['pull_request'])


class IssueCommentEvent(GithubObject):
    SCHEMA = schema.IssueCommentEvent

    @property
    def pull_request(self) -> PullRequest:
        """Get the PullRequest associated with this issue comment event."""
        pr_dict = self.data['issue'].get('pull_request')
        if pr_dict:
            try:
                return PullRequest.get(client=self.client, url=pr_dict['url'])
            except HTTPError:
                LOG.error("No pull request at url %s", pr_dict['url'])
        LOG.debug("Issue #%d is not a pull request",
                  self.data['issue']['number'])


class PullRequestReviewEvent(GithubObject):
    SCHEMA = schema.PullRequestReviewEvent

    @property
    def pull_request(self) -> PullRequest:
        return PullRequest(client=self.client, _validate=False,
                           **self.data['pull_request'])


class StatusEvent(GithubObject):
    SCHEMA = schema.StatusEvent

    @property
    def commit(self) -> str:
        return self.data['sha']

    @property
    def status(self) -> Status:
        return Status(
            client=self.client, state=self.data['state'],
            target_url=self.data.get('target_url'),
            description=self.data.get('description'),
            context=self.data['context']
        )
