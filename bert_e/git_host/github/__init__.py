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
from collections import defaultdict, namedtuple

from requests import HTTPError
from urllib.parse import quote_plus as quote

from bert_e.exceptions import TaskAPIError
from bert_e.lib.lru_cache import LRUCache
from . import schema
from .. import base, cache, factory

LOG = logging.getLogger(__name__)


class Error(base.Error):
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
            'From': email,
            'Authorization': 'token ' + password
        }

        rlog = logging.getLogger('requests.packages.urllib3.connectionpool')
        rlog.setLevel(logging.CRITICAL)
        self.session = base.BertESession()
        self.session.headers.update(headers)

        self.login = login
        self.password = password
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
        response.raise_for_status()
        return json.loads(response.text)

    def delete(self, url, **kwargs):
        """Perform a DELETE request on the github API.

        Args: same as requests.delete()

        Raises: requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.delete(url, **kwargs)
        response.raise_for_status()

    def put(self, url, **kwargs):
        """Perform a PUT request to the Github API.

        Args: same as requests.put()

        Raises: requests.HTTPError

        """
        url = self._patch_url(url)
        response = self.session.put(url, **kwargs)
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

    def get_user_id(self) -> int:
        return User.get(self).data['id']

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


class Repository(base.AbstractGitHostObject, base.AbstractRepository):
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
        return 'https://{}:{}@github.com/{}/{}.git'.format(
            quote(self.client.login),
            quote(self.client.password),
            self.owner,
            self.slug)

    def get_commit_url(self, revision):
        return 'https://github.com/{}/{}/commit/{}'.format(self.owner,
                                                           self.slug,
                                                           revision)

    def get_commit_status(self, ref):
        try:
            combined = AggregatedStatus.get(self.client,
                                            owner=self.owner,
                                            repo=self.slug, ref=ref)

            actions = AggregatedCheckSuites.get(self.client,
                                                owner=self.owner,
                                                repo=self.slug, ref=ref)
            combined.status[actions.key] = actions

        except HTTPError as err:
            if err.response.status_code == 404:
                return None
            raise

        for key, status in combined.status.items():
            cache.BUILD_STATUS_CACHE[key].set(combined.commit, status)

        return combined

    def get_build_status(self, revision: str, key: str) -> str:
        status = cache.BUILD_STATUS_CACHE[key].get(revision, None)
        if status and status.state == 'SUCCESSFUL':
            return status.state
        try:
            return self.get_commit_status(revision).status.get(key, None).state
        except AttributeError:
            return 'NOTSTARTED'

    def get_build_url(self, revision: str, key: str) -> str:
        # Only look inside the cache. There is no need for an API call for this
        # build's URL.
        status = cache.BUILD_STATUS_CACHE[key].get(revision, None)
        if status:
            return status.url

    def get_build_description(self, revision: str, key: str) -> str:
        status = cache.BUILD_STATUS_CACHE[key].get(revision, None)
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


class AggregatedStatus(base.AbstractGitHostObject):
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


class Status(base.AbstractGitHostObject, base.AbstractBuildStatus):
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
    def url(self) -> str:
        return self.data['target_url']

    @property
    def description(self) -> str:
        return self.data['description']

    @property
    def key(self) -> str:
        return self.data['context']

    def __str__(self) -> str:
        return self.state


class AggregatedCheckRuns(base.AbstractGitHostObject):
    """
    The Endpoint to have access infos about github actions runs
    """
    GET_URL = '/repos/{owner}/{repo}/commits/{ref}/check-runs'
    SCHEMA = schema.AggregateCheckRuns

    @property
    def html_url(self):
        if self.data['total_count']:
            return self.data['check_runs'][0]['html_url']
        return ''


class AggregatedCheckSuites(base.AbstractGitHostObject,
                            base.AbstractBuildStatus):
    """
    The Endpoint to have access infos about github actions suites
    """
    GET_URL = '/repos/{owner}/{repo}/commits/{ref}/check-suites'
    SCHEMA = schema.AggregateCheckSuites

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._check_suites = [elem for elem in self.data['check_suites']]

    @classmethod
    def get(cls, client, url=None, params={}, headers={}, **kwargs):
        res = super(AggregatedCheckSuites, cls)\
            .get(client, url, params, headers, **kwargs)

        html_url = AggregatedCheckRuns\
            .get(client, url, params, headers, **kwargs).html_url
        res.data['html_url'] = html_url
        return res

    @property
    def url(self):
        return self.data['html_url']

    @property
    def state(self):
        queued = any(
            elem['status'] == 'queued' for elem in self._check_suites
        )
        all_complete = all(
            elem['status'] == 'completed' for elem in self._check_suites
        )
        all_success = all(
            elem['conclusion'] == 'success' for elem in self._check_suites
        )
        if self._check_suites.__len__() > 0 and queued:
            return 'NOTSTARTED'
        elif self._check_suites.__len__() > 0 and not all_complete:
            return 'INPROGRESS'
        elif self._check_suites.__len__() > 0 and all_complete and all_success:
            return 'SUCCESSFUL'
        else:
            return 'FAILED'

    @property
    def description(self) -> str:
        return 'github actions CI'

    @property
    def key(self) -> str:
        return 'github_actions'

    @property
    def commit(self):
        if self._check_suites.__len__() > 0:
            return self._check_suites[0]["head_sha"]
        else:
            return None


class PullRequest(base.AbstractGitHostObject, base.AbstractPullRequest):
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
        return self.data['user']['login'].lower()

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
        return (r.author.lower() for r in reviews)

    def get_summarized_reviews(self):
        """
        Github API provides three statuses relevant for gating:
            APPROVED, DISMISSED, CHANGES_REQUESTED.
        Any dismissed review means that either a change_request was dismissed
        (but no approval since) or that the latest approval was dismissed. As
        such, only the last "relevant" review item shall be accounted for each
        reviewer, as any remaining approval from that author (in the API) may
        not be the latest status.
        """
        reviews = self._reviews or self.get_reviews()
        # Filter reviews (remove COMMENTED entries)
        filtered = list(filter(lambda r: not r.commented, reviews))
        # Order the reviews by id (so the order matches the PR's timeline)
        filtered.sort(key=lambda r: r.id)
        # ID-based ordering ensure that we can simply select the last for any
        # author, to get the "current" status.
        summary = {}
        for author in self.get_participants():
            author_reviews = list(
                filter(lambda r: r.author == author, filtered))
            if len(author_reviews):
                summary[author] = author_reviews[-1]

        return summary

    def get_change_requests(self):
        summary = self.get_summarized_reviews()
        return (r.author.lower()
                for r in summary.values() if r.changes_requested)

    def get_approvals(self):
        summary = self.get_summarized_reviews()
        return (r.author.lower() for r in summary.values() if r.approved)

    def comment_review(self):
        rev = Review.create(
            client=self.client,
            data={'body': 'not wanting to block', 'event': 'COMMENT'},
            headers={
                'Accept': 'application/vnd.github.black-cat-preview+json'
            },
            owner=self.repo.owner, repo=self.repo.slug, number=self.id
        )
        return rev

    def request_changes(self):
        rev = Review.create(
            client=self.client,
            data={'body': 'NOPE', 'event': 'REQUEST_CHANGES'},
            headers={
                'Accept': 'application/vnd.github.black-cat-preview+json'
            },
            owner=self.repo.owner, repo=self.repo.slug, number=self.id
        )
        return rev

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

    def dismiss(self, review):
        self.client.put(
            url=Review.DISMISS_URL.format(
                owner=self.repo.owner, repo=self.repo.slug,
                number=self.id, id=review.id),
            headers={
                'Accept': 'application/vnd.github.black-cat-preview+json',
            },
            data=json.dumps({
                "message": "no longer relevant.",
            })
        )


class Comment(base.AbstractGitHostObject, base.AbstractComment):
    GET_URL = '/repos/{owner}/{repo}/issues/{number}/comments/{id}'
    LIST_URL = '/repos/{owner}/{repo}/issues/{number}/comments'
    CREATE_URL = LIST_URL

    SCHEMA = schema.Comment
    CREATE_SCHEMA = schema.CreateComment

    def add_task(self, *args):
        raise TaskAPIError("Comment.add_task", NotImplemented)

    @property
    def author(self) -> str:
        return self.data['user']['login'].lower()

    @property
    def created_on(self):
        # note that Github's field is created_at and not created_on
        return self.data['created_at']

    @property
    def text(self) -> str:
        return self.data['body']

    @property
    def id(self) -> int:
        return self.data['id']

    def delete(self) -> None:
        self.client.delete(self.data['url'])


class Review(base.AbstractGitHostObject):
    LIST_URL = '/repos/{owner}/{repo}/pulls/{number}/reviews'
    CREATE_URL = LIST_URL
    APPROVE_URL = '/repos/{owner}/{repo}/pulls/{number}/reviews/{id}/events'
    DISMISS_URL = \
        '/repos/{owner}/{repo}/pulls/{number}/reviews/{id}/dismissals'

    SCHEMA = schema.Review
    CREATE_SCHEMA = schema.CreateReview

    @property
    def author(self) -> str:
        return self.data['user']['login'].lower()

    @property
    def approved(self) -> str:
        return self.data['state'].lower() == 'approved'

    @property
    def commented(self) -> str:
        return self.data['state'].lower() == 'commented'

    @property
    def changes_requested(self) -> str:
        return self.data['state'].lower() == 'changes_requested'

    @property
    def id(self) -> int:
        return self.data['id']


class PullRequestEvent(base.AbstractGitHostObject):
    SCHEMA = schema.PullRequestEvent

    @property
    def action(self) -> str:
        return self.data['action']

    @property
    def pull_request(self) -> PullRequest:
        return PullRequest(client=self.client, _validate=False,
                           **self.data['pull_request'])


class IssueCommentEvent(base.AbstractGitHostObject):
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


class PullRequestReviewEvent(base.AbstractGitHostObject):
    SCHEMA = schema.PullRequestReviewEvent

    @property
    def pull_request(self) -> PullRequest:
        return PullRequest(client=self.client, _validate=False,
                           **self.data['pull_request'])


class StatusEvent(base.AbstractGitHostObject):
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


class User(base.AbstractGitHostObject):
    SCHEMA = schema.User
    GET_URL = '/user'
