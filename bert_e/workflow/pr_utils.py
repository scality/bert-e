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
                 startswith=None, max_history=None,
                 include_status=False) -> AbstractComment:
    """Look for the most recent pull request comment satisfying given
    criteria.

    Args:
        username: comment's author.
        starswith: preamble of the comment.
        max_history: limit of the comment history to look backwards.
        include_status: also consider the always up-to-date status comment.

    Returns:
        The latest comment if it was found. None otherwise.

    """
    # check last commits
    comments = reversed(pull_request.comments)
    if max_history not in (None, -1):
        comments = itertools.islice(comments, 0, max_history)
    for comment in comments:
        if comment.author != username:
            continue
        if not include_status and \
                comment.text.startswith(STATUS_COMMENT_MARKER) and \
                not (startswith or '').startswith(STATUS_COMMENT_MARKER):
            # the status comment is not part of the regular history
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


STATUS_COMMENT_MARKER = '<!-- bert-e-status -->'


# Replies to user commands and purely informational messages: they do not
# describe the state of the pull request and must not replace the status.
STATUS_COMMENT_EXCLUDED = (
    exceptions.InformationException,
    exceptions.HelpMessage,
    exceptions.StatusReport,
    exceptions.UnknownCommand,
    exceptions.CommandNotImplemented,
    exceptions.ResetComplete,
    exceptions.LossyResetWarning,
    exceptions.IncorrectCommandSyntax,
    exceptions.NotEnoughCredentials,
    exceptions.NotAuthor,
)


def render_status_comment(comment: exceptions.TemplateException) -> str:
    """Render the content of the always up-to-date status comment."""
    return (f"{STATUS_COMMENT_MARKER}\n"
            f"## Bert-E status: {comment.title}\n\n"
            f"{comment}")


def _update_status_comment(settings, pull_request: AbstractPullRequest,
                           comment: exceptions.TemplateException):
    """Create or update the single status comment of the pull request.

    The pull request description is left untouched: the status lives in a
    dedicated comment, edited in place whenever the state changes.
    """
    if not getattr(settings, 'status_comment', False) or \
            settings.no_comment or settings.interactive or isinstance(
                comment, STATUS_COMMENT_EXCLUDED):
        return
    text = render_status_comment(comment)
    existing = next(
        (c for c in pull_request.comments
         if c.author == settings.robot and
         c.text.startswith(STATUS_COMMENT_MARKER)), None)
    if existing is None:
        pull_request.add_comment(text)
    elif existing.text != text:
        try:
            existing.update(text)
        except NotImplementedError:
            # no in-place edit on this host: replace the stale comment
            try:
                existing.delete()
            except Exception:
                # keep the stale comment rather than posting a duplicate
                LOG.warning("Could not delete stale status comment; "
                            "skipping status update", exc_info=True)
                return
            pull_request.add_comment(text)


def notify_user(settings, pull_request: AbstractPullRequest,
                comment: exceptions.TemplateException):
    """Notify user by sending a comment or a build status in a pull request."""
    try:
        _update_status_comment(settings, pull_request, comment)
    except NotImplementedError:
        LOG.warning("Status comment is not supported by this git host")
    try:
        _send_bot_status(settings, pull_request, comment)
        _send_comment(settings, pull_request, str(comment),
                      comment.dont_repeat_if_in_history)
    except exceptions.CommentAlreadyExists:
        LOG.info("Comment '%s' already posted", comment.__class__.__name__)
