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
"""Pull Requests messaging utility functions."""
import itertools
import logging

from bert_e import exceptions
from bert_e.git_host.base import AbstractComment, AbstractPullRequest
from bert_e.lib.cli import confirm

LOG = logging.getLogger(__name__)


def find_comment(pull_request: AbstractPullRequest, username=None,
                 startswith=None, max_history=None) -> AbstractComment:
    """Look for the most recent pull request comment satisfying given
    criteria.

    Args:
        username: comment's author.
        starswith: preamble of the comment.
        max_history: limit of the comment history to look backwards.

    Returns:
        The latest comment if it was found. None otherwise.

    """
    # check last commits
    comments = reversed(pull_request.comments)
    if max_history not in (None, -1):
        comments = itertools.islice(comments, 0, max_history)
    for comment in comments:
        if isinstance(username, str) and comment.author != username:
            continue
        if startswith and not comment.text.startswith(startswith):
            if max_history == -1:
                return
            continue
        return comment


def _send_comment(settings, pull_request: AbstractPullRequest, msg: str,
                  dont_repeat_if_in_history=10) -> None:
    """Comment a pull request.

    Before posting:
        Check that the same comment was not already posted in the recent pull
        request comments history.
        Optionally (if settings.interactive is set) ask confirmation to the
        user.

    Raises:
        CommentAlreadyExists: if the comment was already posted.

    """
    if settings.no_comment:
        LOG.debug('Not sending message (no_comment==True).')
        return

    if dont_repeat_if_in_history:
        if find_comment(pull_request, settings.robot_username, msg,
                        dont_repeat_if_in_history):
            raise exceptions.CommentAlreadyExists(
                "The same comment has already been posted in the history."
            )

    if settings.interactive:
        print(msg, '\n')
        if not confirm('Do you want to send this comment?'):
            return

    LOG.debug('SENDING MESSAGE %s', msg)
    return pull_request.add_comment(msg)


def send_comment(settings, pull_request: AbstractPullRequest,
                 comment: exceptions.TemplateException):
    """Post a comment in a pull request."""
    try:
        return _send_comment(settings, pull_request, str(comment),
                             comment.dont_repeat_if_in_history)
    except exceptions.CommentAlreadyExists:
        LOG.info("Comment '%s' already posted", comment.__class__.__name__)


def create_task(settings, task: str, comment: AbstractComment):
    """Add a task to a comment."""
    if settings.no_comment:
        LOG.debug("Not setting task (no_comment==True)")
        return

    if settings.interactive:
        print(task, '\n')
        if not confirm('Do you want to create this task?'):
            return

    LOG.debug('CREATING TASK %s', task)

    try:
        comment.add_task(task)
    except exceptions.TaskAPIError as err:
        LOG.error('Could not create task %s (%s)', task, err)
