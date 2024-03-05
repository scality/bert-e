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

"""This module provides a unified abstract API for Git project hosts.

Typical implementations would be Bitbucket, Github or Gitlab.

"""

import logging
import time

import requests

from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import Iterable
from requests import Session

from bert_e.lib.schema import (load as load_schema,
                               validate as validate_schema,
                               dumps as dump_schema)
from ..exceptions import FlakyGitHost

LOG = logging.getLogger(__name__)


class Error(Exception):
    """Base class for git host api related errors."""


class InvalidOperation(Error):
    """Invalid request made to a githost object."""


class RepositoryExists(Error):
    """The repository we are trying to create already exists."""


class NoSuchRepository(Error):
    """The repository we want to access to or delete does not exist."""


class NoSuchGitHost(Error):
    """The requested git host is not implemented."""


class BertESession(Session):
    """Override the Session class for logging flexibility."""

    git_provider = 'base'  # Overidden when decorating with factory.api_client

    def request(self, method, url, **kwargs):
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                response = super().request(method, url, **kwargs)
                LOG.info("request: {method} {url} {status} {time}".format(
                    method=response.request.method,
                    url=response.request.url,
                    status=response.status_code,
                    time=response.elapsed.microseconds
                ))
            except Exception:
                LOG.error('{method} {url}'.format(method=method, url=url))
                raise

            if response.status_code not in [429, 500, 502]:
                break

            nap = 30 * attempt
            LOG.error('sleeping {nap}s'.format(nap=nap))
            time.sleep(nap)
            if attempt < max_attempts:
                LOG.error('retrying request {method} {url}'.format(
                    method=method, url=url))
            else:
                LOG.error('skipping retry request {method} {url}'.format(
                    method=method, url=url))
        else:
            raise FlakyGitHost(git_host=self.git_provider, active_options=[])

        return response


class AbstractGitHostObject(metaclass=ABCMeta):
    """Abstract githaost defining schema validation"""
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
    def get(cls, client, url=None, params={}, headers={}, **kwargs):
        """Get a Githost object.

        The result is parsed using cls.GET_SCHEMA, of cls.SCHEMA if absent.

        Args:
            - client: the Githost client to use to perform the request.
            - url: a specific url to use for this request. Defaults to GET_URL.
            - params: the parametes of the GET request.
            - **kwargs: the parameters of the URL (name str.format style).

        Returns:
            The result of the query, parsed by the shema.
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
    def list(cls, client, url=None, params={}, headers={}, **kwargs):
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

        Return a Githost object
        """
        if schema_cls is None:
            schema_cls = cls.SCHEMA
        if isinstance(data, requests.Response):
            data.raise_for_status()
            data = data.json()
        return cls(**load_schema(schema_cls, data, **kwargs), _validate=False)

    @classmethod
    def create(cls, client, data, headers={}, url=None, **kwargs):
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
    def update(cls, client, data, headers={}, url=None, **kwargs):
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
    def delete(cls, client, **kwargs):
        """Delete an object."""
        if cls.DELETE_URL is None:
            raise InvalidOperation(
                'DELETE is not supported on {} objects.'.format(cls.__name__))
        client.delete(cls.DELETE_URL.format(**kwargs))


class AbstractBuildStatus(metaclass=ABCMeta):
    """Abstract class defining a build status interface."""
    @property
    @abstractmethod
    def state(self) -> str:
        """The build status itself.

        Possible values:
            - INPROGRESS
            - NOTSTARTED
            - SUCCESSFUL
            - FAILED
        """

    @property
    @abstractmethod
    def url(self) -> str:
        """The build status url."""

    @property
    @abstractmethod
    def description(self) -> str:
        """The build status description."""

    @property
    @abstractmethod
    def key(self) -> str:
        """The build status key."""


class AbstractTask(metaclass=ABCMeta):
    """Abstract class defining a task's interface."""
    # Empty, but used as a return value below


class AbstractComment(metaclass=ABCMeta):
    """Abstract class defining the interface of a pull requests's comment."""
    @abstractmethod
    def add_task(self, msg: str) -> AbstractTask:
        """Attach a new task attached to this comment.

        Args:
            - msg: the message of the task to attach.

        Returns: the newly created task.

        """

    @abstractmethod
    def delete(self) -> None:
        """Delete the comment."""

    @property
    @abstractmethod
    def author(self) -> str:
        """The comment author's username (login)."""

    @property
    @abstractmethod
    def created_on(self) -> datetime:
        """The creation date of the comment"""

    @property
    @abstractmethod
    def text(self) -> str:
        """The comment's contents as raw plaintext."""

    @property
    @abstractmethod
    def id(self) -> int:
        """The comment's ID"""


class AbstractPullRequest(metaclass=ABCMeta):
    @abstractmethod
    def add_comment(self, msg: str) -> AbstractComment:
        """Add a new comment to the Pull Request.

        Args:
            - msg: the raw plaintext of the comment.

        Returns: the newly created Comment object.

        """

    @abstractmethod
    def get_comments(self) -> Iterable[AbstractComment]:
        """Get this pull request's comments.

        Returns: an iterable over the Comment objects.

        """

    @abstractmethod
    def get_change_requests(self) -> Iterable[str]:
        """Get the usernames of participants who requested changes on
        this pull request."""

    @abstractmethod
    def get_approvals(self) -> Iterable[str]:
        """Get the usernames of participants who approved this pull request."""

    @abstractmethod
    def get_participants(self) -> Iterable[str]:
        """Get the usernames of the participants to this pull request."""

    @abstractmethod
    def get_tasks(self) -> Iterable[AbstractTask]:
        """Get this pull request's tasks.

        Returns: an iterable over the Task objects.

        """

    @abstractmethod
    def comment_review(self):
        """Request changes on this pull request."""

    @abstractmethod
    def request_changes(self):
        """Request changes on this pull request."""

    @abstractmethod
    def approve(self):
        """Approve this pull request."""

    @abstractmethod
    def decline(self):
        """Decline this pull request."""

    @abstractmethod
    def set_bot_status(self, status: str | None, title: str,
                       summary: str) -> None:
        """Set a status check reporting its advancement regarding Bert-E's checks

        Args:
            - status: the status of the check.
            - title: the title of the check.
            - summary: the summary of the check.
        """

    @property
    @abstractmethod
    def id(self) -> str:
        """The pull request's unique ID."""

    @property
    @abstractmethod
    def title(self) -> str:
        """The pull request's title."""

    @property
    @abstractmethod
    def author(self) -> str:
        """The username of the pull request's author."""

    @property
    @abstractmethod
    def author_display_name(self) -> str:
        """The display name of the pull request's author."""

    @property
    @abstractmethod
    def description(self) -> str:
        """The description of the Pull Request."""

    @property
    @abstractmethod
    def src_branch(self) -> str:
        """The name of the pull request's source branch."""

    @property
    @abstractmethod
    def src_commit(self) -> str:
        """The sha1 hash corresponding to the pull request's source commit."""

    @src_commit.setter
    @abstractmethod
    def src_commit(self, sha1):
        pass

    @property
    @abstractmethod
    def dst_branch(self) -> str:
        """The name of the pull request's destination branch."""

    @property
    @abstractmethod
    def status(self) -> str:
        """The current status of the pull request.

        Possible values:
            - 'OPEN'
            - 'MERGED'
            - 'DECLINED'

        """

    @property
    @abstractmethod
    def comments(self) -> Iterable[AbstractComment]:
        """Cached list of comments of the pull request."""


class AbstractRepository(metaclass=ABCMeta):
    @abstractmethod
    def get_build_status(self, revision: str, key: str) -> str:
        """Get the build status associated to a commit.

        Args:
            - revision: commit sha1 or branch name
            - key: build key (e.g. "pre-merge")

        Returns:
            - SUCCESSFUL
            - INPROGRESS
            - NOTSTARTED
            - STOPPED
            - FAILED

        """

    @abstractmethod
    def get_commit_url(self, revision: str) -> str:
        """Get the commit url associated to a commit.

        Args:
            - revision: commit sha1 or branch name

        Returns: url to the commit of `revision` or `None`
        """

    @abstractmethod
    def get_build_url(self, revision: str, key: str) -> str:
        """Get the build url associated to a commit.

        Args:
            - revision: commit sha1 or branch name
            - key: build key (e.g. "pre-merge")

        Returns: url to the build of `revision` or `None`
        """

    @abstractmethod
    def set_build_status(self, revision: str, key: str, state: str, **kwargs
                         ) -> None:
        """Associate a build status to a commit.

        Args:
            - revision: commit sha1 or branch name
            - key: build key (e.g. "pre-merge")
            - state: status (see get_build_status() return value)
            - **kwargs: implementation specific arguments

        """

    @abstractmethod
    def get_pull_requests(self, author=None, src_branch=None, status='OPEN'
                          ) -> Iterable[AbstractPullRequest]:
        """Get pull requests from this repository.

        Args:
            - author (str): optional filter on PR author username.
            - src_branch (str or List[str]): optional filter on PR source
                                             branch name.
            - status (str): filter on the pull requests status. Defaults to
                            'OPEN'.
        """

    @abstractmethod
    def get_pull_request(self, pull_request_id: int) -> AbstractPullRequest:
        """Get a specific pull request on this repository.

        Args:
            - pr_id: id of the pull request to get.
        """

    def create_pull_request(self, title: str, src_branch: str, dst_branch: str,
                            description: str, **kwargs) -> AbstractPullRequest:
        """Create a new pull request

        Args:
            - title: title of the new pull request
            - src_branch: name of the source branch
            - dst_branch: name of the destination branch
            - **kwargs: implementation dependent optional arguments

        Returns: the newly created pull request
        """

    @property
    @abstractmethod
    def git_url(self) -> str:
        """This repository's git clone url."""

    @property
    @abstractmethod
    def owner(self) -> str:
        """Owner of the repository."""

    @property
    @abstractmethod
    def slug(self) -> str:
        """Repository name or slug."""


class AbstractClient(metaclass=ABCMeta):

    @abstractmethod
    def get_repository(self, slug: str, owner=None) -> AbstractRepository:
        """Get the associated repository for the client.

        Raises: NoSuchRepository if the repository does not exist.

        Returns: the corresponding AbstractRepository object.

        """

    @abstractmethod
    def create_repository(self, slug: str, owner=None, **kwargs
                          ) -> AbstractRepository:
        """Create a new repository.

        Raises: RepositoryExists if the repository already exists.

        Returns: the corresponding AbstractRepository object.

        """

    @abstractmethod
    def delete_repository(self, slug: str, owner=None) -> None:
        """Delete a repository.

        Raises: NoSuchRepository if the repository does not exist.

        """
