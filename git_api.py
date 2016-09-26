import logging
import os
import time
from pipes import quote
from shutil import rmtree
from tempfile import mkdtemp

import six
from simplecmd import cmd, CommandError


class Repository(object):
    def __init__(self, url):
        self._url = url
        self.tmp_directory = mkdtemp()
        self.cmd_directory = self.tmp_directory

    def __enter__(self):
        return self

    def __exit__(self, type_, value, tb):
        self.delete()

    def delete(self):
        rmtree(self.tmp_directory)
        self.tmp_directory = None
        self.cmd_directory = None

    def clone(self, reference='', create_mirror=True):
        """Clone the repository locally.

        Args:
            * reference: use given local repository as a reference.
            * create_mirror: if set to True (default), then in the absence of a
                reference argument, create a git mirror of the repository under
                the ``$HOME/.wall-e`` tree.

        """
        repo_slug = self._url.split('/')[-1].replace('.git', '')

        if not reference and create_mirror:
            top = os.path.expanduser('~/.wall-e/')
            try:
                os.mkdir(top)
            except OSError:
                pass
            reference = top + repo_slug
            if not os.path.isdir(reference):
                # fixme: isdir() is not a good test of repo existence
                self.cmd('git clone --mirror %s %s', self._url, reference)

        clone_cmd = 'git clone'
        clone_cmd += ' --reference ' + reference
        self.cmd('%s %%s' % clone_cmd, self._url)

        # all commands will now execute from repo directory
        self.cmd_directory = os.path.join(self.tmp_directory, repo_slug)

    def fetch_all_branches(self):
        for remote in self.cmd("git branch -r").split('\n')[:-1]:
            local = remote.replace('origin/', '').split()[-1]
            self.cmd("git branch --track %s %s || exit 0", local, remote)
        self.cmd('git fetch --all')
        self.cmd('git pull --all || exit 0')

    def config(self, key, value):
        self.cmd('git config %s %s', key, value)

    def remote_branch_exists(self, name):
        """Test if a remote branch exists.

        Args:
            name: the name of the remote branch

        Returns:
            A boolean: True if the remote branch exists.
        """
        try:
            self.cmd('git ls-remote --heads --exit-code %s %s',
                     self._url, name)
        except CommandError:
            return False

        return True

    def get_branches_from_sha1(self, sha1):
        lines = self.cmd('git ls-remote --heads %s', self._url).splitlines()
        branches = []
        for line in lines:
            line_sha1, reference = line.split()
            if line_sha1 == sha1 and reference.startswith('refs/heads/'):
                branches.append(reference.replace('refs/heads/', '').strip())
        return branches

    def checkout(self, name):
        try:
            self.cmd('git checkout %s', name)
        except CommandError:
            raise CheckoutFailedException(name)

    def reset(self):
        self.cmd('git reset HEAD --hard')

    def push(self, name):
        try:
            self.cmd('git push --set-upstream origin ' + name)
        except CommandError:
            raise PushFailedException(name)

    def push_all(self):
        try:
            self.cmd('git push --all --atomic')
        except CommandError as err:
            raise PushFailedException(err)

    def cmd(self, command, *args, **kwargs):
        retry = kwargs.pop('retry', 0)
        if args:
            command = command % tuple(
                quote(arg.strip()) if isinstance(arg, str) and arg else arg
                for arg in args
            )
        cwd = kwargs.get('cwd', self.cmd_directory)
        try:
            ret = cmd(command, cwd=cwd, **kwargs)
        except CommandError:
            if retry == 0:
                raise

            logging.warning('The following command failed:\n'
                            ' %s\n'
                            '[%s retry left]', command, retry)
            time.sleep(120)  # helps stabilize requests to bitbucket
            ret = self.cmd(command, retry=retry-1, **kwargs)
        return ret


class Branch(object):
    def __init__(self, repo, name):
        self.repo = repo
        self.name = name

    def merge(self, *source_branches, **kwargs):
        do_push = kwargs.pop('do_push', False)
        force_commit = kwargs.pop('force_commit', False)
        for source_branch in source_branches:
            self.repo.checkout(source_branch.name)
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
        self.repo.checkout(source_branch.name)
        log = self.repo.cmd('git log --no-merges --pretty=%%H %s..%s',
                            source_branch.name, self.name,
                            universal_newlines=True)
        return log.splitlines()

    def includes_commit(self, sha1):
        try:
            self.repo.cmd('git merge-base --is-ancestor %s %s',
                          six.text_type(sha1), self.name)
        except CommandError:
            return False
        return True

    def get_latest_commit(self):
        return self.repo.cmd('git rev-parse %s', self.name)

    def exists(self):
        try:
            self.checkout()
            return True
        except CheckoutFailedException:
            return False

    def checkout(self):
        self.repo.checkout(self.name)

    def reset(self):
        self.repo.reset()

    def push(self):
        self.repo.push(self.name)

    def create(self, source_branch):
        self.repo.checkout(source_branch.name)
        try:
            self.repo.cmd('git checkout -b %s', self.name)
        except CommandError:
            msg = "branch:%s source:%s" % (self.name, source_branch.name)
            raise BranchCreationFailedException(msg)
        self.push()

    def remove(self):
        # hardcode a security since wall-e is all-powerful
        if not self.name.startswith('w/'):
            raise ForbiddenOperation('cannot delete branch %s' %
                                     self.name)

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
