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

import logging
import os
import time
from collections import defaultdict
from pipes import quote
from shutil import rmtree
from tempfile import mkdtemp

from .retry import RetryHandler
from .simplecmd import CommandError, cmd

LOG = logging.getLogger(__name__)


class Repository(object):
    def __init__(self, url, mask_pwd=''):
        self._url = url
        self.tmp_directory = None
        self.reset()
        self._mask_pwd = mask_pwd

    def __enter__(self):
        return self

    def __exit__(self, type_, value, tb):
        self.delete()

    def reset(self):
        if self.tmp_directory:
            self.delete()
        self.tmp_directory = mkdtemp()
        self.cmd_directory = self.tmp_directory
        self._remote_heads = defaultdict(set)
        self._remote_branches = dict()

    def delete(self):
        def onerror_cb(func, path, excinfo):
            errtype, *_ = excinfo
            LOG.warning(
                'Exception %s raised while removing %s.', errtype, path
            )

        rmtree(self.tmp_directory, onerror=onerror_cb)
        self.tmp_directory = None
        self.cmd_directory = None

    def clone(self):
        """Clone the repository locally."""
        repo_slug = self._url.split('/')[-1].replace('.git', '')

        top = os.path.expanduser('~/.bert-e/')
        try:
            os.mkdir(top)
        except OSError:
            pass
        git_cache = os.path.join(top, repo_slug + '.git')
        if not os.path.isdir(git_cache):
            # fixme: isdir() is not a good test of repo existence
            # Clone the git cache in ~/.bert-e/<repo>.git
            self.cmd('git clone --mirror %s', self._url, cwd=top)
        else:
            # Update the git cache
            self.cmd('git fetch --prune', cwd=git_cache)

        # all commands will now execute from repo directory
        self.cmd_directory = os.path.join(self.tmp_directory, repo_slug)
        if os.path.isdir(self.cmd_directory):
            # The repo is already cloned by a previous call to this method
            # some tests do clone twice
            return

        # We need to clone all the git branches locally to make Bert-E's code
        # simple and easy to maintain.
        # A fast way to do that is to clone a mirror and then reconvert it to
        # a normal repo.
        # see https://git.wiki.kernel.org/index.php/Git_FAQ#How_do_I_clone_a_re
        # pository_with_all_remotely_tracked_branches.3F
        os.mkdir(self.cmd_directory)
        self.cmd('git clone --mirror %s .git', git_cache)
        self.cmd('git config --bool core.bare false')
        # The current origin is the local cache, delete then point it to the
        # original repo
        self.cmd('git remote remove origin')
        self.cmd('git remote add origin %s', self._url)
        # Update the list of remote branches (required if we use 'branch -r')
        self.cmd('git remote update origin')

    def config(self, key, value):
        self.cmd('git config %s %s', key, value)

    def _get_remote_branches(self, force=False):
        """Put remote branch information in cache.

        Args:
            - Force (bool): force cache refresh. Defaults to False.

        """
        output = ''
        if not force and (self._remote_branches or self._remote_heads):
            return
        self._remote_heads = defaultdict(set)
        self._remote_branches = dict()
        output = self.cmd('git ls-remote --heads %s', self._url)

        for line in output.splitlines():
            sha, branch = line.replace('\t', ' ').split()
            # use short sha1 everywhere (sometimes only info sent by BB API)
            sha = sha[:12]
            branch = branch.replace('refs/heads/', '').strip()
            self._remote_heads[sha].add(branch)
            self._remote_branches[branch] = sha

    def remote_branch_exists(self, name, refresh_cache=False):
        """Test if a remote branch exists.

        Args:
            name: the name of the remote branch

        Returns:
            A boolean: True if the remote branch exists.
        """
        self._get_remote_branches(refresh_cache)
        return name in self._remote_branches

    def get_branches_from_commit(self, commit, refresh_cache=False):
        """Get branches corresponding to given commit."""
        self._get_remote_branches(refresh_cache)
        return self._remote_heads[('%s' % commit)[:12]]

    def checkout(self, name):
        try:
            self.cmd('git checkout %s', name)
        except CommandError as err:
            raise CheckoutFailedException(name) from err

    def push(self, name):
        try:
            self.cmd('git push --set-upstream origin ' + name)
        except CommandError as err:
            raise PushFailedException(name) from err

    def push_all(self, prune=False):
        prune = '--prune' if prune else ''
        try:
            self.cmd('git push --all --atomic %s' % prune)
        except CommandError as err:
            raise PushFailedException(err) from err

    def cmd(self, command, *args, **kwargs):
        retry = kwargs.pop('retry', 0)
        if args:
            command = command % tuple(
                quote(arg.strip()) if isinstance(arg, str) and arg else arg
                for arg in args
            )
        cwd = kwargs.pop('cwd', self.cmd_directory)
        kwargs.setdefault('mask_pwd', self._mask_pwd)
        try:
            ret = cmd(command, cwd=cwd, **kwargs)
        except CommandError:
            if retry == 0:
                raise

            LOG.debug('command failed [%s retry left]', retry)
            time.sleep(120)  # helps stabilize requests to bitbucket
            ret = self.cmd(command, retry=retry - 1, **kwargs)
        return ret

    @property
    def remote_branches(self):
        self._get_remote_branches()
        return self._remote_branches.keys()


class Branch(object):
    def __init__(self, repo, name):
        self.repo = repo
        self.name = name
        self.newly_created = False

    def merge(self, *source_branches, **kwargs):
        do_push = kwargs.pop('do_push', False)
        force_commit = kwargs.pop('force_commit', False)
        self.checkout()

        branches = ' '.join(("'%s'" % s.name) for s in source_branches)
        try:
            command = 'git merge --no-edit %s %s' % ('--no-ff' if force_commit
                                                     else '', branches)
            self.repo.cmd(command)  # May fail if conflict
        except CommandError as err:
            raise MergeFailedException(self.name, branches) from err
        if do_push:
            self.push()

    def get_commit_diff(self, source_branch, ignore_merges=True):
        log = self.repo.cmd(
            'git log %s --pretty="%%H %%P" %s..%s',
            '--no-merges' if ignore_merges else '', source_branch, self.name)
        return (
            Commit(self.repo, sha1, parents=parents)
            for sha1, *parents in (line.split() for line in log.splitlines())
        )

    def includes_commit(self, commit):
        try:
            self.repo.cmd('git merge-base --is-ancestor %s %s',
                          commit, self.name)
        except CommandError:
            return False
        return True

    def get_latest_commit(self):
        return self.repo.cmd('git rev-parse %s', self.name).rstrip()

    def exists(self):
        try:
            self.checkout()
            return True
        except CheckoutFailedException:
            return False

    def checkout(self):
        self.repo.checkout(self.name)

    def reset(self, do_checkout=True, origin=True, ignore_missing=False):
        if do_checkout:
            self.checkout()
        try:
            self.repo.cmd('git reset --hard %s',
                          'origin/' + self.name if origin else self.name)
        except CommandError:
            if not ignore_missing:
                raise

    def push(self):
        self.repo.push(self.name)

    def create(self, source_branch, do_push=True):
        try:
            self.repo.cmd('git checkout -b %s %s', self.name,
                          source_branch.name)
        except CommandError as err:
            msg = "branch:%s source:%s" % (self.name, source_branch.name)
            raise BranchCreationFailedException(msg) from err
        if do_push:
            self.push()
        self.newly_created = True

    def remove(self, do_push=False):
        # security check since Bert-E is all-powerful on the repository
        if not (self.name.startswith('w/') or self.name.startswith('q/') or
                self.name.startswith('tmp/')):
            raise ForbiddenOperation('cannot delete branch %s' %
                                     self.name)

        self.repo.cmd('git branch -D %s', self.name)
        if not do_push:
            return
        try:
            self.repo.push(':' + self.name)
        except PushFailedException as err:
            raise RemoveFailedException() from err

    def __contains__(self, commit):
        return self.includes_commit(commit)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def differs(self, other):
        res = self.repo.cmd('git diff %s %s', self.name, other,
                            universal_newlines=False)
        return bool(res)


class Commit(object):
    def __init__(self, repo, sha1, author=None, parents=None):
        self._repo = repo
        self.sha1 = sha1
        self._author = author
        try:
            self._parents = [Commit(repo, parent) for parent in parents]
        except TypeError:
            self._parents = None

    @property
    def author(self):
        if not self._author:
            # Author names can contain non-ascii characters in pretty much
            # any encoding. Hence the use of 'universal_newlines=False' and an
            # explicit decoding that escapes symbols from unknown encodings.
            self._author = (
                self._repo.cmd('git show --pretty="%%aN" %s', self.sha1,
                               universal_newlines=False)
                .decode('utf-8', 'backslashreplace')
                .strip()
            )
        return self._author

    @property
    def is_merge(self):
        return len(self.parents) > 1

    @property
    def parents(self):
        if self._parents is None:
            self._parents = []
            for info in (self._repo.cmd('git cat-file -p %s', self.sha1)
                         .splitlines()):
                try:
                    key, value = info.split(maxsplit=1)
                except ValueError:
                    continue
                if key == 'parent':
                    self._parents.append(Commit(self._repo, value))
        return self._parents

    def __repr__(self):
        return str(self.sha1)

    def __hash__(self):
        return hash(self.sha1)

    def __eq__(self, other):
        if isinstance(other, Commit):
            return self.sha1 == other.sha1
        elif isinstance(other, str):
            # Accept to compare Commit objects and str sha1s
            return self.sha1 == other


class GitException(Exception):
    pass


class MergeFailedException(GitException):
    pass


class CheckoutFailedException(GitException):
    pass


class PushFailedException(GitException):
    pass


class RemoveFailedException(GitException):
    pass


class BranchCreationFailedException(GitException):
    pass


class ForbiddenOperation(GitException):
    pass


def robust_merge(dst: Branch, src1: Branch, src2: Branch):
    """'Best-effort' octopus merge.

    Perform both the merge using octopus and consecutive strategies.
    If the resulting branches differ, keep the result of consecutive merges.
    Otherwise, keep the octopus merge.

    """
    tmp_oct = Branch(dst.repo, 'tmp/octopus/{}'.format(dst))
    tmp_cns = Branch(dst.repo, 'tmp/normal/{}'.format(dst))

    tmp_oct.create(dst, do_push=False)
    tmp_cns.create(dst, do_push=False)

    oct_conflict = None

    try:
        octopus_merge(tmp_oct, src1, src2)
    except MergeFailedException as err:
        oct_conflict = err

    consecutive_merge(tmp_cns, src1, src2)

    if oct_conflict is not None:
        dst.merge(tmp_cns)
    elif tmp_cns.differs(tmp_oct):
        LOG.warning('Octopus merge yielded a different result than consecutive'
                    ' merges.')
        dst.merge(tmp_cns)
    else:
        dst.merge(tmp_oct)

    tmp_oct.remove()
    tmp_cns.remove()


def octopus_merge(dst: Branch, src1: Branch, src2: Branch):
    """Try a 3-way octopus merge.

    If it fails, try merging sources in opposite order.
    If it still fails try a poor man's 3-way merge by doing two consecutive
    2-way merges.

    Raises:
        MergeFailedException: if there is an actual conflict.

    """
    try:
        dst.merge(src1, src2)
    except MergeFailedException as err:
        try:
            dst.reset(False, False)
            dst.merge(src2, src1)
        except MergeFailedException:
            dst.reset(False, False)
            raise err
        except Exception:
            raise err


def consecutive_merge(dst: Branch, src1: Branch, src2: Branch):
    """Poor man's 3-way merge using two consecutive 2-way merges.

    If it fails, try merging sources in opposite order.

    Raises:
        MergeFailedException: if there is an actual conflict.

    """
    try:
        dst.merge(src1)
        dst.merge(src2)
    except MergeFailedException as err:
        try:
            dst.reset(False, False)
            dst.merge(src2)
            dst.merge(src1)
        except MergeFailedException:
            raise
        except Exception:
            raise err


def push(repo: Repository, branches=None, prune=False):
    """Push multiple branches at once. Retry up to 30 seconds before giving up.

    Args:
        repo: Git repository to push.
        branches: branches to push.
        prune: push branch deletions too.

    """
    retry = RetryHandler(30, LOG)
    names = ''
    if branches:
        names = ' '.join("'{0}'".format(b.name) for b in branches)
        with retry:
            retry.run(
                repo.push, names,
                catch=PushFailedException,
                fail_msg="Failed to push changes"
            )
    elif branches is None:
        with retry:
            retry.run(
                repo.push_all,
                prune=prune,
                catch=PushFailedException,
                fail_msg="Failed to push changes"
            )


def clone_git_repo(job):
    """Get a local clone of the project's repository to work on."""
    repo = job.git.repo
    repo.clone()
    repo.config('user.email', job.settings.robot_email)
    repo.config('user.name', job.settings.robot_username)
    repo.config('merge.renameLimit', '999999')
    return repo
