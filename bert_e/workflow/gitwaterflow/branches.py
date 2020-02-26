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
from functools import total_ordering

from bert_e import exceptions as errors
from bert_e.lib import git
from bert_e.lib.template_loader import render

LOG = logging.getLogger(__name__)


class GWFBranch(git.Branch):
    pattern = '(?P<prefix>[a-z]+)/(?P<label>.+)'
    major = 0
    minor = 0
    micro = -1  # is incremented always, first version is 0
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
            if (key in ('major', 'minor', 'micro', 'pr_id') and
                    value is not None):
                value = int(value)
            self.__setattr__(key, value)

    def __str__(self):
        return self.name

    @property
    def version_t(self):
        if self.micro is not None:
            return (self.major, self.minor, self.micro)

        return (self.major, self.minor)


class HotfixBranch(GWFBranch):
    pattern = '^hotfix/(?P<label>.+)$'


class UserBranch(GWFBranch):
    pattern = '^user/(?P<label>.+)$'


class ReleaseBranch(GWFBranch):
    pattern = '^release/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'


class FeatureBranch(GWFBranch):
    all_prefixes = ('improvement', 'bugfix', 'feature', 'project',
                    'documentation', 'design', 'dependabot')
    jira_issue_pattern = '(?P<jira_project>[A-Z0-9_]+)-[0-9]+'
    prefixes = '(?P<prefix>(%s))' % '|'.join(all_prefixes)
    pattern = "^(?P<feature_branch>%s/(?P<label>(?P<jira_issue_key>%s)?" \
              "(?(jira_issue_key).*|.+)))$" % (prefixes, jira_issue_pattern)
    cascade_producer = True


@total_ordering
class DevelopmentBranch(GWFBranch):
    pattern = '^development/(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'
    cascade_producer = True
    cascade_consumer = True
    can_be_destination = True
    allow_prefixes = FeatureBranch.all_prefixes
    has_stabilization = False

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.major == other.major and
                self.minor == other.minor)

    def __lt__(self, other):
        return (self.__class__ == other.__class__ and
                (self.major < other.major or
                 (self.major == other.major and
                  self.minor < other.minor)))

    @property
    def version_t(self):
        return (self.major, self.minor)


@total_ordering
class StabilizationBranch(DevelopmentBranch):
    pattern = '^stabilization/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+))$'
    allow_prefixes = FeatureBranch.all_prefixes

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.major == other.major and
                self.minor == other.minor and
                self.micro == other.micro)

    def __lt__(self, other):
        return (self.__class__ == other.__class__ and
                (self.major < other.major or
                 (self.major == other.major and
                  self.minor < other.minor) or
                 (self.major == other.major and
                  self.minor == other.minor and
                  self.micro < other.micro)))

    @property
    def version_t(self):
        return (self.major, self.minor, self.micro)


class IntegrationBranch(GWFBranch):
    pattern = '^w/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              '(\.(?P<micro>\d+))?)/' + FeatureBranch.pattern[1:]
    dst_branch = ''
    feature_branch = ''

    def get_pull_request_from_list(self, open_prs):
        import pdb; pdb.set_trace()
        for pr in open_prs:
            if pr.src_branch != self.name:
                continue
            if self.dst_branch and \
                    pr.dst_branch != \
                    self.dst_branch.name:
                continue
            return pr

    def get_or_create_pull_request(self, parent_pr, open_prs, githost_repo):
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
            pr = githost_repo.create_pull_request(
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

    def get_or_create_pull_request(self, parent_pr, open_prs, githost_repo):
        return self.get_pull_request_from_list(open_prs), False

    def remove(self, do_push=False):
        pass  # Never delete the source branch


class QueueBranch(GWFBranch):
    pattern = '^q/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              '(\.(?P<micro>\d+))?)$'
    dst_branch = ''

    def __init__(self, repo, name):
        super(QueueBranch, self).__init__(repo, name)
        if self.micro is not None:
            dest = branch_factory(repo, 'stabilization/%s' % self.version)
        else:
            dest = branch_factory(repo, 'development/%s' % self.version)
        self.dst_branch = dest

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.name == other.name


@total_ordering
class QueueIntegrationBranch(GWFBranch):
    pattern = '^q/(?P<pr_id>\d+)/' + IntegrationBranch.pattern[3:]

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
            match_ = re.match('\s*origin/(?P<name>.*)', branch)
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
            self._queues = OrderedDict(sorted(self._queues.items()))

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

        # check all subsequent versions have a master queue
        has_queues = False
        for version in versions:
            if version not in stack:
                if has_queues:
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
        prs = []
        # identify version corresponding to last dev queue
        # (i.e. ignore stab queues)
        greatest_dev = None
        for version in reversed(queues.keys()):
            if len(version) == 2:
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
            raise errors.QueuesNotValidated()

        mergeable_prs = self._extract_pr_ids(self._queues)

        if not self.force_merge:
            for merge_path in self.merge_paths:
                versions = [branch.version_t for branch in merge_path]
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

    @property
    def queued_prs(self):
        """Ordered list of queued PR IDs (oldest first)."""
        if not self._queues:
            return []
        last_entry = self._queues[list(self._queues.keys())[-1]]
        return list(reversed([branch.pr_id for branch in
                              last_entry[QueueIntegrationBranch]]))

    def has_version_queued_prs(self, version):
        return (self._queues.get(version, {}).get(QueueIntegrationBranch)
                is not None)


class BranchCascade(object):
    def __init__(self):
        self._cascade = OrderedDict()
        self.dst_branches = []  # store branches
        self.ignored_branches = []  # store branch names (easier sort)
        self.target_versions = []
        self._merge_paths = []

    def build(self, repo, dst_branch=None):
        flat_branches = set()
        for prefix in ['development', 'stabilization']:
            cmd = 'git branch -a --list *%s/*' % prefix
            for branch in repo.cmd(cmd).split('\n')[:-1]:
                match_ = re.match('\*?\s*(remotes/origin/)?(?P<name>.*)',
                                  branch)
                if match_:
                    flat_branches.add(match_.group('name'))
        for flat_branch in flat_branches:
            try:
                branch = branch_factory(repo, flat_branch)
            except errors.UnrecognizedBranchPattern:
                continue
            self.add_branch(branch)

        for tag in repo.cmd('git tag').split('\n')[:-1]:
            self.update_micro(tag)

        if dst_branch:
            self.finalize(dst_branch)

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
            LOG.debug("Discard non destination branch: %s", branch)
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
            raise errors.UnsupportedMultipleStabBranches(cur_branch, branch)

        self._cascade[(major, minor)][branch.__class__] = branch

    def update_micro(self, tag):
        """Update development branch latest micro based on tag."""
        pattern = "^(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<micro>\d+))$"
        match = re.match(pattern, tag)
        if not match:
            LOG.debug("Ignore tag: %s", tag)
            return
        LOG.debug("Consider tag: %s", tag)
        major = int(match.groupdict()['major'])
        minor = int(match.groupdict()['minor'])
        micro = int(match.groupdict()['micro'])
        try:
            branches = self._cascade[(major, minor)]
        except KeyError:
            LOG.debug("Ignore tag: %s", tag)
            return
        stb_branch = branches[StabilizationBranch]

        if stb_branch is not None and stb_branch.micro <= micro:
            # We have a tag but we did not remove the stabilization branch.
            raise errors.DeprecatedStabilizationBranch(stb_branch.name, tag)

        dev_branch = branches[DevelopmentBranch]
        if dev_branch:
            dev_branch.micro = max(micro, dev_branch.micro)

    def validate(self):
        previous_dev_branch = None
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if stb_branch and dev_branch:
                if dev_branch.micro + 1 != stb_branch.micro:
                    raise errors.VersionMismatch(dev_branch, stb_branch)

                if not dev_branch.includes_commit(stb_branch):
                    raise errors.DevBranchesNotSelfContained(stb_branch,
                                                             dev_branch)

            if previous_dev_branch:
                if not dev_branch.includes_commit(previous_dev_branch):
                    raise errors.DevBranchesNotSelfContained(
                        previous_dev_branch, dev_branch)

            previous_dev_branch = dev_branch if dev_branch else stb_branch

    def _set_target_versions(self, dst_branch):
        """Compute list of expected Jira FixVersion/s.

        Must be called after the cascade has been finalised.

        """
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]
            # TODO: rename this error. it doesn't make sense
            if (dev_branch is None and stb_branch is None and
                    isinstance(dst_branch, DevelopmentBranch)):
                raise errors.DevBranchDoesNotExist(
                    'development/%d.%d' % (dst_branch.major, dst_branch.minor))

            if stb_branch:
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, stb_branch.micro))
            else:
                offset = 2 if dev_branch.has_stabilization else 1
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, dev_branch.micro + offset))

    def finalize(self, dst_branch):
        """Finalize cascade considering given destination.

        Assumes the cascade has been populated by calls to add_branch
        and update_micro. The local lists keeping track

        Args:
            dst_branch: where the pull request wants to merge

        Raises:

        Returns:
            list: list of destination branches
            list: list of ignored destination branches

        """
        self.get_merge_paths()  # populate merge paths before removing data
        ignore_stb_branches = False
        include_dev_branches = False
        dev_branch = None
        if dst_branch.name == 'development/10.0':
            import pdb; pdb.set_trace()
        for (major, minor), branch_set in list(self._cascade.items()):
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            # TODO: rename this error. it doesn't make sense
            if (dev_branch is None and stb_branch is None and
                    isinstance(dst_branch, DevelopmentBranch)):
                raise errors.DevBranchDoesNotExist(
                    'development/%d.%d' % (dst_branch.major, dst_branch.minor))

            # remember if a stab is attached before it is removed
            # from path, for the correct target_version computation
            if stb_branch and dev_branch:
                dev_branch.has_stabilization = True

            # remove untargetted branches from cascade
            if dst_branch == dev_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if stb_branch and ignore_stb_branches:
                branch_set[StabilizationBranch] = None
                self.ignored_branches.append(stb_branch.name)
                if dev_branch is None:
                    del self._cascade[(major, minor)]

            if dst_branch == stb_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if dev_branch is not None and not include_dev_branches:
                branch_set[DevelopmentBranch] = None
                self.ignored_branches.append(dev_branch.name)

                if branch_set[StabilizationBranch]:
                    branch_set[StabilizationBranch] = None
                    self.ignored_branches.append(stb_branch.name)

                del self._cascade[(major, minor)]
                continue

            # add to dst_branches in the correct order
            if branch_set[StabilizationBranch] and isinstance(dst_branch, DevelopmentBranch):
                self.dst_branches.append(stb_branch)
            if branch_set[DevelopmentBranch]:
                self.dst_branches.append(dev_branch)
        if not any(self.dst_branches):
            raise errors.NotASingleDevBranch()

        self._set_target_versions(dst_branch)
        self.ignored_branches.sort()

    def get_development_branches(self):
        return [b[DevelopmentBranch] for _, b in self._cascade.items()]


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
    for cls in [StabilizationBranch, DevelopmentBranch, ReleaseBranch,
                QueueBranch, QueueIntegrationBranch,
                FeatureBranch, HotfixBranch, IntegrationBranch, UserBranch]:
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
