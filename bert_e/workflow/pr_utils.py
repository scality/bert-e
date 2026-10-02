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

# Every status comment starts with this line: this is how we recognize it.
STATUS_COMMENT_HEADER = '# Bert-E status'


def is_status_comment(comment: AbstractComment, username=None) -> bool:
    """Tell whether the comment is the bot's pull request status comment.

    Args:
        username: if given, the comment must also be authored by this user.

    """
    if username is not None and comment.author != username:
        return False
    return comment.text.startswith(STATUS_COMMENT_HEADER)


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
    # The status comment is edited in place and is not part of the
    # conversation: it must neither count as a message nor hide one.
    comments = (c for c in reversed(pull_request.comments)
                if not is_status_comment(c, username))
    if max_history not in (None, -1):
        comments = itertools.islice(comments, 0, max_history)
    for comment in comments:
        if comment.author != username:
            continue
        if startswith and not comment.text.startswith(startswith):
            if max_history == -1:
                return
            continue
        return comment


def find_status_comment(pull_request: AbstractPullRequest, username
                        ) -> AbstractComment:
    """Return the status comment of the pull request, if any."""
    for comment in pull_request.comments:
        if is_status_comment(comment, username):
            return comment


def upsert_status_comment(settings, pull_request: AbstractPullRequest,
                          msg: str, comment=None) -> None:
    """Create the status comment, or edit it if its contents changed.

    `comment` is the already known status comment, if any, which saves
    listing the pull request comments again.
    """
    if settings.no_comment or settings.interactive:
        LOG.debug('Not sending the status comment.')
        return
    if comment is None:
        comment = find_status_comment(pull_request, settings.robot)
    if comment is None:
        LOG.debug('CREATING STATUS COMMENT %s', msg)
        pull_request.add_comment(msg)
    elif comment.text != msg:
        LOG.debug('UPDATING STATUS COMMENT %s', msg)
        comment.edit(msg)


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

    if dont_repeat_if_in_history != 0:
        if find_comment(pull_request, settings.robot, msg,
                        dont_repeat_if_in_history):
            raise exceptions.CommentAlreadyExists(
                "The same comment has already been posted in the history."
            )

    if settings.interactive:
        print(msg, '\n')
        if not confirm('Do you want to send this comment?'):
            return

    LOG.debug('SENDING MESSAGE %s', msg)
    pull_request.add_comment(msg)


def _send_bot_status(settings, pull_request: AbstractPullRequest,
                     comment: exceptions.TemplateException):
    """Post the bot status in a pull request."""
    if settings.send_bot_status is False or comment.status is None:
        LOG.debug("No need to send bot status")
        return
    LOG.info(f"Setting bot status to {comment.status} as {comment.title}")
    pull_request.set_bot_status(
        comment.status,
        title=comment.title,
        summary=str(comment),
    )


def notify_user(settings, pull_request: AbstractPullRequest,
                comment: exceptions.TemplateException):
    """Notify user by sending a comment or a build status in a pull request."""
    try:
        _send_bot_status(settings, pull_request, comment)
        _send_comment(settings, pull_request, str(comment),
                      comment.dont_repeat_if_in_history)
    except exceptions.CommentAlreadyExists:
        LOG.info("Comment '%s' already posted", comment.__class__.__name__)
