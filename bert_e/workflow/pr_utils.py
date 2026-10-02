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
import re

from bert_e import exceptions
from bert_e.git_host.base import AbstractComment, AbstractPullRequest
from bert_e.lib.cli import confirm
from bert_e.lib.template_loader import render

LOG = logging.getLogger(__name__)

STATUS_COMMENT_MARKER = '<!-- bert-e-status -->'
STATUS_PR_RE = re.compile(
    r'^\* #(?P<id>\d+): `(?P<src>[^`]+)` \u2192 `(?P<dst>[^`]+)`',
    re.MULTILINE)


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
        if comment.author != username:
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


def find_status_comment(pull_request: AbstractPullRequest, username):
    """Return the pinned status comment posted by the bot, if any."""
    for comment in pull_request.comments:
        if comment.author == username and \
                comment.text.startswith(STATUS_COMMENT_MARKER):
            return comment
    return None


def _integration_pull_requests(comment, previous_text=None):
    """List the integration pull requests known for a status comment.

    Use those carried by the message when available, otherwise keep the
    ones listed in the previous status comment.
    """
    child_prs = comment.kwargs.get('child_prs')
    if child_prs:
        return [{'id': pr.id, 'dst': pr.dst_branch, 'src': pr.src_branch}
                for pr in child_prs]
    if previous_text:
        return [
            {'id': m.group('id'), 'dst': m.group('dst'),
             'src': m.group('src')}
            for m in STATUS_PR_RE.finditer(previous_text)
        ]
    return []


def update_status_comment(settings, pull_request: AbstractPullRequest,
                          comment: exceptions.TemplateException):
    """Create or update the single comment showing the latest bot state.

    The comment is edited in place so that the current status is always at
    the same (early) position in the pull request conversation, and the
    description of the pull request is left untouched.
    """
    if settings.no_comment or settings.interactive:
        return
    existing = find_status_comment(pull_request, settings.robot)
    prs = _integration_pull_requests(
        comment, existing.text if existing else None)
    text = render('pr_status_comment.md', marker=STATUS_COMMENT_MARKER,
                  state=comment.title, code=comment.code,
                  status=getattr(comment, 'status', None),
                  integration_prs=prs,
                  active_options=comment.kwargs.get('active_options'))
    if existing is None:
        pull_request.add_comment(text)
    elif existing.text.strip() != text.strip():
        existing.update(text)


def notify_user(settings, pull_request: AbstractPullRequest,
                comment: exceptions.TemplateException):
    """Notify user by sending a comment or a build status in a pull request."""
    try:
        # Must happen before the message so that the status comment is never
        # the last bot comment (see dont_repeat_if_in_history).
        try:
            update_status_comment(settings, pull_request, comment)
        except Exception:
            LOG.warning("Could not update the status comment", exc_info=True)
        _send_bot_status(settings, pull_request, comment)
        _send_comment(settings, pull_request, str(comment),
                      comment.dont_repeat_if_in_history)
    except exceptions.CommentAlreadyExists:
        LOG.info("Comment '%s' already posted", comment.__class__.__name__)
