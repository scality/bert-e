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
"""This module holds the implementation of various special-role git branches
defined by GitWaterFlow.

"""
import logging
import re
from collections import OrderedDict
from copy import deepcopy
from functools import cmp_to_key
from functools import total_ordering

from bert_e import exceptions as errors
from bert_e.lib import git
from bert_e.lib.template_loader import render

LOG = logging.getLogger(__name__)


def _compare_version_component(version1, version2, component_index):
    """
    Helper method to compare version components at a specific level.

    Args:
        version1, version2: Version tuples to compare
        component_index: Index of the component to compare
        (0 for major, 1 for minor, 2 for micro)

    Returns:
        int: -1 if version1 < version2, 1 if version1 > version2,
        0 if equal or both missing
        None: if comparison should continue to next level
    """
    len1 = len(version1)
    len2 = len(version2)

    # Both have the component - compare them
    if len1 > component_index and len2 > component_index:
        comp1 = version1[component_index]
        comp2 = version2[component_index]
        if comp1 != comp2:
            return comp1 - comp2
        return None  # Equal, continue to next level

    # Only one has the component
    elif len1 > component_index and len2 <= component_index:
        # version1 has component, version2 doesn't
        # -> version1 comes first in the cascade
        return -1
    elif len1 <= component_index and len2 > component_index:
        # version2 has component, version1 doesn't
        # -> version2 comes first in the cascade
        return 1

    # Neither has the component at this level
    return None


def compare_branches(branch1, branch2):
    """
    Compare GitWaterflow branches for sorting.
    For cascade ordering, we want: 4.3 < 4 < 5.1 < 10.0 < 10
    Specific minor versions come before major-only branches within
    the same major.
    """
    # Safely extract version components
    version1 = branch1[0]
    version2 = branch2[0]

    # Compare major versions first using helper
    major_result = _compare_version_component(version1, version2, 0)
    if major_result is not None:
        return major_result

    # Same major version - check if one is major-only vs major.minor
    # Major-only branches have None as minor version, e.g., (4, None)
    # Major.minor branches have integer minor version, e.g., (4, 3)
    is_major_only_1 = len(version1) >= 2 and version1[1] is None
    is_major_only_2 = len(version2) >= 2 and version2[1] is None

    if is_major_only_1 and not is_major_only_2:
        # version1 is major-only, version2 is major.minor
        # major-only comes after
        return 1
    elif not is_major_only_1 and is_major_only_2:
        # version1 is major.minor, version2 is major-only
        # major.minor comes before
        return -1

    # Compare remaining version components (minor, micro) using helper
    for level in range(1, 3):  # 1=minor, 2=micro
        result = _compare_version_component(version1, version2, level)
        if result is not None:
            return result

    return 0


def compare_queues(version1, version2):
    # Compare queues using standard branch comparison
    return compare_branches(version1, version2)


class GWFBranch(git.Branch):
    pattern = r'(?P<prefix>[a-z]+)/(?P<label>.+)'
    major = 0
    minor = 0
    micro = -1  # is incremented always, first version is 0
    hfrev = -1
    cascade_producer = False
    cascade_consumer = False
    can_be_destination = False
    allow_ticketless_pr = False

    def __init__(self, repo, name):
        super().__init__(repo, name)
        match = re.match(self.pattern, name)
        if not match:
            raise errors.BranchNameInvalid(name)
        for key, value in match.groupdict().items():
            if (key in ('major', 'minor', 'micro', 'hfrev', 'pr_id') and
                    value is not None):
                value = int(value)
            self.__setattr__(key, value)

    def __str__(self):
        return self.name

    @property
    def version_t(self):
        if self.micro is not None:
            if self.hfrev is not None:
                return (self.major, self.minor, self.micro, self.hfrev)
            return (self.major, self.minor, self.micro)

        return (self.major, self.minor)


class LegacyHotfixBranch(GWFBranch):
    pattern = r'^hotfix/(?P<label>.+)$'


class UserBranch(GWFBranch):
    pattern = r'^user/(?P<label>.+)$'


class ReleaseBranch(GWFBranch):
    pattern = r'^release/' \
              r'(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'


class FeatureBranch(GWFBranch):
    all_prefixes = ('improvement', 'bugfix', 'feature', 'project',
                    'documentation', 'design', 'dependabot', 'epic',
                    'bug')
    jira_issue_pattern = '(?P<jira_project>[a-zA-Z0-9_]+)-[0-9]+'
    prefixes = '(?P<prefix>(%s))' % '|'.join(all_prefixes)
    pattern = "^(?P<feature_branch>%s/(?P<label>(?P<jira_issue_key>%s)?" \
              "(?(jira_issue_key).*|.+)))$" % (prefixes, jira_issue_pattern)
    cascade_producer = True

    def __init__(self, repo, name):
        super().__init__(repo, name)
        if self.jira_issue_key:
            self.jira_issue_key = self.jira_issue_key.upper()
        if self.jira_project:
            self.jira_project = self.jira_project.upper()


@total_ordering
class HotfixBranch(GWFBranch):
    pattern = r'^hotfix/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              r'\.(?P<micro>\d+))$'
    cascade_producer = False
    cascade_consumer = True
    can_be_destination = True
    allow_prefixes = FeatureBranch.all_prefixes

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.major == other.major and
                self.minor == other.minor and
                self.micro == other.micro and
                self.hfrev == other.hfrev)

    def __lt__(self, other):
        return (self.__class__ == other.__class__ and
                (self.major < other.major or
                 (self.major == other.major and
                  self.minor < other.minor) or
                 (self.major == other.major and
                  self.minor == other.minor and
                  self.micro < other.micro) or
                 (self.major == other.major and
                  self.minor == other.minor and
                  self.micro == other.micro and
                  self.hfrev < other.hfrev)))

    @property
    def version_t(self):
        return (self.major, self.minor, self.micro, self.hfrev)


@total_ordering
class DevelopmentBranch(GWFBranch):
    pattern = (r'^development/(?P<version>(?P<major>\d+)'
               r'(\.(?P<minor>\d+))?(\.(?P<micro>\d+))?)$')
    cascade_producer = True
    cascade_consumer = True
    can_be_destination = True
    allow_prefixes = FeatureBranch.all_prefixes
    latest_minor = -1

    def __init__(self, repo, name):
        super().__init__(repo, name)
        # The regex match is already done in parent GWFBranch.__init__
        # self.major, self.minor are already set by parent, add micro handling

        # Handle micro version - it will be None if not present
        if not hasattr(self, 'micro') or self.micro is None:
            self.micro = None  # Keep as None for x.y format branches

        # Update version property to include micro when present
        if self.micro is not None:
            self.version = f"{self.major}.{self.minor}.{self.micro}"
        elif self.minor is not None:
            self.version = f"{self.major}.{self.minor}"
        else:
            self.version = f"{self.major}"

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.major == other.major and
                self.minor == other.minor and
                getattr(self, 'micro', None) == getattr(other, 'micro', None))

    def __lt__(self, other):
        if self.__class__ != other.__class__:
            return NotImplemented

        # Major version comparison
        if self.major != other.major:
            return self.major < other.major

        if self.minor is None:
            # development/<major> is greater than development/<major>.<minor>
            return False
        # Same major version - apply cascade rules
        if self.minor is not None and other.minor is None:
            return True

        # Both have minor versions
        if self.minor != other.minor:
            return self.minor < other.minor

    @property
    def has_minor(self) -> bool:
        return self.minor is not None

    @property
    def version_t(self):
        if getattr(self, 'micro', None) is not None:
            return (self.major, self.minor, self.micro)
        elif self.minor is not None:
            return (self.major, self.minor)
        else:
            return (self.major, None)


class IntegrationBranch(GWFBranch):
    pattern = r'^w/(?P<version>(?P<major>\d+)(\.(?P<minor>\d+))?' \
              r'(\.(?P<micro>\d+)(\.(?P<hfrev>\d+))?)?)/' + \
              FeatureBranch.pattern[1:]
    dst_branch = ''
    feature_branch = ''

    def get_pull_request_from_list(self, open_prs):
        for pr in open_prs:
            if pr.src_branch != self.name:
                continue
            if self.dst_branch and \
                    pr.dst_branch != \
                    self.dst_branch.name:
                continue
            return pr

    def get_or_create_pull_request(self, parent_pr, open_prs, bitbucket_repo):
        title = 'INTEGRATION [PR#%s > %s] %s' % (
            parent_pr.id, self.dst_branch.name, parent_pr.title
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
                                 branch=self.name)
            pr = bitbucket_repo.create_pull_request(
                title=title,
                name='name',
                src_branch=self.name,
                dst_branch=self.dst_branch.name,
                close_source_branch=True,
                description=description)
            created = True
        return pr, created

    def remove(self, do_push=False):
        # make sure we are not on the branch to remove
        self.dst_branch.checkout()
        super().remove(do_push=do_push)


class GhostIntegrationBranch(IntegrationBranch):
    pattern = FeatureBranch.pattern

    def __init__(self, repo, name, dst_branch):
        self.version = dst_branch.version
        self.major = dst_branch.major
        self.minor = dst_branch.minor
        super().__init__(repo, name)

    def get_or_create_pull_request(self, parent_pr, open_prs, bitbucket_repo):
        return self.get_pull_request_from_list(open_prs), False

    def remove(self, do_push=False):
        pass  # Never delete the source branch


class QueueBranch(GWFBranch):
    pattern = r'^q/(?P<version>(?P<major>\d+)(\.(?P<minor>\d+))?' \
              r'(\.(?P<micro>\d+)(\.(?P<hfrev>\d+))?)?)$'
    dst_branch = ''

    def __init__(self, repo, name):
        super(QueueBranch, self).__init__(repo, name)
        if self.hfrev is not None:
            dest = branch_factory(repo, 'hotfix/%d.%d.%d' % (self.major,
                                  self.minor, self.micro))
        else:
            dest = branch_factory(repo, 'development/%s' % self.version)
        self.dst_branch = dest

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.name == other.name


@total_ordering
class QueueIntegrationBranch(GWFBranch):
    pattern = r'^q/w/(?P<pr_id>\d+)/' + IntegrationBranch.pattern[3:]

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.name == other.name

    def __lt__(self, other):
        return self.__class__ == other.__class__ and \
            other.includes_commit(self)


class QueueCollection(object):
    """Manipulate and analyse all active queues in the repository."""

    def __init__(self, bbrepo, build_key, merge_paths, force_merge):
        self.bbrepo = bbrepo
        self.build_key = build_key
        self.merge_paths = merge_paths
        self.force_merge = force_merge
        self._queues = OrderedDict()
        self._mergeable_queues = None
        self._mergeable_prs = []
        self._validated = False

    def build(self, repo):
        """Collect q branches from repository, add them to the collection."""
        cmd = 'git branch -r --list origin/q/*'
        for branch in repo.cmd(cmd).split('\n')[:-1]:
            match_ = re.match(r'\s*origin/(?P<name>.*)', branch)
            if not match_:
                continue
            try:
                branch = branch_factory(repo, match_.group('name'))
            except errors.UnrecognizedBranchPattern:
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
            raise errors.InvalidQueueBranch(branch)
        self._validated = False
        # make sure we have a local copy of the branch
        # (enables get_latest_commit)
        branch.checkout()
        version = branch.version_t
        if version not in self._queues.keys():
            self._queues[version] = {
                QueueBranch: None,
                QueueIntegrationBranch: []
            }
            # Sort the top dict again
            self._queues = OrderedDict(sorted(self._queues.items(),
                                              key=cmp_to_key(compare_queues)))

        if isinstance(branch, QueueBranch):
            self._queues[version][QueueBranch] = branch
        else:
            self._queues[version][QueueIntegrationBranch].append(branch)

    def _horizontal_validation(self, version):
        """Validation of the queue collection on one given version.

        Called by validate().

        """
        masterq = self._queues[version][QueueBranch]
        # check master queue state
        if not masterq:
            yield errors.MasterQueueMissing(version)
        else:
            if not masterq.includes_commit(masterq.dst_branch):
                yield errors.MasterQueueLateVsDev(masterq, masterq.dst_branch)

            if not self._queues[version][QueueIntegrationBranch]:
                # check master queue points to dev
                if (masterq.get_latest_commit() !=
                        masterq.dst_branch.get_latest_commit()):
                    yield errors.MasterQueueNotInSync(masterq,
                                                      masterq.dst_branch)
            else:
                # check state of master queue wrt to greatest integration
                # queue
                greatest_intq = (
                    self._queues[version][QueueIntegrationBranch][0]
                )
                if (greatest_intq.get_latest_commit() !=
                        masterq.get_latest_commit()):
                    if greatest_intq.includes_commit(masterq):
                        yield errors.MasterQueueLateVsInt(masterq,
                                                          greatest_intq)

                    elif masterq.includes_commit(greatest_intq):
                        yield errors.MasterQueueYoungerThanInt(masterq,
                                                               greatest_intq)

                    else:
                        yield errors.MasterQueueDiverged(masterq,
                                                         greatest_intq)

            # check each integration queue contains the previous one
            nextq = masterq
            for intq in self._queues[version][QueueIntegrationBranch]:
                if not nextq.includes_commit(intq):
                    yield errors.QueueInclusionIssue(nextq, intq)
                nextq = intq
            if not nextq.includes_commit(masterq.dst_branch):
                yield errors.QueueInclusionIssue(nextq, masterq.dst_branch)

    def _vertical_validation(self, stack, versions):
        """Validation of the queue collection on one given merge path.

        Called by validate().

        """
        prs = self._extract_pr_ids(stack)
        last_version = versions[-1]

        hf_detected = False
        if len(list(stack.keys())) == 1:
            if len(list(stack.keys())[0]) == 4:
                hf_detected = True

        # check all subsequent versions have a master queue
        has_queues = False
        for version in versions:
            if version not in stack:
                if has_queues and not hf_detected:
                    yield errors.MasterQueueMissing(version)
                continue
            has_queues = True
            if not stack[version][QueueBranch]:
                yield errors.MasterQueueMissing(version)

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
                    if len(version) == 4:
                        # skip hf from check loop
                        continue
                    if (stack[version][QueueIntegrationBranch] and
                            stack[version][QueueIntegrationBranch][0].pr_id ==
                            pr):
                        vqint = stack[version][QueueIntegrationBranch].pop(0)
                        # take this opportunity to check vertical inclusion
                        if not next_vqint.includes_commit(vqint):
                            yield errors.QueueInclusionIssue(next_vqint, vqint)
                        next_vqint = vqint
                    else:
                        # this pr is supposedly entirely removed from the stack
                        # if it comes back again, its an error
                        break
                prs.remove(pr)

            # skip hf from stack and prs before final checks
            for version in versions:
                if len(version) == 4:
                    if version not in stack:
                        continue
                    while stack[version][QueueIntegrationBranch]:
                        pr_id = stack[version][QueueIntegrationBranch][0].pr_id
                        stack[version][QueueIntegrationBranch].pop(0)
                        if pr_id in prs:
                            prs.remove(pr_id)

            if prs:
                # after this algorithm prs should be empty
                yield errors.QueueInconsistentPullRequestsOrder()
            else:
                # and stack should be empty too
                for version in versions:
                    if (version in stack and
                            stack[version][QueueIntegrationBranch]):
                        yield errors.QueueInconsistentPullRequestsOrder()

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
        errs = []
        versions = self._queues.keys()

        if not versions:
            # no queues, cool stuff
            self._validated = True
            return

        for version in versions:
            errs.extend(self._horizontal_validation(version))

        for merge_path in self.merge_paths:
            versions = [branch.version_t for branch in merge_path]
            stack = deepcopy(self._queues)
            # remove versions not on this merge_path from consideration
            for version in list(stack.keys()):
                if version not in versions:
                    stack.pop(version)

            errs.extend(self._vertical_validation(stack, versions))

        if errs:
            raise errors.IncoherentQueues(errs)

        self._validated = True

    @property
    def failed_prs(self):
        """Return a list PRs in which the build have failed in the queue."""
        if not self._validated:
            raise errors.QueuesNotValidated()

        failed = []
        for version in self._queues.keys():
            qint = self._queues[version][QueueIntegrationBranch]
            if qint:
                qint = qint[0]
                status = self.bbrepo.get_build_status(
                    qint.get_latest_commit(),
                    self.build_key
                )
                if status == 'FAILED':
                    failed.append(qint.pr_id)
        return failed

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
            if all([inq.pr_id != first_failed_pr for inq in intqs]):
                # do not pop anything if failed pr is not on the current path
                continue

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
        prs_hf = []
        prs = []
        # identify version corresponding to last dev queue
        # (i.e. ignore stab queues)
        greatest_dev = None
        for version in reversed(queues.keys()):
            if len(version) == 2 and greatest_dev is None:
                greatest_dev = version
            if len(version) == 4:
                # we may not catch the hf pr_id later from greatest_dev
                # so insert them now
                for qint in queues[version][QueueIntegrationBranch]:
                    if qint.pr_id not in prs_hf:
                        prs_hf.insert(0, qint.pr_id)

        if greatest_dev:
            for qint in queues[greatest_dev][QueueIntegrationBranch]:
                if qint.pr_id not in prs_hf + prs:
                    prs.insert(0, qint.pr_id)

        return prs_hf + prs

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
            raise errors.QueuesNotValidated()

        mergeable_prs = self._extract_pr_ids(self._queues)

        if not self.force_merge:
            for merge_path in self.merge_paths:
                versions = [branch.version_t for branch in merge_path]
                stack = deepcopy(self._queues)
                # remove versions not on this merge_path from consideration
                for version in list(stack.keys()):
                    # exclude hf version from this pop process
                    if version not in versions and len(version) < 4:
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

    @property
    def queued_prs(self):
        """Ordered list of queued PR IDs (oldest first)."""
        if not self._queues:
            return []

        # Find last_entry for which there is not a hf entry
        last_entry = None
        pr_ids = []
        for key in list(reversed(self._queues.keys())):
            if len(key) < 4:
                last_entry = self._queues[key]
                break

        if last_entry is not None:
            pr_ids = list(reversed([branch.pr_id for branch in
                                    last_entry[QueueIntegrationBranch]]))

        # Add hotfix PRs that are not seen from the queues top key
        pr_hf_ids = []
        for key in list(reversed(self._queues.keys())):
            if len(key) == 4:
                entry = self._queues[key]
                new_pr_ids = list([branch.pr_id for branch in
                                   entry[QueueIntegrationBranch]])
                for pr_hf_id in new_pr_ids:
                    if pr_hf_id not in pr_hf_ids:
                        pr_hf_ids = [pr_hf_id] + pr_hf_ids

        # Remove hotfix PRs from the first set
        pr_non_hf_ids = []
        for pr_id in pr_ids:
            if pr_id not in pr_hf_ids:
                pr_non_hf_ids = pr_non_hf_ids + [pr_id]

        return pr_hf_ids + pr_non_hf_ids

    def has_version_queued_prs(self, version):
        # delete_branch() may call this property with a four numbers version
        # finished by -1, so we can not rely on this last number to match.
        if len(version) == 4 and version[3] == -1:
            for queue_version in self._queues.keys():
                if len(queue_version) == 4 and \
                   len(version) == 4 and \
                   queue_version[:3] == version[:3]:
                    queued_pr = self._queues.get(queue_version)
                    if queued_pr is not None and \
                       queued_pr.get(QueueIntegrationBranch) is not None:
                        return True
            return False
        # classic test otherwise
        return (self._queues.get(version, {}).get(QueueIntegrationBranch)
                is not None)

    def delete(self):
        """Delete the queues entirely."""

        for branch in self._queues.values():
            queue: QueueBranch = branch[QueueBranch]
            queue.dst_branch.checkout()
            queue.remove(do_push=True)
            queue_integration: QueueIntegrationBranch | None = branch.get(
                QueueIntegrationBranch)
            if queue_integration:
                queue_integration.remove(do_push=True)


class BranchCascade(object):
    def __init__(self):
        self._cascade = OrderedDict()
        self.dst_branches = []  # store branches
        self.ignored_branches = []  # store branch names (easier sort)
        self.target_versions = []
        self._merge_paths = []

    def build(self, repo, dst_branch=None):
        flat_branches = set()
        for prefix in ['development', 'hotfix']:
            cmd = 'git branch -a --list *%s/*' % prefix
            for branch in repo.cmd(cmd).split('\n')[:-1]:
                match_ = re.match(r'\*?\s*(remotes/origin/)?(?P<name>.*)',
                                  branch)
                if match_:
                    flat_branches.add(match_.group('name'))
        for flat_branch in flat_branches:
            try:
                branch = branch_factory(repo, flat_branch)
            except errors.UnrecognizedBranchPattern:
                continue
            self.add_branch(branch, dst_branch)

        for tag in repo.cmd('git tag').split('\n')[:-1]:
            self.update_versions(tag)

        # Re-sort the cascade after update_versions may have changed keys
        self._cascade = OrderedDict(
            sorted(self._cascade.items(), key=cmp_to_key(compare_branches))
        )
        self._update_major_versions()
        if dst_branch:
            self.finalize(dst_branch)

    def get_merge_paths(self):
        """Return the dict of all greatest merge paths.

        The items in the list correspond to:
        - the path (list of branches) from the oldest dev
            branch to the newest dev branch

        This is used by QueueCollection to check the integrity of queues.

        It is not required to finalize the cascade to extract this
        information, a simple call to build is enough.

        """
        if self._merge_paths:
            return self._merge_paths

        ret = [[]]
        for branches in self._cascade.values():
            if branches[DevelopmentBranch]:
                if branches[HotfixBranch]:
                    # create a new path starting from this hotfix
                    ret.append([branches[HotfixBranch]])
                # append this version to all paths
                for path in ret:
                    path.append(branches[DevelopmentBranch])
        self._merge_paths = ret
        return ret

    def add_branch(self, branch, dst_branch=None):
        if not branch.can_be_destination:
            LOG.debug("Discard non destination branch: %s", branch)
            return

        if branch.__class__ is HotfixBranch:
            if dst_branch and \
               dst_branch.__class__ is HotfixBranch:
                if branch.major != dst_branch.major or \
                   branch.minor != dst_branch.minor or \
                   branch.micro != dst_branch.micro:
                    # this is not the hotfix branch we want to add
                    return
            else:
                return

        # Create key based on full version tuple
        key = branch.version_t

        if key not in self._cascade.keys():
            self._cascade[key] = {
                DevelopmentBranch: None,
                HotfixBranch: None,
            }
            # Sort the cascade again using updated comparison
            self._cascade = OrderedDict(
                sorted(self._cascade.items(), key=cmp_to_key(compare_branches))
            )

        self._cascade[key][branch.__class__] = branch

    def update_versions(self, tag):
        """Update expected versions based on repository tags."""
        pattern = r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+)" \
                  r"(\.(?P<hfrev>\d+)|)$"
        match = re.match(pattern, tag)
        if not match:
            LOG.debug("Ignore tag: %s", tag)
            return
        LOG.debug("Consider tag: %s", tag)
        major = int(match.groupdict()['major'])
        minor = int(match.groupdict()['minor'])
        micro = int(match.groupdict()['micro'])
        hfrev = 0  # default hfrev
        if match.groupdict()['hfrev'] is not None:
            hfrev = int(match.groupdict()['hfrev'])

        # Look for branches that match this version
        # Check for exact (major, minor) match and major-only match
        branches = self._cascade.get((major, minor), {})
        major_branches = self._cascade.get((major, None), {})
        micro_branches = self._cascade.get((major, minor, micro), {})

        # Also look for hotfix branches with matching major.minor.micro
        hf_branch = None
        for key, branch_set in self._cascade.items():
            if (len(key) >= 3 and key[0] == major and key[1] == minor and
                    key[2] == micro and branch_set.get(HotfixBranch)):
                hf_branch = branch_set[HotfixBranch]
                break

        if not branches and not major_branches and not hf_branch:
            LOG.debug("Ignore tag: %s", tag)
            return

        # If we didn't find hf_branch above, check in branches
        if not hf_branch:
            hf_branch = branches.get(HotfixBranch)
        dev_branch: DevelopmentBranch = branches.get(DevelopmentBranch)
        major_branch: DevelopmentBranch = major_branches.get(DevelopmentBranch)
        micro_branch: DevelopmentBranch = micro_branches.get(DevelopmentBranch)

        if hf_branch:
            if hf_branch.micro == micro:
                hf_branch.hfrev = max(hfrev + 1, hf_branch.hfrev)
                hf_branch.version = '%d.%d.%d.%d' % (hf_branch.major,
                                                     hf_branch.minor,
                                                     hf_branch.micro,
                                                     hf_branch.hfrev)

        if micro_branch is not None and \
           ([micro_branch.major, micro_branch.minor,
             micro_branch.micro] == [major, minor, micro]):
            raise errors.ReleaseAlreadyExists(micro_branch, tag)

        if dev_branch:
            # Only update if tag matches X.Y
            # And is not a three-digit dev branch

            if dev_branch.major == major and dev_branch.minor == minor:
                # Exclude tags whose micro is already
                # A three-digit dev branch for this X.Y
                three_digit_keys = [
                    k for k in self._cascade.keys()
                    if len(k) == 3 and k[0] == major and k[1] == minor
                ]

                three_digit_micros = set(k[2] for k in three_digit_keys)
                next_micro = micro + 1
                while next_micro in three_digit_micros:
                    next_micro += 1
                if (not hasattr(dev_branch, '_next_micro') or
                        dev_branch._next_micro is None):
                    dev_branch._next_micro = next_micro
                else:
                    dev_branch._next_micro = max(
                        next_micro,
                        dev_branch._next_micro
                    )
        if major_branch:
            major_branch.latest_minor = max(
                minor,
                major_branch.latest_minor
            )

        # Re-sort the cascade after any key changes
        self._cascade = OrderedDict(
            sorted(
                self._cascade.items(),
                key=cmp_to_key(compare_branches)
            )
        )

    def validate(self):
        previous_dev_branch = None
        for key, branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            hf_branch = branch_set[HotfixBranch]

            if dev_branch is None and \
               hf_branch is not None:
                # skip cascade validation for hf
                continue

            if previous_dev_branch:
                if not dev_branch.includes_commit(previous_dev_branch):
                    raise errors.DevBranchesNotSelfContained(
                        previous_dev_branch, dev_branch)

            previous_dev_branch = dev_branch

    def _update_major_versions(self):
        """
        For every major dev branch, ensure the latest minor is set.
        This function is used on the case where we have a
        dev/1 and dev/1.0 branch but no 1.0.0 tag.
        In this case, when expecting the next version for dev/1
        we should return 1.1.0 instead of 1.0.0.
        """
        for version_tuple, branch_set in self._cascade.items():
            # Only process major-only branches (tuples where minor is None)
            if len(version_tuple) < 2:
                continue
            if len(version_tuple) == 2 and version_tuple[1] is None:
                major_branch: DevelopmentBranch = branch_set[DevelopmentBranch]
                major = version_tuple[0]

                # Find all minor versions for this major
                minors = [
                    version_tuple[1] for version_tuple in self._cascade.keys()
                    if (len(version_tuple) >= 2 and
                        version_tuple[0] == major and
                        version_tuple[1] is not None)
                ]
                minors.append(major_branch.latest_minor)

                major_branch.latest_minor = max(minors)
            elif len(version_tuple) == 2 and version_tuple[1] is not None:
                minor_branch: DevelopmentBranch = branch_set[DevelopmentBranch]
                minor = version_tuple[1]
                major = version_tuple[0]

                # Find all micros versions for this minor
                micros = [
                    version_tuple[2] for version_tuple in self._cascade.keys()
                    if (len(version_tuple) >= 3 and
                        version_tuple[0] == major and
                        version_tuple[1] == minor and
                        version_tuple[2] is not None)
                ]
                if micros:
                    minor_branch.latest_micro = max(micros)

    def _set_target_versions(self, dst_branch):
        """Compute list of expected Jira FixVersion/s.

        Must be called after the cascade has been finalised.
        """
        # Clear any existing target versions to avoid duplicates
        self.target_versions = []
        for key, branch_set in self._cascade.items():
            dev_branch: DevelopmentBranch = branch_set[DevelopmentBranch]
            hf_branch: HotfixBranch = branch_set[HotfixBranch]

            if hf_branch and dst_branch.name.startswith('hotfix/'):
                self.target_versions.append(
                    '%d.%d.%d.%d' % (
                        hf_branch.major, hf_branch.minor, hf_branch.micro,
                        hf_branch.hfrev
                    )
                )
            if dev_branch:
                # Development branches with major.minor naming
                if dev_branch.has_minor:
                    # Use the tracked next micro version if available,
                    # otherwise use the micro+1 if this is a three-digit branch
                    if (hasattr(dev_branch, '_next_micro') and
                            dev_branch._next_micro is not None):
                        next_micro = dev_branch._next_micro
                    elif getattr(dev_branch, 'micro', None) is not None:
                        version_current = '%d.%d.%d' % (
                            dev_branch.major, dev_branch.minor,
                            dev_branch.micro)
                        self.target_versions.append(version_current)
                        next_micro = dev_branch.micro
                    else:
                        if hasattr(dev_branch, 'latest_micro'):
                            next_micro = dev_branch.latest_micro + 1
                        else:
                            next_micro = 0
                    version_str = '%d.%d.%d' % (
                        dev_branch.major, dev_branch.minor, next_micro
                    )
                    if version_str not in self.target_versions:
                        self.target_versions.append(version_str)

                else:
                    # For development/x branches, use latest_minor logic
                    # Target should be X.(latest_minor+1).0,
                    # not X.(latest_minor+1).1
                    self.target_versions.append(
                        f"{dev_branch.major}."
                        f"{dev_branch.latest_minor + 1}."
                        f"0"
                    )

    def finalize(self, dst_branch):
        """
        Finalize cascade considering given destination.

        Assumes the cascade has been populated by calls to add_branch
        and update_versions. The local lists keeping track
        Args:
            dst_branch: where the pull request wants to merge

        Raises:

        Returns:
            list: list of destination branches
            list: list of ignored destination branches

        """
        self.get_merge_paths()  # populate merge paths before removing data
        dst_hf = dst_branch.name.startswith('hotfix/')

        # First: Find the destination branch key if it's a development branch
        dst_branch_key = None
        if not dst_hf:
            for key, branch_set in self._cascade.items():
                dev_branch = branch_set[DevelopmentBranch]
                if dev_branch and dev_branch.name == dst_branch.name:
                    dst_branch_key = key
                    break

        # Process all branches
        for key, branch_set in list(self._cascade.items()):
            dev_branch = branch_set[DevelopmentBranch]
            hf_branch = branch_set[HotfixBranch]

            # Handle development branches
            if dev_branch:
                if not dst_hf:
                    # For dev destinations, include branches
                    # with version >= destination version
                    # Special handling for major-only vs major.minor branches
                    key_major = key[0]
                    key_minor = key[1] if len(key) > 1 else None
                    dst_major = dst_branch_key[0]
                    dst_minor = (dst_branch_key[1] if len(dst_branch_key) > 1
                                 else None)

                    should_include = False

                    if key_major > dst_major:
                        # Higher major version always included
                        should_include = True
                    elif key_major == dst_major:
                        # Same major version
                        if key_minor is None:
                            # Major-only branch (e.g., development/4) -
                            # always included for same major
                            should_include = True
                        elif dst_minor is None:
                            # Destination is major-only, this is major.minor -
                            # exclude specific minor versions
                            should_include = False
                        else:
                            # Both have minor versions -
                            # Compare micro if present
                            if len(key) > 2 and len(dst_branch_key) > 2:
                                # Both have micro versions
                                should_include = key[2] >= dst_branch_key[2]
                            elif len(key) > 2 and len(dst_branch_key) <= 2:
                                # This branch has micro,
                                # Destination does not
                                should_include = False
                            elif len(key) <= 2 and len(dst_branch_key) > 2:
                                # This branch does not have micro,
                                # Destination does
                                should_include = True
                            else:
                                # Both have no micro
                                should_include = key_minor >= dst_minor

                    if should_include:
                        self.dst_branches.append(dev_branch)
                    else:
                        self.ignored_branches.append(dev_branch.name)
                        branch_set[DevelopmentBranch] = None
                else:
                    # For hotfix destinations, ignore all dev branches
                    self.ignored_branches.append(dev_branch.name)
                    branch_set[DevelopmentBranch] = None
            # Handle hotfix branches
            if hf_branch:
                self.dst_branches.append(hf_branch)

        # Clean up the cascade by removing keys with no branches
        keys_to_remove = []
        for key, branch_set in self._cascade.items():
            if (
                not branch_set[DevelopmentBranch] and
                not branch_set[HotfixBranch]
            ):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._cascade[key]

        # Sort dst_branches according to cascade order
        # (the cascade is already sorted)
        # Extract development branches in cascade order
        ordered_dst_branches = []
        for key, branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            hf_branch = branch_set[HotfixBranch]
            if dev_branch and dev_branch in self.dst_branches:
                ordered_dst_branches.append(dev_branch)
            if hf_branch and hf_branch in self.dst_branches:
                ordered_dst_branches.append(hf_branch)

        self.dst_branches = ordered_dst_branches

        self._set_target_versions(dst_branch)
        self.ignored_branches.sort()

    def get_development_branches(self):
        return [b[DevelopmentBranch] for _, b in self._cascade.items()
                if b[DevelopmentBranch] is not None]


def branch_factory(repo: git.Repository, branch_name: str) -> GWFBranch:
    """Construct a GWFBranch object corresponding to the branch_name.

    Args:
        repo: corresponding git repository.
        branch_name: name of the branch to construct.

    Returns:
        The constructed GWFBranch.

    Raises:
        UnrecognizedBranchPattern if the branch name is invalid.

    """
    for cls in [DevelopmentBranch, ReleaseBranch,
                QueueBranch, QueueIntegrationBranch,
                FeatureBranch, HotfixBranch, LegacyHotfixBranch,
                IntegrationBranch, UserBranch]:
        try:
            branch = cls(repo, branch_name)
            return branch
        except errors.BranchNameInvalid:
            pass

    raise errors.UnrecognizedBranchPattern(branch_name)


def build_branch_cascade(job):
    """Initialize the job's branch cascade."""
    cascade = job.git.cascade
    if cascade.dst_branches:
        # Do not rebuild cascade
        return cascade
    cascade.build(job.git.repo, job.git.dst_branch)
    LOG.debug(cascade.dst_branches)
    return cascade


def build_queue_collection(job):
    """Initialize the queue collection."""
    cascade = job.git.cascade = job.git.cascade or BranchCascade()
    if not cascade._cascade:
        cascade.build(job.git.repo)
    queues = QueueCollection(job.project_repo, job.settings.build_key,
                             cascade.get_merge_paths(),
                             getattr(job, 'force_merge', False))
    queues.build(job.git.repo)
    return queues


def is_cascade_producer(branch_name: str) -> bool:
    return branch_factory(None, branch_name).cascade_producer


def is_cascade_consumer(branch_name: str) -> bool:
    return branch_factory(None, branch_name).cascade_consumer
