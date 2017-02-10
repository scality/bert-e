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

from ..simplecmd import CommandError, cmd


LOG = logging.getLogger(__name__)


class Repository(object):
    def __init__(self, url, mask_pwd=''):
        self._url = url
        self.tmp_directory = mkdtemp()
        self.cmd_directory = self.tmp_directory
        self._remote_heads = defaultdict(set)
        self._remote_branches = dict()
        self._mask_pwd = mask_pwd

    def __enter__(self):
        return self

    def __exit__(self, type_, value, tb):
        self.delete()

    def delete(self):
        rmtree(self.tmp_directory)
        self.tmp_directory = None
        self.cmd_directory = None

    def clone(self):
        """Clone the repository locally.
        """
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
        try:
            output = self.cmd('git ls-remote --heads %s', self._url)
        except CommandError:
            return

        for line in output.splitlines():
            sha, branch = line.split()
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

    def get_branches_from_sha1(self, sha1):
        """Get branches corresponding to given sha1."""
        self._get_remote_branches()
        return self._remote_heads[sha1[:12]]

    def checkout(self, name):
        try:
            self.cmd('git checkout %s', name)
        except CommandError:
            raise CheckoutFailedException(name)

    def push(self, name):
        try:
            self.cmd('git push --set-upstream origin ' + name)
        except CommandError:
            raise PushFailedException(name)

    def push_all(self, prune=False):
        prune = '--prune' if prune else ''
        try:
            self.cmd('git push --all --atomic %s' % prune)
        except CommandError as err:
            raise PushFailedException(err)

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


class Branch(object):
    def __init__(self, repo, name):
        self.repo = repo
        self.name = name

    def merge(self, *source_branches, **kwargs):
        do_push = kwargs.pop('do_push', False)
        force_commit = kwargs.pop('force_commit', False)
        self.checkout()

        branches = ' '.join(("'%s'" % s.name) for s in source_branches)
        try:
            command = 'git merge --no-edit %s %s' % ('--no-ff' if force_commit
                                                     else '', branches)
            self.repo.cmd(command)  # May fail if conflict
        except CommandError:
            raise MergeFailedException(self.name, branches)
        if do_push:
            self.push()

    def get_commit_diff(self, source_branch):
        log = self.repo.cmd('git log --no-merges --pretty=%%H %s..%s',
                            source_branch.name, self.name,
                            universal_newlines=True)
        return log.splitlines()

    def includes_commit(self, sha1):
        try:
            self.repo.cmd('git merge-base --is-ancestor %s %s',
                          sha1, self.name)
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

    def reset(self, do_checkout=True):
        if do_checkout:
            self.checkout()
        self.repo.cmd('git reset --hard origin/%s', self.name)

    def push(self):
        self.repo.push(self.name)

    def create(self, source_branch, do_push=True):
        try:
            self.repo.cmd('git checkout -b %s %s', self.name,
                          source_branch.name)
        except CommandError:
            msg = "branch:%s source:%s" % (self.name, source_branch.name)
            raise BranchCreationFailedException(msg)
        if do_push:
            self.push()

    def remove(self, do_push=False):
        # security check since Bert-E is all-powerful on the repository
        if not (self.name.startswith('w/') or self.name.startswith('q/')):
            raise ForbiddenOperation('cannot delete branch %s' %
                                     self.name)

        self.repo.cmd('git branch -D %s', self.name)
        if not do_push:
            return
        try:
            self.repo.push(':' + self.name)
        except PushFailedException:
            raise RemoveFailedException()

    def __repr__(self):
        return self.name


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
