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

"""This module provides a unified abstract API for Git project hosts.

Typical implementations would be Bitbucket, Github or Gitlab.

"""

from abc import ABCMeta, abstractmethod
from typing import Iterable


class Error(Exception):
    """Base class for git host api related errors."""


class RepositoryExists(Error):
    """The repository we are trying to create already exists."""


class NoSuchRepository(Error):
    """The repository we want to access to or delete does not exist."""


class NoSuchGitHost(Error):
    """The requested git host is not implemented."""


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

    @property
    @abstractmethod
    def author(self) -> str:
        """The comment author's username (login)."""

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
    def merge(self):
        """Merge this pull request."""

    @abstractmethod
    def approve(self):
        """Approve this pull request."""

    @abstractmethod
    def decline(self):
        """Decline this pull request."""

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
            - FAILED

        """

    def get_build_url(self, revision: str, key: str) -> str:
        """Get the build url associated to a commit.

        Args:
            - revision: commit sha1 or branch name
            - key: build key (e.g. "pre-merge")

        Returns: url to the build of `revision` or `None`
        """

    def set_build_status(self, revision: str, key: str, state: str, **kwargs):
        """Associate a build status to a commit.

        Args:
            - revision: commit sha1 or branch name
            - key: build key (e.g. "pre-merge")
            - state: status (see get_build_status() return value)
            - **kwargs: implementation specific arguments

        """

    @abstractmethod
    def get_pull_requests(self, author=None, src_branch=None
                          ) -> Iterable[AbstractPullRequest]:
        """Get pull requests from this repository.

            * author (str): optional filter on PR author username.
            * src_branch (str or List[str]): optional filter on PR source
                branch name.
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
        return self.get_git_url()


class AbstractClient(metaclass=ABCMeta):

    @abstractmethod
    def get_repository(self, slug, owner=None) -> AbstractRepository:
        """Get the associated repository for the client.

        Raises: NoSuchRepository if the repository does not exist.

        Returns: the corresponding AbstractRepository object.

        """

    @abstractmethod
    def create_repository(self, slug, owner=None,
                          **kwargs) -> AbstractRepository:
        """Create a new repository.

        Raises: RepositoryExists if the repository already exists.

        Returns: the corresponding AbstractRepository object.

        """

    @abstractmethod
    def delete_repository(self, slug, owner=None) -> None:
        """Delete a repository.

        Raises: NoSuchRepository if the repository does not exist.

        """
