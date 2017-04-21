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

"""Commands and options defined for BertE's implementation of GitWaterFlow.

The module holds the implementation of all commands/options users can send
BertE through comments in the pull requests.

"""

from bert_e.exceptions import (
    CommandNotImplemented, LossyResetWarning, ResetComplete, HelpMessage,
    StatusReport, IncorrectCommandSyntax
)
from bert_e.reactor import Reactor
from .integration import get_integration_branches
from ..git_utils import clone_git_repo, push


@Reactor.option(default=set())
def after_pull_request(job, pr_id=None, **kwargs):
    """Wait for the given pull request id to be merged before continuing with
    the current one.

    """
    if pr_id is None:
        raise IncorrectCommandSyntax(
            robot_username=job.bert_e.client.login,
            active_options=job.active_options)

    try:
        int(pr_id)
    except ValueError:
        return

    job.settings.after_pull_request.add(pr_id)


@Reactor.command('help')
def print_help(job, *args):
    """Print Bert-E's manual in the pull request."""
    raise HelpMessage(
        options=Reactor.get_options(), commands=Reactor.get_commands(),
        active_options=job.active_options
    )


@Reactor.command
def status(job, *args):
    """Print Bert-E's current status in the pull request ```TBA```"""
    raise StatusReport(status={}, active_options=job.active_options)


@Reactor.command("build", "Re-start a fresh build ```TBA```")
@Reactor.command("retry", "Re-start a fresh build ```TBA```")
@Reactor.command("clear",
                 "Remove all comments from Bert-E from the history ```TBA```")
def not_implemented(job):
    raise CommandNotImplemented(active_options=job.active_options)


def _reset(job, force=False):
    """Snippet to reset integration branches; deleting them both locally
    and remotely.
    """
    clone_git_repo(job)
    wbranches = list(get_integration_branches(job))

    if not wbranches:
        raise ResetComplete(couldnt_decline=[],
                            active_options=job.active_options)

    lossy_reset = None
    for branch in wbranches:
        src, dst = branch.src_branch, branch.dst_branch
        feature = set(src.get_commit_diff(dst))

        # wcommits: commits that belong to the integration branches but not
        # the feature or development branches.
        wcommits = set(branch.get_commit_diff(dst)) - feature
        if any(rev.author != job.settings.robot_username for rev in wcommits):
            lossy_reset = LossyResetWarning(active_options=job.active_options)

    if lossy_reset and not force:
        raise lossy_reset

    wprs = job.project_repo.get_pull_requests(
        src_branch=[b.name for b in wbranches]
    )
    for branch in wbranches:
        branch.remove(do_push=False)
    push(job.git.repo, prune=True)

    # decline integration pull requests:
    error_prs = []
    for pr in wprs:
        try:
            pr.decline()
        except Exception:
            error_prs.append(pr)
    raise ResetComplete(couldnt_decline=error_prs,
                        active_options=job.active_options)


@Reactor.command
def force_reset(job, *args):
    """Delete integration branches & pull requests, and restart merge process
    from the beginning.
    """
    _reset(job, force=True)


@Reactor.command
def reset(job, *args):
    """Try to remove integration branches unless there are commits on them
    which do not appear on the source branch.
    """
    _reset(job, force=False)


def setup(defaults={}):
    # Bypasses
    Reactor.add_option(
        "bypass_author_approval",
        "Bypass the pull request author's approval",
        privileged=True,
        default=defaults.get("bypass_author_approval", False))
    Reactor.add_option(
        "bypass_build_status",
        "Bypass the build and test status",
        privileged=True,
        default=defaults.get("bypass_build_status", False))
    Reactor.add_option(
        "bypass_commit_size",
        "Bypass the check on the size of the changeset ```TBA```",
        privileged=True,
        default=defaults.get("bypass_commit_size", False))
    Reactor.add_option(
        "bypass_incompatible_branch",
        "Bypass the check on the source branch prefix",
        privileged=True,
        default=defaults.get("bypass_incompatible_branch", False))
    Reactor.add_option(
        "bypass_jira_check",
        "Bypass the Jira issue check",
        privileged=True,
        default=defaults.get("bypass_jira_check", False))
    Reactor.add_option(
        "bypass_peer_approval",
        "Bypass the pull request peers' approval",
        privileged=True,
        default=defaults.get("bypass_peer_approval", False))
    Reactor.add_option(
        "bypass_tester_approval",
        "Bypass the pull request testers' approval",
        privileged=True,
        default=defaults.get("bypass_tester_approval", False))

    # Other options
    Reactor.add_option(
        "unanimity",
        "Change review acceptance criteria from `one reviewer at least` "
        "to `all reviewers`",
        default=defaults.get("unanimity", False))
    Reactor.add_option(
        "wait",
        "Instruct Bert-E not to run until further notice.",
        default=defaults.get("wait", False))
