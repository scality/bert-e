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

"""Commands and options defined for BertE's implementation of GitWaterFlow.

The module holds the implementation of all commands/options users can send
BertE through comments in the pull requests.

"""
import logging

from bert_e.exceptions import (
    CommandNotImplemented, LossyResetWarning, ResetComplete, HelpMessage,
    StatusReport, IncorrectCommandSyntax
)
from bert_e.reactor import Reactor
from .integration import get_integration_branches
from ..git_utils import clone_git_repo, push

LOG = logging.getLogger(__name__)


class _StatusItem:
    """A single row in the pull request status report."""

    def __init__(self, display_name, passed, details=None):
        self.display_name = display_name
        setattr(self, 'pass', passed)
        self.details = details or []


def _check_approvals_status(job):
    """Return a _StatusItem reflecting the current approval state."""
    from .utils import (bypass_peer_approval, bypass_leader_approval,
                        bypass_author_approval)

    required_peer = job.settings.required_peer_approvals
    required_leader = job.settings.required_leader_approvals
    robot = job.settings.robot

    peer_count = required_peer if bypass_peer_approval(job) else 0
    leader_count = required_leader if bypass_leader_approval(job) else 0
    author_ok = (not job.settings.need_author_approval or
                 bypass_author_approval(job) or
                 job.settings.approve)

    if (author_ok and
            peer_count >= required_peer and
            leader_count >= required_leader and
            not job.settings.unanimity):
        return _StatusItem('Approvals', True)

    participants = set(job.pull_request.get_participants()) - {robot}
    approvals = set(job.pull_request.get_approvals())
    if job.settings.approve:
        approvals.add(job.pull_request.author)

    leaders = set(job.settings.project_leaders)
    author_ok = author_ok or job.pull_request.author in approvals
    leader_count += len(approvals & leaders)
    if (job.pull_request.author in leaders and
            job.pull_request.author not in approvals):
        leader_count += 1

    peer_count += len(approvals - {job.pull_request.author})
    change_requests = set(job.pull_request.get_change_requests())
    unanimity = job.settings.unanimity
    is_unanimous = (approvals - {robot}) == participants

    details = []
    if not author_ok:
        details.append("author approval required")
    missing_leaders = required_leader - leader_count
    if missing_leaders > 0:
        unapproved = sorted(str(u) for u in leaders - approvals)
        details.append(
            "{} leader approval(s) missing{}".format(
                missing_leaders,
                " (from: {})".format(', '.join(unapproved)) if unapproved
                else ""
            )
        )
    missing_peers = required_peer - peer_count
    if missing_peers > 0:
        details.append("{} peer approval(s) missing".format(missing_peers))
    if unanimity and not is_unanimous:
        details.append("unanimity required but not reached")
    if change_requests:
        details.append(
            "changes requested by: {}".format(
                ', '.join(sorted(change_requests)))
        )

    return _StatusItem('Approvals', not details, details=details)


def _check_builds_status(job):
    """Return a _StatusItem for integration branch build status, or None if
    no integration branches exist or no build key is configured.
    """
    key = job.settings.build_key
    if not key:
        return None

    from .utils import bypass_build_status
    wbranches = list(get_integration_branches(job))
    if not wbranches:
        return None

    if bypass_build_status(job):
        return _StatusItem('Integration builds', True, ['bypassed'])

    ordered = {
        'SUCCESSFUL': 0, 'INPROGRESS': 1,
        'NOTSTARTED': 2, 'STOPPED': 3, 'FAILED': 4,
    }
    worst_rank = 0
    worst_branch = None
    worst_state = 'SUCCESSFUL'
    for branch in wbranches:
        state = job.project_repo.get_build_status(
            branch.get_latest_commit(), key)
        rank = ordered.get(state, 5)
        if rank > worst_rank:
            worst_rank = rank
            worst_branch = branch
            worst_state = state

    if worst_state == 'SUCCESSFUL':
        return _StatusItem('Integration builds', True)
    return _StatusItem(
        'Integration builds', False,
        details=["{}: {}".format(worst_branch.name, worst_state)]
    )


def _check_fix_versions_status(job):
    """Return a _StatusItem for Jira fix-version correctness, or None if
    Jira is not configured or version checks are disabled.
    """
    from .utils import bypass_jira_check
    from bert_e import exceptions as exns

    if bypass_jira_check(job):
        return _StatusItem('Fix versions', True, ['bypassed'])

    if not all([job.settings.jira_keys,
                job.settings.jira_email,
                job.settings.jira_account_url]):
        return None

    if job.settings.disable_version_checks:
        return None

    from jira.exceptions import JIRAError
    import requests.exceptions as requests_exc
    from .jira import check_issue_reference, get_jira_issue, check_fix_versions
    try:
        has_ref = check_issue_reference(job)
    except exns.MissingJiraId:
        return _StatusItem('Fix versions', False,
                           details=['missing Jira issue id in branch name'])

    if not has_ref:
        return None

    try:
        issue = get_jira_issue(job)
        check_fix_versions(job, issue)
        return _StatusItem('Fix versions', True)
    except exns.IncorrectFixVersion as exc:
        details = [
            "expected: {}".format(
                ', '.join(exc.kwargs.get('expect_versions', []))),
            "found: {}".format(
                ', '.join(exc.kwargs.get('issue_versions', []))),
        ]
        return _StatusItem('Fix versions', False, details=details)
    except exns.JiraIssueNotFound:
        return _StatusItem('Fix versions', False,
                           details=['Jira issue not found'])
    except (JIRAError, requests_exc.RequestException):
        LOG.warning("Fix-version status check failed: Jira unreachable",
                    exc_info=True)
        return None


def _has_foreign_commit(branch, robot):
    """Return True if the integration branch contains a commit that is not
    from the feature branch or the robot — i.e. one that would be lost on
    a reset.
    """
    src, dst = branch.src_branch, branch.dst_branch
    feature = set(src.get_commit_diff(dst))
    for rev in reversed(list(branch.get_commit_diff(dst))):
        if rev in feature:
            continue
        if rev.author == robot:
            continue
        if len(rev.parents) == 1:
            parent = rev.parents[0]
            if parent in feature or dst.includes_commit(parent):
                feature.add(rev)
                continue
        return True
    return False


def _check_history_status(job):
    """Return a _StatusItem indicating whether a reset may be needed, or
    None if no integration branches exist yet.
    """
    wbranches = list(get_integration_branches(job))
    if not wbranches:
        return None

    for branch in wbranches:
        if _has_foreign_commit(branch, job.settings.robot):
            return _StatusItem('History', False, ['reset may be needed'])

    return _StatusItem('History', True)


def _build_status_report(job):
    """Collect all available status checks for the pull request."""
    from .branches import build_branch_cascade

    report = {}
    report['approvals'] = _check_approvals_status(job)

    try:
        clone_git_repo(job)
        build_branch_cascade(job)
    except Exception:
        LOG.warning("Status report: git clone/cascade failed, "
                    "returning partial report", exc_info=True)
        return report

    builds = _check_builds_status(job)
    if builds is not None:
        report['builds'] = builds

    fix_versions = _check_fix_versions_status(job)
    if fix_versions is not None:
        report['fix_versions'] = fix_versions

    history = _check_history_status(job)
    if history is not None:
        report['history'] = history

    return report


@Reactor.option(default=set())
def after_pull_request(job, pr_id=None, **kwargs):
    """Wait for the given pull request id to be merged before continuing with
    the current one.

    """
    if pr_id is None:
        raise IncorrectCommandSyntax(
            robot=job.bert_e.client.login,
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
    """Print Bert-E's current status in the pull request."""
    report = _build_status_report(job)
    raise StatusReport(status=report, active_options=job.active_options)


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
        if _has_foreign_commit(branch, job.settings.robot):
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
        "bypass_leader_approval",
        "Bypass the pull request leaders' approval",
        privileged=True,
        default=defaults.get("bypass_leader_approval", False))

    # Other options
    Reactor.add_option(
        "approve",
        "Instruct Bert-E that the author has approved the pull request.",
        authored=True,
        default=defaults.get("approve", False)
    )
    Reactor.add_option(
        "create_pull_requests",
        "Allow the creation of integration pull requests.",
        privileged=False,
        default=defaults.get("create_pull_requests", False))
    Reactor.add_option(
        "create_integration_branches",
        "Allow the creation of integration branches.",
        privileged=False,
        default=defaults.get("create_integration_branches", False))
    Reactor.add_option(
        "no_octopus",
        "Prevent Wall-E from doing any octopus merge and use multiple "
        "consecutive merge instead",
        default=defaults.get("no_octopus", False))
    Reactor.add_option(
        "unanimity",
        "Change review acceptance criteria from `one reviewer at least` "
        "to `all reviewers`",
        default=defaults.get("unanimity", False))
    Reactor.add_option(
        "wait",
        "Instruct Bert-E not to run until further notice.",
        default=defaults.get("wait", False))
