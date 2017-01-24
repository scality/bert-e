#!/usr/bin/env python3
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

import argparse
import itertools
import logging
import re
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime
from functools import total_ordering
from os.path import exists

import yaml
from jira.exceptions import JIRAError

from .api import bitbucket as bitbucket_api
from .api import jira as jira_api
from .api.git import Repository as GitRepository
from .api.git import (Branch, CheckoutFailedException, MergeFailedException,
                      PushFailedException, RemoveFailedException)
from .exceptions import *
from .template_loader import render
from .utils import RetryHandler

SHA1_LENGHT = [12, 40]

DEFAULT_OPTIONAL_SETTINGS = {
    'build_key': 'pre-merge',
    'required_peer_approvals': 2,
    'jira_account_url': '',
    'jira_username': '',
    'jira_keys': [],
    'prefixes': {},
    'testers': [],
    'admins': [],
    'tasks': [],
}

# This variable is used to get an introspectable status that the server can
# display.
STATUS = {}


class Option(object):
    """Options implementation.

    Bert-E uses options to activate additional functionality
    or alter the behaviour of existing functionality.

    An option is always set to False by default.

    It is activated either on the command line of bert_e.py,
    or by the users of a pull-request, by adding a special
    comment in the pull-request. The options then remain
    active until this comment is deleted.

    An option may require privileges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, privileged, help, value=False):
        self.value = value
        self.help = help
        self.privileged = privileged

    def set(self, value):
        self.value = value

    def is_set(self):
        return self.value


class Command(object):
    """Commands implementation.

    Bert-E uses commands to operate one-time actions.

    Commands are triggered by adding a comment in the
    pull-request.

    A command may require privileges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, privileged, help, handler):
        self.handler = handler
        self.help = help
        self.privileged = privileged


def confirm(question):
    input_ = input(question + " Enter (y)es or (n)o: ")
    return input_ == "yes" or input_ == "y"


class BertEPullRequest():
    def __init__(self, bbrepo, robot_username, pr_id):
        pull_request_id = int(pr_id)

        self.bbrepo = bbrepo
        self.bb_pr = self.bbrepo.get_pull_request(pull_request_id)
        self.author = self.bb_pr.author
        self.author_display_name = self.bb_pr.author_display_name
        if robot_username == self.author:
            res = re.search('(?P<pr_id>\d+)', self.bb_pr.description)
            if not res:
                raise ParentPullRequestNotFound(self.bb_pr.id)
            pull_request_id = int(res.group('pr_id'))
            self.bb_pr = self.bbrepo.get_pull_request(pull_request_id)
            self.author = self.bb_pr.author
            self.author_display_name = self.bb_pr.author_display_name

        # first posted comments first in the list
        self.comments = []
        self.after_prs = []
        self.source_branch = None
        self.destination_branch = None


class BertEBranch(Branch):
    pattern = '(?P<prefix>[a-z]+)/(?P<label>.+)'
    major = 0
    minor = 0
    micro = -1  # is incremented always, first version is 0
    cascade_producer = False
    cascade_consumer = False
    can_be_destination = False
    allow_ticketless_pr = False

    def __init__(self, repo, name):
        super(BertEBranch, self).__init__(repo, name)
        match = re.match(self.pattern, name)
        if not match:
            raise BranchNameInvalid(name)
        for key, value in match.groupdict().items():
            if (key in ('major', 'minor', 'micro', 'pr_id') and
                    value is not None):
                value = int(value)
            self.__setattr__(key, value)

    def __str__(self):
        return self.name


class HotfixBranch(BertEBranch):
    pattern = '^hotfix/(?P<label>.+)$'


class UserBranch(BertEBranch):
    pattern = '^user/(?P<label>.+)$'


class ReleaseBranch(BertEBranch):
    pattern = '^release/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'


class FeatureBranch(BertEBranch):
    all_prefixes = ('improvement', 'bugfix', 'feature', 'project')
    jira_issue_pattern = '(?P<jira_project>[A-Z0-9_]+)-[0-9]+'
    prefixes = '(?P<prefix>(%s))' % '|'.join(all_prefixes)
    pattern = "^%s/(?P<label>(?P<jira_issue_key>%s)?" \
              "(?(jira_issue_key).*|.+))$" % (prefixes, jira_issue_pattern)
    cascade_producer = True


class DevelopmentBranch(BertEBranch):
    pattern = '^development/(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'
    cascade_producer = True
    cascade_consumer = True
    can_be_destination = True
    allow_prefixes = FeatureBranch.all_prefixes

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.major == other.major and \
            self.minor == other.minor


class StabilizationBranch(DevelopmentBranch):
    pattern = '^stabilization/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+))$'
    allow_prefixes = FeatureBranch.all_prefixes

    def __eq__(self, other):
        return DevelopmentBranch.__eq__(self, other) and \
            self.micro == other.micro


class IntegrationBranch(BertEBranch):
    pattern = '^w/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              '(\.(?P<micro>\d+))?)/' + FeatureBranch.pattern[1:]
    destination_branch = ''
    source_branch = ''

    def merge_from_branch(self, source_branch):
        self.merge(source_branch)

    def update_to_development_branch(self):
        self.destination_branch.merge(self, force_commit=False)

    def get_pull_request_from_list(self, open_prs):
        for pr in open_prs:
            if pr.src_branch != self.name:
                continue
            if self.destination_branch and \
                    pr.dst_branch != \
                    self.destination_branch.name:
                continue
            return pr

    def get_or_create_pull_request(self, parent_pr, open_prs, bitbucket_repo,
                                   first=False):
        title = 'INTEGRATION [PR#%s > %s] %s' % (
            parent_pr.id, self.destination_branch.name, parent_pr.title
        )

        # WARNING potential infinite loop:
        # creating a child pr will trigger a 'pr update' webhook
        # Bert-E will analyse it, retrieve the main pr, then
        # re-enter here and recreate the children pr.
        # solution: do not create the pr if it already exists
        pr = self.get_pull_request_from_list(open_prs)
        # need a boolean to know if the PR is created or no
        created = False
        if not pr:
            description = render('pull_request_description.md',
                                 pr=parent_pr,
                                 branch=self.name,
                                 first=first)
            pr = bitbucket_repo.create_pull_request(
                title=title,
                name='name',
                src_branch=self.name,
                dst_branch=self.destination_branch.name,
                close_source_branch=True,
                description=description)
            created = True
        return pr, created

    def remove(self, do_push=False):
        # make sure we are not on the branch to remove
        self.destination_branch.checkout()
        super(IntegrationBranch, self).remove(do_push)


class QueueBranch(BertEBranch):
    pattern = '^q/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              '(\.(?P<micro>\d+))?)$'
    destination_branch = ''

    def __init__(self, repo, name):
        super(QueueBranch, self).__init__(repo, name)
        if self.micro is not None:
            dest = branch_factory(repo, 'stabilization/%s' % self.version)
        else:
            dest = branch_factory(repo, 'development/%s' % self.version)
        self.destination_branch = dest

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.name == other.name


@total_ordering
class QueueIntegrationBranch(BertEBranch):
    pattern = '^q/(?P<pr_id>\d+)/' + IntegrationBranch.pattern[3:]

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.name == other.name

    def __lt__(self, other):
        return self.__class__ == other.__class__ and \
            other.includes_commit(self)


def branch_factory(repo, branch_name):
    for cls in [StabilizationBranch, DevelopmentBranch, ReleaseBranch,
                QueueBranch, QueueIntegrationBranch,
                FeatureBranch, HotfixBranch, IntegrationBranch, UserBranch]:
        try:
            branch = cls(repo, branch_name)
            return branch
        except BranchNameInvalid:
            pass

    raise UnrecognizedBranchPattern(branch_name)


class QueueCollection(object):
    """Manipulate and analyse all active queues in the repository."""

    def __init__(self, bbrepo, build_key, merge_paths):
        self.bbrepo = bbrepo
        self.build_key = build_key
        self.merge_paths = merge_paths
        self._queues = OrderedDict()
        self._mergeable_queues = None
        self._mergeable_prs = []
        self._validated = False

    def build(self, repo):
        """Collect q branches from repository, add them to the collection."""
        cmd = 'git branch -r --list origin/q/*'
        for branch in repo.cmd(cmd).split('\n')[:-1]:
            match_ = re.match('\s*origin/(?P<name>.*)', branch)
            if not match_:
                continue
            try:
                branch = branch_factory(repo, match_.group('name'))
            except UnrecognizedBranchPattern:
                continue
            self._add_branch(branch)

        self.finalize()

    @property
    def mergeable_queues(self):
        """Return a collection of queues suitable for merge.

        This only works after the collection is validated.

        """
        if self._mergeable_queues is None:
            self._process()
        return self._mergeable_queues

    @property
    def mergeable_prs(self):
        """Return the list of pull requests suitable for merge.

        This only works after the collection is validated.

        """
        if self._mergeable_queues is None:
            self._process()
        return self._mergeable_prs

    def _add_branch(self, branch):
        """Add a single branch to the queue collection."""
        if not isinstance(branch, (QueueBranch, QueueIntegrationBranch)):
            raise InvalidQueueBranch(branch)
        self._validated = False
        # make sure we have a local copy of the branch
        # (enables get_latest_commit)
        branch.checkout()
        version = branch.version
        if version not in self._queues.keys():
            self._queues[version] = {
                QueueBranch: None,
                QueueIntegrationBranch: []
            }
            # Sort the top dict again
            self._queues = OrderedDict(sorted(self._queues.items()))

        if isinstance(branch, QueueBranch):
            self._queues[version][QueueBranch] = branch
        else:
            self._queues[version][QueueIntegrationBranch].append(branch)

    def _horizontal_validation(self, version):
        """Validation of the queue collection on one given version.

        Called by validate().

        """
        errors = []
        masterq = self._queues[version][QueueBranch]
        # check master queue state
        if not masterq:
            errors.append(
                MasterQueueMissing(version))
        else:
            if not masterq.includes_commit(masterq.destination_branch):
                errors.append(MasterQueueLateVsDev(
                    masterq,
                    masterq.destination_branch
                ))

            if not self._queues[version][QueueIntegrationBranch]:
                # check master queue points to dev
                if (masterq.get_latest_commit() !=
                        masterq.destination_branch.get_latest_commit()):
                    errors.append(MasterQueueNotInSync(
                        masterq,
                        masterq.destination_branch
                    ))
            else:
                # check state of master queue wrt to greatest integration
                # queue
                greatest_intq = (
                    self._queues[version][QueueIntegrationBranch][0]
                )
                if (greatest_intq.get_latest_commit() !=
                        masterq.get_latest_commit()):
                    if greatest_intq.includes_commit(masterq):
                        errors.append(MasterQueueLateVsInt(
                            masterq, greatest_intq))

                    elif masterq.includes_commit(greatest_intq):
                        errors.append(MasterQueueYoungerThanInt(
                            masterq, greatest_intq))

                    else:
                        errors.append(MasterQueueDiverged(
                            masterq, greatest_intq))

            # check each integration queue contains the previous one
            nextq = masterq
            for intq in self._queues[version][QueueIntegrationBranch]:
                if not nextq.includes_commit(intq):
                    errors.append(QueueInclusionIssue(nextq, intq))
                nextq = intq
            if not nextq.includes_commit(masterq.destination_branch):
                errors.append(QueueInclusionIssue(
                    nextq,
                    masterq.destination_branch
                ))
        return errors

    def _vertical_validation(self, stack, versions):
        """Validation of the queue collection on one given merge path.

        Called by validate().

        """

        errors = []
        prs = self._extract_pr_ids(stack)
        last_version = versions[-1]

        # check all subsequent versions have a master queue
        has_queues = False
        for version in versions:
            if version not in stack:
                if has_queues:
                    errors.append(MasterQueueMissing(version))
                continue
            has_queues = True
            if not stack[version][QueueBranch]:
                errors.append(MasterQueueMissing(version))

        # check queues are sync'ed vertically and included in each other
        # (last one corresponds to same PR on all versions..., and so on)
        # other way to say it: each version has all the PR_ids of the
        # previous version
        if last_version in stack:
            while stack[last_version][QueueIntegrationBranch]:
                next_vqint = stack[last_version][QueueIntegrationBranch].pop(0)
                pr = next_vqint.pr_id
                if pr not in prs:
                    # early fail
                    break
                for version in reversed(versions[:-1]):
                    if version not in stack:
                        # supposedly finished
                        break
                    if (stack[version][QueueIntegrationBranch] and
                            stack[version][QueueIntegrationBranch][0].pr_id ==
                            pr):
                        vqint = stack[version][QueueIntegrationBranch].pop(0)
                        # take this opportunity to check vertical inclusion
                        if not next_vqint.includes_commit(vqint):
                            errors.append(
                                QueueInclusionIssue(next_vqint, vqint))
                        next_vqint = vqint
                    else:
                        # this pr is supposedly entirely removed from the stack
                        # if it comes back again, its an error
                        break
                prs.remove(pr)
            if prs:
                # after this algorithm prs should be empty
                errors.append(QueueInconsistentPullRequestsOrder())
            else:
                # and stack should be empty too
                for version in versions:
                    if (version in stack and
                            stack[version][QueueIntegrationBranch]):
                        errors.append(QueueInconsistentPullRequestsOrder())
        return errors

    def validate(self):
        """Check the state of queues declared via add_branch.

        The following checks are performed:
        - horizontal checks: on a given branch version, each integration
            queue must include the previous one; the master queue must
            point to the last integration queue; In case there is no
            integration queue (nothing queued for this version), the
            master queue must point on the corresponding development
            branch.
        - vertical checks: across versions, on each merge path, the queues
            must be in the correct order (pr1 queued first, pr2 then, ...);
            when a pr is queued in a version, it must be present in all the
            following integration queues; for a given pr, the queues must be
            included in each other.
        - completeness: in order to detect missing integration queues
            (manuel delete for example), deconstruct the master queues
            by reverting merge commits; each result should not differ in
            content from the previous integration queue; The last diff is
            checked vs the corresponding development branch. TODO

        """
        errors = []
        versions = self._queues.keys()

        if not versions:
            # no queues, cool stuff
            self._validated = True
            return

        for version in versions:
            errs = self._horizontal_validation(version)
            errors.extend(errs)

        for merge_path in self.merge_paths:
            versions = [branch.version for branch in merge_path]
            stack = deepcopy(self._queues)
            # remove versions not on this merge_path from consideration
            for version in list(stack.keys()):
                if version not in versions:
                    stack.pop(version)

            errs = self._vertical_validation(stack, versions)
            errors.extend(errs)

        if errors:
            raise IncoherentQueues(errors)

        self._validated = True

    def _recursive_lookup(self, queues):
        """Given a set of queues, remove all queues that can't be merged,
        based on the build status obtained from the repository manager.

        A pull request must be removed from the list if the build on at least
        one version is FAILED, and if this failure is not recovered by
        a later pull request.

        Return once a mergeable set is identified or the set is empty.

        """
        first_failed_pr = 0
        for version in queues.keys():
            qints = queues[version][QueueIntegrationBranch]
            if qints:
                qint = qints[0]
                status = self.bbrepo.get_build_status(
                    qint.get_latest_commit(),
                    self.build_key
                )
                if status != 'SUCCESSFUL':
                    first_failed_pr = qint.pr_id
                    break

        if first_failed_pr == 0:
            # all tip queues are pass, merge as it is
            return

        # remove all queues that don't pass globally,
        # up to the identified failed pr, and retry
        for version in queues.keys():
            intqs = queues[version][QueueIntegrationBranch]
            while intqs:
                intq = intqs.pop(0)
                if intq.pr_id == first_failed_pr:
                    break

        self._recursive_lookup(queues)

    def _extract_pr_ids(self, queues):
        """Return list of pull requests present in a set of queues.

        This is obtained by reading pr ids from the greatest
        development queue branch, so assumes that this branch
        contains a reference to all pull requests in queues (this
        is normally the case if everything was queued by Bert-E.

        Return (list):
            pull request ids in provided queue set (in the order
                of addition to the queue, from oldest to newest)

        """
        prs = []
        # identify version corresponding to last dev queue
        # (i.e. ignore stab queues)
        greatest_dev = None
        for version in reversed(queues.keys()):
            if re.match(r'^\d+\.\d+$', version):
                greatest_dev = version
                break
        if greatest_dev:
            for qint in queues[greatest_dev][QueueIntegrationBranch]:
                prs.insert(0, qint.pr_id)
        return prs

    def _remove_unmergeable(self, prs, queues):
        """Given a set of queues, remove all queues that are not in
        the provided list of pull request ids.

        """
        for version in queues.keys():
            while (queues[version][QueueIntegrationBranch] and
                    queues[version][QueueIntegrationBranch][0].pr_id not in
                    prs):
                queues[version][QueueIntegrationBranch].pop(0)

    def _process(self):
        """Given a sorted list of queues, identify most buildable series.

        We need to look at mergeable PRs from the point of view
        of all the possible merge_paths individually, then merge
        the results in a super-mergeable status.

        Populates:
            - _mergeable_queues (list): queues corresponding to the
                mergeable PRs
            - _mergeable_prs (list): pull requests affected by the merge

        """
        if not self._validated:
            raise QueuesNotValidated()

        mergeable_prs = self._extract_pr_ids(self._queues)
        for merge_path in self.merge_paths:
            versions = [branch.version for branch in merge_path]
            stack = deepcopy(self._queues)
            # remove versions not on this merge_path from consideration
            for version in list(stack.keys()):
                if version not in versions:
                    stack.pop(version)

            # obtain list of mergeable prs on this merge_path
            self._recursive_lookup(stack)
            path_mergeable_prs = self._extract_pr_ids(stack)
            # smallest table is the common denominator
            if len(path_mergeable_prs) < len(mergeable_prs):
                mergeable_prs = path_mergeable_prs

        self._mergeable_prs = mergeable_prs
        mergeable_queues = deepcopy(self._queues)
        self._remove_unmergeable(mergeable_prs, mergeable_queues)
        self._mergeable_queues = mergeable_queues

    def finalize(self):
        """Finalize the collection of queues.

        Assumes _queues has been populated by calls to add_branch.

        """
        # order integration queues by content
        for version in self._queues.keys():
            self._queues[version][
                QueueIntegrationBranch].sort(reverse=True)


class BranchCascade(object):
    def __init__(self):
        self._cascade = OrderedDict()
        self._cascade_full = None
        self.destination_branches = []  # store branches
        self.ignored_branches = []  # store branch names (easier sort)
        self.target_versions = []
        self._merge_paths = []

    def build(self, repo, destination_branch=None):
        for prefix in ['development', 'stabilization']:
            cmd = 'git branch -r --list origin/%s/*' % prefix
            for branch in repo.cmd(cmd).split('\n')[:-1]:
                match_ = re.match('\s*origin/(?P<name>.*)', branch)
                if not match_:
                    continue
                try:
                    branch = branch_factory(repo, match_.group('name'))
                except UnrecognizedBranchPattern:
                    continue
                self.add_branch(branch)

        for tag in repo.cmd('git tag').split('\n')[:-1]:
            self.update_micro(tag)

        if destination_branch:
            self.finalize(destination_branch)

    def get_merge_paths(self):
        """Return the dict of all greatest merge paths.

        The items in the list correspond to:
        - the path (list of branches) from the oldest dev
            branch to the newest dev branch
        - the path (list of branches) from each stabilization branch
            to the newest dev branch

        This is used by QueueCollection to check the integrity of queues.

        It is not required to finalize the cascade to extract this
        information, a simple call to build is enough.

        """
        if self._merge_paths:
            return self._merge_paths

        ret = [[]]
        for branches in self._cascade.values():
            if branches[DevelopmentBranch]:
                if branches[StabilizationBranch]:
                    # create a new path starting from this stab
                    ret.append([branches[StabilizationBranch]])
                # append this version to all paths
                for path in ret:
                    path.append(branches[DevelopmentBranch])
        self._merge_paths = ret
        return ret

    def add_branch(self, branch):
        if not branch.can_be_destination:
            logging.debug("Discard non destination branch: %s", branch)
            return
        (major, minor) = branch.major, branch.minor
        if (major, minor) not in self._cascade.keys():
            self._cascade[(major, minor)] = {
                DevelopmentBranch: None,
                StabilizationBranch: None,
            }
            # Sort the cascade again
            self._cascade = OrderedDict(sorted(self._cascade.items()))
        cur_branch = self._cascade[(major, minor)][branch.__class__]

        if cur_branch:
            raise UnsupportedMultipleStabBranches(cur_branch, branch)

        self._cascade[(major, minor)][branch.__class__] = branch

    def update_micro(self, tag):
        """Update development branch latest micro based on tag."""
        pattern = "^(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<micro>\d+))$"
        match = re.match(pattern, tag)
        if not match:
            logging.debug("Ignore tag: %s", tag)
            return
        logging.debug("Consider tag: %s", tag)
        major = int(match.groupdict()['major'])
        minor = int(match.groupdict()['minor'])
        micro = int(match.groupdict()['micro'])
        try:
            branches = self._cascade[(major, minor)]
        except KeyError:
            logging.debug("Ignore tag: %s", tag)
            return
        stb_branch = branches[StabilizationBranch]

        if stb_branch is not None and stb_branch.micro <= micro:
            # We have a tag but we did not remove the stabilization branch.
            raise DeprecatedStabilizationBranch(stb_branch.name, tag)

        dev_branch = branches[DevelopmentBranch]
        if dev_branch:
            dev_branch.micro = max(micro, dev_branch.micro)

    def validate(self):
        previous_dev_branch = None
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if dev_branch is None:
                raise DevBranchDoesNotExist(
                    'development/%d.%d' % (major, minor))

            if stb_branch:
                if dev_branch.micro != stb_branch.micro + 1:
                    raise VersionMismatch(dev_branch, stb_branch)

                if not dev_branch.includes_commit(stb_branch):
                    raise DevBranchesNotSelfContained(stb_branch, dev_branch)

            if previous_dev_branch:
                if not dev_branch.includes_commit(previous_dev_branch):
                    raise DevBranchesNotSelfContained(previous_dev_branch,
                                                      dev_branch)

            previous_dev_branch = dev_branch

    def _set_target_versions(self, destination_branch):
        """Compute list of expected Jira FixVersion/s.

        Must be called after the cascade has been finalised.

        """
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if stb_branch:
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, stb_branch.micro))
            else:
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, dev_branch.micro))

    def finalize(self, destination_branch):
        """Finalize cascade considering given destination.

        Assumes the cascade has been populated by calls to add_branch
        and update_micro. The local lists keeping track

        Args:
            destination_branch: where the pull request wants to merge

        Raises:

        Returns:
            list: list of destination branches
            list: list of ignored destination branches

        """
        self.get_merge_paths()  # populate merge paths before removing data
        ignore_stb_branches = False
        include_dev_branches = False
        dev_branch = None

        for (major, minor), branch_set in list(self._cascade.items()):
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if dev_branch is None:
                raise DevBranchDoesNotExist(
                    'development/%d.%d' % (major, minor))

            # update _expected_ micro versions
            if stb_branch:
                dev_branch.micro += 2
            else:
                dev_branch.micro += 1

            # remove untargetted branches from cascade
            if destination_branch == dev_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if stb_branch and ignore_stb_branches:
                branch_set[StabilizationBranch] = None
                self.ignored_branches.append(stb_branch.name)

            if destination_branch == stb_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if not include_dev_branches:
                branch_set[DevelopmentBranch] = None
                self.ignored_branches.append(dev_branch.name)

                if branch_set[StabilizationBranch]:
                    branch_set[StabilizationBranch] = None
                    self.ignored_branches.append(stb_branch.name)

                del self._cascade[(major, minor)]
                continue

            # add to destination_branches in the correct order
            if branch_set[StabilizationBranch]:
                self.destination_branches.append(stb_branch)
            if branch_set[DevelopmentBranch]:
                self.destination_branches.append(dev_branch)

        if not dev_branch:
            raise NotASingleDevBranch()

        self._set_target_versions(destination_branch)
        self.ignored_branches.sort()


class BertE:
    def __init__(self, args, options, commands, settings):
        self._bbconn = bitbucket_api.Client(
            settings['robot_username'],
            args.bitbucket_password,
            settings['robot_email']
        )
        self.bbrepo = bitbucket_api.Repository(
            self._bbconn,
            owner=settings['repository_owner'],
            repo_slug=settings['repository_slug']
        )
        self.options = options
        self.commands = commands
        self.settings = settings
        self.jira_password = args.jira_password
        self.backtrace = args.backtrace
        self.interactive = args.interactive
        self.no_comment = args.no_comment
        self.quiet = args.quiet
        self.token = args.token.strip()
        self.use_queue = not args.disable_queues
        self.repo = GitRepository(self.bbrepo.get_git_url())
        self.tmpdir = self.repo.tmp_directory

    def handler(self):
        """Determine the resolution path based on the input id.

        Args:
          - token (str):
            - pull request id: handle the pull request update
            - sha1: analyse state of the queues,
               only if the sha1 belongs to a queue

        Returns:
            - a Bert-E return code

        """
        try:
            if len(self.token) in SHA1_LENGHT:
                branches = self.repo.get_branches_from_sha1(self.token)
                for branch in branches:
                    if self.use_queue and isinstance(
                            branch_factory(self.repo, branch),
                            QueueIntegrationBranch):
                        return self.handle_merge_queues()   # queued

                return self.handle_pull_request_from_sha1(self.token)

            try:
                int(self.token)
            except ValueError:
                pass
            else:
                # it is probably a pull request id
                return self.handle_pull_request(self.token)

            raise UnsupportedTokenType(self.token)

        except SilentException as excp:
            if self.backtrace:
                raise

            logging.info('Exception raised: %d', excp.code)
            if not self.quiet:
                print('%d - %s' % (0, excp.__class__.__name__))
            return 0

    def handle_pull_request(self, pr_id):
        """Entry point to handle a pull request id."""
        self._pr = BertEPullRequest(
            self.bbrepo,
            self.settings['robot_username'],
            pr_id
        )
        self._cascade = BranchCascade()

        try:
            self._handle_pull_request()
        except TemplateException as excp:
            self.send_msg_and_continue(excp)

            if self.backtrace:
                raise excp

            logging.info('Exception raised: %d %s', excp.code, excp.__class__)
            if not self.quiet:
                print('%d - %s' % (excp.code, excp.__class__.__name__))
            return excp.code

    def handle_pull_request_from_sha1(self, sha1):
        """Entry point to handle a pull request from a sha1."""
        pr = self.get_integration_pull_request_from_sha1(sha1)
        if not pr:
            raise NothingToDo('Could not find the PR corresponding to'
                              ' sha1: %s' % sha1)
        return self.handle_pull_request(pr.id)

    def handle_merge_queues(self):
        """Entry point to handle queues following a build status update."""
        self._clone_git_repo()
        cascade = BranchCascade()
        cascade.build(self.repo)
        qc = self._validate_queues(cascade)

        # Update the queue status
        update_queue_status(qc)

        if not qc.mergeable_prs:
            raise NothingToDo()

        self._merge_queues(qc.mergeable_queues)

        # notify PRs and cleanup
        for pr_id in qc.mergeable_prs:
            self._close_queued_pull_request(pr_id, deepcopy(cascade))
            add_merged_pr(pr_id)

        # git push --all --force --prune
        self._push(prune=True)
        raise Merged()

    def get_integration_pull_request_from_sha1(self, sha1):
        """Get the oldest open integration pull request containing given
        commit.

        """
        open_prs = list(self.bbrepo.get_pull_requests())
        candidates = sorted(
            filter(bool, (b.get_pull_request_from_list(open_prs) for b in
                          self._get_integration_branches_from_sha1(sha1))),
            key=lambda pr: pr.id
        )
        if candidates:
            return candidates[0]

    def _get_integration_branches_from_sha1(self, sha1):
        git_repo = GitRepository(self.bbrepo.get_git_url())
        return [IntegrationBranch(self, branch) for branch in
                git_repo.get_branches_from_sha1(sha1)
                if branch.startswith('w/')]

    def option_is_set(self, name):
        if name not in self.options.keys():
            return False
        return self.options[name].is_set()

    def _get_active_options(self):
        return [option for option in self.options.keys() if
                self.option_is_set(option)]

    def print_help(self, args):
        raise HelpMessage(options=self.options,
                          commands=self.commands,
                          active_options=self._get_active_options())

    def get_status_report(self):
        # tmp hard coded
        return {}

    def publish_status_report(self, args):
        raise StatusReport(status=self.get_status_report(),
                           active_options=self._get_active_options())

    def command_not_implemented(self, args):
        raise CommandNotImplemented(
            active_options=self._get_active_options()
        )

    def find_bitbucket_comment(self,
                               username=None,
                               startswith=None,
                               max_history=None):
        # check last commits
        comments = reversed(self._pr.comments)
        if max_history not in (None, -1):
            comments = itertools.islice(comments, 0, max_history)
        for comment in comments:
            u = comment.author
            raw = comment.text
            # python3
            if isinstance(username, str) and u != username:
                continue
            # python2
            if isinstance(username, list) and u not in username:
                continue
            if startswith and not raw.startswith(startswith):
                if max_history == -1:
                    return
                continue
            return comment

    def send_bitbucket_msg(self, msg, dont_repeat_if_in_history=10):
        if self.no_comment:
            logging.debug('not sending message due to no_comment being True.')
            return

        # Apply no-repeat strategy
        if dont_repeat_if_in_history:
            if self.find_bitbucket_comment(
                    username=self.settings['robot_username'],
                    startswith=msg,
                    max_history=dont_repeat_if_in_history):
                raise CommentAlreadyExists(
                    'The same comment has already been posted '
                    'in the past. Nothing to do here!'
                )

        if self.interactive:
            print('%s\n' % msg)
            if not confirm('Do you want to send this comment?'):
                return

        logging.debug('SENDING MSG %s', msg)
        return self._pr.bb_pr.add_comment(msg)

    def create_task(self, task, comment):
        if self.no_comment:
            logging.debug('not sending message due to no_comment being True.')
            return

        if self.interactive:
            print('%s\n' % task)
            if not confirm('Do you want to create this task?'):
                return

        logging.debug('CREATING TASK %s', task)

        try:
            comment.add_task(task)
        except TaskAPIError as err:
            logging.error('could not create task %s (%s)', task, err)
            pass

    def send_msg_and_continue(self, msg):
        try:
            return self.send_bitbucket_msg(str(msg),
                                           msg.dont_repeat_if_in_history)
        except CommentAlreadyExists:
            logging.info("Comment '%s' already posted", msg.__class__.__name__)

    def _check_pr_state(self):
        if self._pr.bb_pr.status not in ('OPEN', 'DECLINED'):
            raise NothingToDo('The pull-request\'s state is "%s"'
                              % self._pr.bb_pr.status)
        return self._pr.bb_pr.status

    def _clone_git_repo(self):
        repo = self.repo
        repo.clone()
        repo.config('user.email', self.settings['robot_email'])
        repo.config('user.name', self.settings['robot_username'])
        repo.config('merge.renameLimit', '999999')
        return repo

    def _setup_source_branch(self, src_branch_name, dst_branch_name):
        self._pr.source_branch = branch_factory(self.repo, src_branch_name)

    def _setup_destination_branch(self, dst_branch_name):
        self.destination_branch = branch_factory(self.repo, dst_branch_name)

    def _handle_declined_pr(self):
        # main PR is declined, cleanup everything and quit
        self._build_branch_cascade()
        changed = self._remove_integration_data(self._pr.source_branch)

        if changed:
            self._push(prune=True)
            raise PullRequestDeclined()
        else:
            raise NothingToDo()

    def _check_if_ignored(self):
        # check feature branch
        if not self._pr.source_branch.cascade_producer:
            raise NotMyJob(self._pr.source_branch.name,
                           self.destination_branch.name)

        # check selected destination branch
        if not self.destination_branch.cascade_consumer:
            raise NotMyJob(self._pr.source_branch.name,
                           self.destination_branch.name)

    def _send_greetings(self):
        """Display a welcome message if conditions are met."""
        # Skip if the robot has already posted a comment on this PR
        if self.find_bitbucket_comment(
                username=self.settings['robot_username']):
            return

        # On bitbucket tasks are displayed LIFO so we reverse to keep ordering
        tasks = list(reversed(self.settings.get('tasks', [])))

        comment = self.send_msg_and_continue(InitMessage(
            bert_e=self.settings['robot_username'],
            author=self._pr.author_display_name,
            status=self.get_status_report(),
            active_options=self._get_active_options(),
            tasks=tasks,
        ))

        for task in tasks:
            self.create_task(task, comment)

    def _check_options(self, comment_author, pr_author, keyword_list, comment):
        logging.debug('checking keywords %s', keyword_list)

        for idx, keyword in enumerate(keyword_list):
            if keyword.startswith('after_pull_request='):
                match_ = re.match('after_pull_request=(?P<pr_id>\d+)$',
                                  keyword)
                if not match_:
                    return False
                self._pr.after_prs.append(match_.group('pr_id'))
                keyword = 'after_pull_request'

            if keyword not in self.options.keys():
                # the first keyword may be a valid command
                if idx == 0 and keyword in self.commands:
                    logging.debug("ignoring options due to unknown keyword")
                    return False

                raise UnknownCommand(active_options=self._get_active_options(),
                                     command=keyword,
                                     author=comment_author,
                                     comment=comment)

            limited_access = self.options[keyword].privileged
            if limited_access:
                if comment_author == pr_author:
                    raise NotEnoughCredentials(
                        active_options=self._get_active_options(),
                        command=keyword,
                        author=comment_author,
                        self_pr=True,
                        comment=comment
                    )

                if comment_author not in self.settings['admins']:
                    raise NotEnoughCredentials(
                        active_options=self._get_active_options(),
                        command=keyword,
                        author=comment_author,
                        self_pr=False,
                        comment=comment
                    )

        return True

    def _get_options(self, pr_author):
        """Load settings from pull-request comments."""
        username = self.settings['robot_username']
        for comment in self._pr.comments:
            raw = comment.text
            if not raw.strip().startswith('@%s' % username):
                continue

            logging.debug('Found a keyword comment: %s', raw)
            raw_cleaned = raw.strip()[len(username) + 1:]

            # accept all options in the form:
            # @{robot_username} option1 option2...
            # @{robot_username} option1, option2, ...
            # @{robot_username}: option1 - option2 - ...
            raw_cleaned = re.sub(r'[,.\-/:;|+]', ' ', raw_cleaned)
            regexp = r"\s*(?P<keywords>(\s+[\w=]+)+)\s*$"
            match_ = re.match(regexp, raw_cleaned)
            if not match_:
                logging.debug('Keyword comment ignored. '
                              'Not an option, unknown format: %s', raw)
                continue

            keywords = match_.group('keywords').strip().split()

            if not self._check_options(comment.author, pr_author,
                                       keywords, raw):
                logging.debug('Keyword comment ignored. '
                              'Not an option, checks failed: %s', raw)
                continue

            for keyword in keywords:
                # strip args
                option = keyword.split('=')[0]
                self.options[option].set(True)

    def _check_command(self, author, command, comment):
        logging.debug('checking command %s', command)

        if command not in self.commands:
            if command in self.options:
                logging.debug("Ignoring option")
                return False
            # Should not happen because of previous option check,
            # better be safe than sorry though
            raise UnknownCommand(active_options=self._get_active_options(),
                                 command=command,
                                 author=author,
                                 comment=comment)

        limited_access = self.commands[command].privileged
        if limited_access and author not in self.settings['admins']:
            raise NotEnoughCredentials(
                active_options=self._get_active_options(),
                command=command,
                author=author,
                self_pr=False,
                comment=comment
            )
        return True

    def _handle_commands(self):
        """Detect the last command in pull-request comments and act on it."""
        username = self.settings['robot_username']
        for comment in reversed(self._pr.comments):
            # if Bert-E is the author of this comment, any previous command
            # has been treated or is outdated, since Bert-E replies to all
            # commands. The search is over.
            if comment.author == username:
                return

            raw = comment.text
            if not raw.strip().startswith('@%s' % username):
                continue

            logging.debug('Found a potential command comment: %s', raw)

            # accept all commands in the form:
            # @{robot_username} command arg1 arg2 ...
            regexp = "@%s[\s:]*" % username
            raw_cleaned = re.sub(regexp, '', raw.strip())
            regexp = r"(?P<command>[A-Za-z_]+[^= ,])(?P<args>.*)$"
            match_ = re.match(regexp, raw_cleaned)
            if not match_:
                logging.warning('Command comment ignored. '
                                'Not a command, unknown format: %s' % raw)
                continue

            command = match_.group('command')

            if not self._check_command(comment.author, command, raw):
                logging.debug('Command comment ignored. '
                              'Not a command, checks failed: %s' % raw)
                continue

            # get command handler and execute it
            assert hasattr(self, self.commands[command].handler)
            handler = getattr(self, self.commands[command].handler)
            handler(match_.group('args'))

    def _init_phase(self):
        """Send greetings if required, read options and commands."""
        # read comments and store them for multiple usage
        self._pr.comments = list(self._pr.bb_pr.get_comments())
        if (self._pr.comments and
                self._pr.comments[0]['id'] > self._pr.comments[-1]['id']):
            self._pr.comments.reverse()

        self._send_greetings()
        self._get_options(self._pr.author)
        self._handle_commands()

    def _check_dependencies(self):
        if self.option_is_set('wait'):
            raise NothingToDo('wait option is set')

        if not self._pr.after_prs:
            return

        prs = [self.bbrepo.get_pull_request(int(pr_id))
               for pr_id in self._pr.after_prs]

        opened_prs = [p for p in prs if p.status == 'OPEN']
        merged_prs = [p for p in prs if p.status == 'MERGED']
        declined_prs = [p for p in prs if p.status == 'DECLINED']

        if len(self._pr.after_prs) != len(merged_prs):
            raise AfterPullRequest(
                opened_prs=opened_prs,
                declined_prs=declined_prs,
                active_options=self._get_active_options())

    def _build_branch_cascade(self):
        if self._cascade.destination_branches:
            # building cascade one time is enough
            return
        self._cascade.build(self.repo, self.destination_branch)

    def _check_compatibility_src_dest(self):
        if self.option_is_set('bypass_incompatible_branch'):
            return
        for dest_branch in self._cascade.destination_branches:
            if self._pr.source_branch.prefix not in dest_branch.allow_prefixes:
                raise IncompatibleSourceBranchPrefix(
                    source=self._pr.source_branch,
                    destination=self.destination_branch,
                    active_options=self._get_active_options())

    def _jira_check_reference(self):
        """Check the reference to a Jira issue in the source branch.

        Returns:
            bool: True if the reference is valid and must be checked
                  False if the Jira issue should be ignored

        Raises:
            MissingJiraId: if a Jira issue is required but missing

        """
        if not self._pr.source_branch.jira_issue_key:
            for dest_branch in self._cascade.destination_branches:
                if not dest_branch.allow_ticketless_pr:
                    raise MissingJiraId(
                        source_branch=self._pr.source_branch.name,
                        dest_branch=dest_branch.name,
                        active_options=self._get_active_options())
            return False
        return True

    def _jira_get_issue(self, issue_id):
        try:
            issue = jira_api.JiraIssue(
                account_url=self.settings['jira_account_url'],
                issue_id=issue_id,
                login=self.settings['jira_username'],
                passwd=self.jira_password)
        except JIRAError as e:
            if e.status_code == 404:
                raise JiraIssueNotFound(
                    issue=issue_id,
                    active_options=self._get_active_options())

            else:
                raise

        return issue

    def _jira_check_project(self, issue):
        # check the project
        if (self._pr.source_branch.jira_project not in
                self.settings['jira_keys']):
            expected = ', '.join(self.settings['jira_keys'])
            raise IncorrectJiraProject(
                expected_project=expected,
                issue=issue,
                active_options=self._get_active_options()
            )

    def _jira_check_issue_type(self, issue):
        issuetype = issue.fields.issuetype.name

        prefixes = self.settings.get('prefixes')
        if issuetype == 'Sub-task':
            raise SubtaskIssueNotSupported(
                issue=issue,
                pairs=prefixes,
                active_options=self._get_active_options())

        if not prefixes:
            # no settings specified, accept all
            return

        expected_prefix = prefixes.get(issuetype)
        if expected_prefix is None:
            raise JiraUnknownIssueType(issuetype)

        if expected_prefix != self._pr.source_branch.prefix:
            raise MismatchPrefixIssueType(
                prefix=self._pr.source_branch.prefix,
                expected=issuetype,
                pairs=prefixes,
                issue=issue,
                active_options=self._get_active_options())

    def _jira_check_version(self, issue):
        issue_versions = [version.name for version in
                          issue.fields.fixVersions]
        issue_versions.sort()
        issue_versions = set(issue_versions)
        expect_versions = self._cascade.target_versions
        expect_versions.sort()
        expect_versions = set(expect_versions)

        if issue_versions != expect_versions:
            raise IncorrectFixVersion(
                issue=issue,
                issue_versions=issue_versions,
                expect_versions=expect_versions,
                active_options=self._get_active_options())

    def _jira_checks(self):
        """Check the Jira issue id specified in the source branch."""
        if self.option_is_set('bypass_jira_check'):
            return

        if (not self.settings['jira_keys'] or
                not self.settings['jira_username'] or
                not self.settings['jira_account_url']):
            # skip checks
            return

        if self._jira_check_reference():
            issue_id = self._pr.source_branch.jira_issue_key
            issue = self._jira_get_issue(issue_id)

            self._jira_check_project(issue)
            self._jira_check_issue_type(issue)
            self._jira_check_version(issue)

    def _check_source_branch_still_exists(self):
        # check source branch still exists
        # (it may have been deleted by developers)
        try:
            Branch(self.repo, self._pr.source_branch.name).checkout()
        except CheckoutFailedException:
            raise NothingToDo(self._pr.source_branch.name)

    def _create_integration_branches(self, source_branch):
        integration_branches = []
        for dst_branch in self._cascade.destination_branches:
            name = 'w/%s/%s' % (dst_branch.version, source_branch)
            integration_branch = branch_factory(self.repo, name)
            integration_branch.source_branch = source_branch
            integration_branch.destination_branch = dst_branch
            integration_branches.append(integration_branch)
            if not integration_branch.exists():
                integration_branch.create(
                    integration_branch.destination_branch)
        return integration_branches

    def _remove_integration_data(self, source_branch):
        changed = False
        open_prs = list(self.bbrepo.get_pull_requests())
        for dst_branch in self._cascade.destination_branches:
            name = 'w/%s/%s' % (dst_branch.version, source_branch)
            # decline integration PR
            for pr in open_prs:
                if (
                    pr.status == 'OPEN' and
                    pr.src_branch == name and
                    pr.dst_branch == dst_branch.name
                ):
                    pr.decline()
                    changed = True
                    break
            # remove integration branch
            integration_branch = branch_factory(self.repo, name)
            integration_branch.source_branch = source_branch
            integration_branch.destination_branch = dst_branch
            if integration_branch.exists():
                integration_branch.remove()
                changed = True
        return changed

    def _check_in_sync(self, integration_branches):
        """Validate that each `integration_branch` contains the last
        commit from its predecessor.

        Return (bool):
            - True: all in sync
            - False: one of the integration branch at least needs an
             update

        """
        prev = integration_branches[0].source_branch
        for branch in integration_branches:
            if not branch.includes_commit(
                    prev.get_latest_commit()):
                return False
            prev = branch
        return True

    def _check_pristine(self, integration_branch):
        """Validate that `integration_branch` contains commits
        from its source branch and destination branch only.

        This method is only optimised for the _first_ integration
        branch (the current use case).

        raises:
            - BranchHistoryMismatch: if a commit from neither source
               nor destination is detected

        """
        source_branch = integration_branch.source_branch
        destination_branch = integration_branch.destination_branch
        # Always get new commits compared to the destination (i.e. obtain the
        # list of commits from the source branch), because
        # the destination may grow very fast during the lifetime of the
        # source branch. A long list is very slow to process due to the loop
        # RELENG-1451.
        for commit in integration_branch.get_commit_diff(destination_branch):
            if not source_branch.includes_commit(commit):
                raise BranchHistoryMismatch(
                    commit=commit,
                    integration_branch=integration_branch,
                    feature_branch=source_branch,
                    development_branch=destination_branch,
                    active_options=self._get_active_options())

    def _update(self, wbranch, source, origin=False):
        try:
            wbranch.merge(wbranch.destination_branch, source)
        except MergeFailedException:
            wbranch.reset(False)
            try:
                wbranch.merge(source, wbranch.destination_branch)
            except MergeFailedException:
                raise Conflict(source=source,
                               wbranch=wbranch,
                               active_options=self._get_active_options(),
                               origin=origin,
                               feature_branch=self._pr.source_branch,
                               dev_branch=self.destination_branch)

    def _update_integration(self, integration_branches):
        prev, children = integration_branches[0], integration_branches[1:]
        self._check_pristine(prev)
        self._update(prev, self._pr.source_branch, True)
        for branch in children:
            self._update(branch, prev)
            prev = branch

    def _create_pull_requests(self, integration_branches):
        # read open PRs and store them for multiple usage
        open_prs = list(self.bbrepo.get_pull_requests())
        prs, created = zip(*(
            integration_branch.get_or_create_pull_request(self._pr.bb_pr,
                                                          open_prs,
                                                          self.bbrepo,
                                                          idx == 0)
            for idx, integration_branch in enumerate(integration_branches)
        ))
        if any(created):
            self.send_msg_and_continue(IntegrationPullRequestsCreated(
                bert_e=self.settings['robot_username'],
                pr=self._pr.bb_pr, child_prs=prs,
                ignored=self._cascade.ignored_branches,
                active_options=self._get_active_options()
            ))
        return prs

    def _check_pull_request_skew(self, integration_branches, integration_prs):
        """Check potential skew between local commit and commit in PR.

        Three cases are possible:
        - the local commit and the commit we obtained in the PR
          object are identical; nothing to do

        - the local commit, that has just been pushed by Bert-E,
          does not reflect yet in the PR object we obtained from
          bitbucket (the cache mechanism from BB mean the PR is still
          pointing to a previous commit); the solution is to update
          the PR object with the latest commit we know of

        - the local commit is outdated, someone else has pushed new
          commits on the integration branch, and it reflects in the PR
          object; in this case we abort the process, Bert-E will be
          called again on the new commits.

        """
        for branch, pr in zip(integration_branches, integration_prs):
            branch_sha1 = branch.get_latest_commit()
            pr_sha1 = pr.src_commit  # 12 hex hash
            if branch_sha1.startswith(pr_sha1):
                continue

            if branch.includes_commit(pr_sha1):
                logging.warning('Skew detected (expected commit: %s, '
                                'got PR commit: %s).', branch_sha1,
                                pr_sha1)
                logging.warning('Updating the integration PR locally.')
                pr.src_commit = branch_sha1
                continue

            raise PullRequestSkewDetected(pr.id, branch_sha1, pr_sha1)

    def _check_approvals(self):
        """Check approval of a PR by author, tester and peer.

        Raises:
            - AuthorApprovalRequired
            - PeerApprovalRequired
            - TesterApprovalRequired

        """
        required_peer_approvals = self.settings['required_peer_approvals']
        current_peer_approvals = 0
        if self.option_is_set('bypass_peer_approval'):
            current_peer_approvals = required_peer_approvals
        approved_by_author = self.option_is_set('bypass_author_approval')
        approved_by_tester = self.option_is_set('bypass_tester_approval')
        requires_unanimity = self.option_is_set('unanimity')
        is_unanimous = True

        if not self.settings['testers']:
            # if the project does not declare any testers,
            # just assume a pseudo-tester has approved the PR
            approved_by_tester = True

        # If a tester is the author of the PR we will bypass
        #  the tester approval
        if self._pr.author in self.settings['testers']:
            approved_by_tester = True

        if (approved_by_author and
                (current_peer_approvals >= required_peer_approvals) and
                approved_by_tester and not requires_unanimity):
            return

        # NB: when author hasn't approved the PR, author isn't listed in
        # 'participants'
        username = self.settings['robot_username']

        participants = set(self._pr.bb_pr.get_participants())
        approvals = set(self._pr.bb_pr.get_approvals())

        # Exclude Bert-E from consideration
        participants -= {username}

        testers = set(self.settings['testers'])

        is_unanimous = approvals - {username} == participants
        approved_by_author |= self._pr.author in approvals
        approved_by_tester |= bool(approvals & testers)
        peer_approvals = approvals - testers - {self._pr.author}
        current_peer_approvals += len(peer_approvals)
        missing_peer_approvals = (
            required_peer_approvals - current_peer_approvals)

        if not approved_by_author:
            raise AuthorApprovalRequired(
                pr=self._pr.bb_pr,
                author_approval=approved_by_author,
                missing_peer_approvals=missing_peer_approvals,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if missing_peer_approvals > 0:
            raise PeerApprovalRequired(
                pr=self._pr.bb_pr,
                author_approval=approved_by_author,
                missing_peer_approvals=missing_peer_approvals,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if testers and not approved_by_tester:
            raise TesterApprovalRequired(
                pr=self._pr.bb_pr,
                author_approval=approved_by_author,
                missing_peer_approvals=missing_peer_approvals,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if requires_unanimity and not is_unanimous:
            raise UnanimityApprovalRequired(
                pr=self._pr.bb_pr,
                author_approval=approved_by_author,
                missing_peer_approvals=missing_peer_approvals,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

    def _get_sha1_build_status(self, sha1, key=None):
        key = key or self.settings['build_key']
        return self.bbrepo.get_build_status(sha1, key)

    def _get_pr_build_status(self, key, pr):
        return self._get_sha1_build_status(pr.src_commit, key)

    def _check_build_status(self, child_prs):
        """Report the worst status available."""
        if self.option_is_set('bypass_build_status'):
            return

        key = self.settings['build_key']
        if not key:
            return

        ordered_state = ['SUCCESSFUL', 'INPROGRESS', 'NOTSTARTED', 'FAILED']
        g_state = 'SUCCESSFUL'
        worst_pr = child_prs[0]
        for pr in child_prs:
            build_state = self._get_pr_build_status(key, pr)
            if ordered_state.index(g_state) < ordered_state.index(build_state):
                g_state = build_state
                worst_pr = pr

        if g_state == 'FAILED':
            raise BuildFailed(pr_id=worst_pr.id,
                              active_options=self._get_active_options())
        elif g_state == 'NOTSTARTED':
            raise BuildNotStarted()
        elif g_state == 'INPROGRESS':
            raise BuildInProgress()
        assert build_state == 'SUCCESSFUL'

    def _get_queue_branch(self, dev_branch, create=True):
        name = 'q/%s' % dev_branch.version
        queue_branch = branch_factory(self.repo, name)
        if not queue_branch.exists() and create:
            queue_branch.create(dev_branch)
        return queue_branch

    def _get_queue_integration_branch(self, pr_id, integration_branch):
        """Get the q/pr_id/x.y/* branch corresponding to a w/x.y/* branch."""
        wbranch = integration_branch
        name = 'q/%s/%s/%s' % (pr_id, wbranch.version, self._pr.source_branch)
        qint_branch = branch_factory(self.repo, name)
        return qint_branch

    def _add_to_queue(self, integration_branches):
        qbranches = [self._get_queue_branch(w.destination_branch)
                     for w in integration_branches]

        to_push = list(qbranches)
        qbranch, qbranches = qbranches[0], qbranches[1:]
        wbranch, wbranches = integration_branches[0], integration_branches[1:]

        try:
            qbranch.merge(wbranch)
            qint = self._get_queue_integration_branch(
                self._pr.bb_pr.id, wbranch)
            qint.create(qbranch, do_push=False)
            to_push.append(qint)
            for qbranch, wbranch in zip(qbranches, wbranches):
                try:
                    qbranch.merge(wbranch, qint)  # octopus merge
                except MergeFailedException:
                    qbranch.reset(False)
                    qbranch.merge(qint, wbranch)

                qint = self._get_queue_integration_branch(
                    self._pr.bb_pr.id, wbranch)
                qint.create(qbranch, do_push=False)
                to_push.append(qint)
        except MergeFailedException:
            raise QueueConflict(active_options=self._get_active_options())

        self._push(to_push)

    def _already_in_queue(self, integration_branches):
        qint_branches = [
            self._get_queue_integration_branch(self._pr.bb_pr.id, w)
            for w in integration_branches
        ]
        exist = [q.exists() for q in qint_branches]
        return any(exist)

    def _merge(self, integration_branches):
        for integration_branch in integration_branches:
            integration_branch.update_to_development_branch()

        for integration_branch in integration_branches:
            try:
                integration_branch.remove()
            except RemoveFailedException:
                # ignore failures as this is non critical
                pass

        self._push(prune=True)

    def _merge_queues(self, queues):
        for branches in queues.values():
            # Fast-forward development/x.y to the most recent mergeable queue
            destination = branches[QueueBranch].destination_branch
            if branches[QueueIntegrationBranch]:
                latest = branches[QueueIntegrationBranch][0]
                logging.debug("Merging %s into %s", latest, destination)
                destination.merge(latest)

                # Delete the merged queue-integration branches
                for queue in branches[QueueIntegrationBranch]:
                    logging.debug("Removing %s", queue)
                    queue.remove()

    def _validate_repo(self):
        self._cascade.validate()

    def _validate_queues(self, cascade):
        qc = QueueCollection(
            self.bbrepo,
            self.settings['build_key'],
            cascade.get_merge_paths()
        )
        qc.build(self.repo)
        # extract destination branches from cascade
        qc.validate()
        return qc

    def _push(self, branches=(), prune=False):
        retry = RetryHandler(30, logging)
        names = ''
        if branches:
            names = ' '.join("'{0}'".format(b.name) for b in branches)
            with retry:
                retry.run(
                    self.repo.push, names,
                    catch=PushFailedException,
                    fail_msg="Failed to push changes"
                )
        else:
            with retry:
                retry.run(
                    self.repo.push_all,
                    prune=prune,
                    catch=PushFailedException,
                    fail_msg="Failed to push changes"
                )

    def _close_queued_pull_request(self, pr_id, cascade):
        self._pr = BertEPullRequest(
            self.bbrepo, self.settings['robot_username'], pr_id)
        self._cascade = cascade
        src_branch = branch_factory(
            self.repo,
            self._pr.bb_pr.src_branch
        )
        dst_branch = branch_factory(
            self.repo,
            self._pr.bb_pr.dst_branch
        )
        self._cascade.finalize(dst_branch)

        if dst_branch.includes_commit(src_branch.get_latest_commit()):
            # Everything went fine, send a success message
            self.send_msg_and_continue(SuccessMessage(
                branches=self._cascade.destination_branches,
                ignored=self._cascade.ignored_branches,
                issue=src_branch.jira_issue_key,
                author=self._pr.bb_pr.author_display_name,
                active_options=[]))

        else:
            # Frown at the author for adding posterior changes. This
            # message will wake Bert-E up on the Pull Request, and the queues
            # have disappeared, so the normal pre-queuing workflow will restart
            # naturally.
            commits = src_branch.get_commit_diff(dst_branch)
            self.send_msg_and_continue(PartialMerge(
                commits=commits,
                branches=self._cascade.destination_branches,
                active_options=[]))

        # Remove integration branches (potentially let Bert-E rebuild them if
        # the merge was partial)
        wbranches = self._create_integration_branches(src_branch)

        # Checkout destination branch so we are not on a w/* branch when
        # deleting it.
        dst_branch.checkout()
        for wbranch in wbranches:
            try:
                wbranch.remove()
            except RemoveFailedException:
                # not critical
                pass

    def _handle_pull_request(self):
        """Analyse and handle a pull request that has just been updated."""

        self._check_pr_state()

        dst_branch_name = self._pr.bb_pr.dst_branch
        src_branch_name = self._pr.bb_pr.src_branch
        self._setup_source_branch(src_branch_name, dst_branch_name)
        self._setup_destination_branch(dst_branch_name)
        self._check_if_ignored()

        self._init_phase()
        self._check_dependencies()

        # Now we're actually going to work on the repository. Let's clone it.
        self._clone_git_repo()

        if self._pr.bb_pr.status == 'DECLINED':
            self._handle_declined_pr()

        # Handle the case when bitbucket is lagging and the PR was actually
        # merged before.
        if self.destination_branch.includes_commit(self._pr.source_branch):
            raise NothingToDo()

        self._build_branch_cascade()
        self._validate_repo()
        self._check_compatibility_src_dest()
        self._jira_checks()
        self._check_source_branch_still_exists()

        integration_branches = self._create_integration_branches(
            self._pr.source_branch)

        if self.use_queue and self._already_in_queue(integration_branches):
            self.handle_merge_queues()

        in_sync = self._check_in_sync(integration_branches)

        try:
            self._update_integration(integration_branches)
        except:
            raise
        else:
            if self.use_queue and in_sync:
                # In queue mode, in case no conflict is detected,
                # we want to keep the integration branches as they are,
                # hense reset branches to avoid a push later in the code
                for branch in integration_branches:
                    branch.reset()
        finally:
            self._push(integration_branches)

        child_prs = self._create_pull_requests(integration_branches)

        self._check_pull_request_skew(integration_branches, child_prs)
        self._check_approvals()
        self._check_build_status(child_prs)

        if self.interactive and not confirm('Do you want to merge/queue?'):
            return

        # If the integration pull requests were already in sync with the
        # feature branch before our last update (which serves as a final
        # check for conflicts), and all builds were green, and we reached
        # this point without an error, then all conditions are met to enter
        # the queue.
        if self.use_queue:
            # validate current state of queues
            try:
                self._validate_queues(self._cascade)
            except IncoherentQueues:
                raise QueueOutOfOrder(
                    active_options=self._get_active_options())
            # Enter the merge queue!
            self._add_to_queue(integration_branches)
            self._validate_repo()
            raise Queued(
                branches=self._cascade.destination_branches,
                ignored=self._cascade.ignored_branches,
                issue=self._pr.source_branch.jira_issue_key,
                author=self._pr.author_display_name,
                active_options=self._get_active_options())

        else:
            self._merge(integration_branches)
            add_merged_pr(self._pr.bb_pr.id)
            self._validate_repo()
            raise SuccessMessage(
                branches=self._cascade.destination_branches,
                ignored=self._cascade.ignored_branches,
                issue=self._pr.source_branch.jira_issue_key,
                author=self._pr.author_display_name,
                active_options=self._get_active_options())


def update_queue_status(queue_collection):
    """Set the inspectable merge queue status.

    It consists in an ordereddict on the form:

        {
            PR_ID: [(VERSION, SHA1), (VERSION, SHA1), ...]
            ...
        }

    It is ordered by PR queuing date (the most recently queued PR last).
    The lists are ordered by target version number (the most recent version
    first).

    """
    queues = queue_collection._queues
    qib = QueueIntegrationBranch
    status = OrderedDict()
    # initialize status dict
    for branch in reversed(queues[list(queues.keys())[-1]][qib]):
        status[branch.pr_id] = []

    for version, queue in reversed(queues.items()):
        for branch in queue[qib]:
            status[branch.pr_id].append((version, branch.get_latest_commit()))

    STATUS['merge queue'] = status


def add_merged_pr(pr_id):
    """Add pr_id to the list of merged pull requests.

    This list is an inspectable dequeue containing the last 10 merged pull
    requests' IDs.

    """
    merged_prs = STATUS.setdefault('merged PRs', deque(maxlen=10))
    merged_prs.append({'id': pr_id, 'merge_time': datetime.now()})


def setup_parser():
    parser = argparse.ArgumentParser(add_help=True,
                                     description='Merges bitbucket '
                                                 'pull requests.')
    parser.add_argument(
        'settings',
        help="Path to project settings file")
    parser.add_argument(
        'bitbucket_password',
        help="Robot Bitbucket password")
    parser.add_argument(
        'jira_password',
        help="Robot Jira password")
    parser.add_argument(
        'token', type=str,
        help="The ID of the pull request or sha1 (%s characters) "
             "to analyse" % SHA1_LENGHT)
    parser.add_argument(
        '--disable-queues', action='store_true', default=False,
        help="Deactivate optimistic merge queue (legacy mode)")
    parser.add_argument(
        '--option', '-o', action='append', type=str, dest='cmd_line_options',
        help="Activate additional options")
    parser.add_argument(
        '--interactive', action='store_true', default=False,
        help="Ask before merging or sending comments")
    parser.add_argument(
        '--no-comment', action='store_true', default=False,
        help="Do not add any comment to the pull request page")
    parser.add_argument(
        '-v', action='store_true', dest='verbose', default=False,
        help="Verbose mode")
    parser.add_argument(
        '--backtrace', action='store_true', default=False,
        help="Show backtrace instead of return code on console")
    parser.add_argument(
        '--quiet', action='store_true', default=False,
        help="Don't print return codes on the console")

    return parser


def setup_options(args):
    options = {
        'after_pull_request':
            Option(privileged=False,
                   value=False,  # not supported from command line
                   help="Wait for the given pull request id to be merged "
                        "before continuing with the current one"),
        'bypass_author_approval':
            Option(privileged=True,
                   value='bypass_author_approval' in args.cmd_line_options,
                   help="Bypass the pull request author's approval"),
        'bypass_build_status':
            Option(privileged=True,
                   value='bypass_build_status' in args.cmd_line_options,
                   help="Bypass the build and test status"),
        'bypass_commit_size':
            Option(privileged=True,
                   value='bypass_commit_size' in args.cmd_line_options,
                   help='Bypass the check on the size of the changeset '
                        '```TBA```'),
        'bypass_incompatible_branch':
            Option(privileged=True,
                   value='bypass_incompatible_branch' in args.cmd_line_options,
                   help="Bypass the check on the source branch prefix"),
        'bypass_jira_check':
            Option(privileged=True,
                   value='bypass_jira_check' in args.cmd_line_options,
                   help="Bypass the Jira issue check"),
        'bypass_peer_approval':
            Option(privileged=True,
                   value='bypass_peer_approval' in args.cmd_line_options,
                   help="Bypass the pull request peer's approval"),
        'bypass_tester_approval':
            Option(privileged=True,
                   value='bypass_tester_approval' in args.cmd_line_options,
                   help="Bypass the pull request tester's approval"),
        'unanimity':
            Option(privileged=False,
                   value='unanimity' in args.cmd_line_options,
                   help="Change review acceptance criteria from "
                        "`one reviewer at least` to `all reviewers` "),
        'wait':
            Option(privileged=False,
                   value='wait' in args.cmd_line_options,
                   help="Instruct Bert-E not to run until further notice")
    }
    return options


def setup_commands():
    commands = {
        'help':
            Command(privileged=False,
                    handler='print_help',
                    help='print Bert-E\'s manual in the pull-request'),
        'status':
            Command(privileged=False,
                    handler='publish_status_report',
                    help='print Bert-E\'s current status in '
                         'the pull-request ```TBA```'),
        'build':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='re-start a fresh build ```TBA```'),
        'retry':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='re-start a fresh build ```TBA```'),
        'clear':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='remove all comments from Bert-E from the '
                         'history ```TBA```'),
        'reset':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='delete integration branches, integration pull '
                         'requests, and restart merge process from the '
                         'beginning ```TBA```')
    }
    return commands


def setup_settings(settings_file):
    settings = dict(DEFAULT_OPTIONAL_SETTINGS)

    if not exists(settings_file):
        raise SettingsFileNotFound(settings_file)

    with open(settings_file, 'r') as f:
        try:
            # read the yaml data as pure string (no conversion)
            new_settings = yaml.load(f, Loader=yaml.BaseLoader)
        except Exception:
            raise IncorrectSettingsFile(settings_file)

    # replace default data by provided data
    for key in new_settings:
        settings[key] = new_settings[key]

    # check settings type and presence
    for setting_ in ['repository_owner', 'repository_slug',
                     'robot_username', 'robot_email', 'build_key',
                     'jira_account_url', 'jira_username',
                     'pull_request_base_url', 'commit_base_url']:
        if setting_ not in settings:
            raise MissingMandatorySetting(settings_file)

        if not isinstance(settings[setting_], str):
            raise IncorrectSettingsFile(settings_file)

    try:
        settings['required_peer_approvals'] = int(
            settings['required_peer_approvals'])
    except ValueError:
        raise IncorrectSettingsFile(settings_file)

    for setting_ in ['prefixes']:
        if not isinstance(settings[setting_], dict):
            raise IncorrectSettingsFile(settings_file)

    for setting_ in ['jira_keys', 'admins', 'tasks']:
        if not isinstance(settings[setting_], list):
            raise IncorrectSettingsFile(settings_file)

        for data in settings[setting_]:
            if not isinstance(data, str):
                raise IncorrectSettingsFile(settings_file)

    return settings


def main():
    parser = setup_parser()
    args = parser.parse_args()
    if not args.cmd_line_options:
        args.cmd_line_options = []

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        # request lib is noisy
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.WARNING)
        requests_log.propagate = True

    options = setup_options(args)
    commands = setup_commands()
    settings = setup_settings(args.settings)

    bert_e = BertE(args, options, commands, settings)
    try:
        return bert_e.handler()
    finally:
        bert_e.repo.delete()
        assert not exists(bert_e.tmpdir), (
            "temporary workdir '%s' wasn't deleted!" % bert_e.tmpdir)


if __name__ == '__main__':
    main()
