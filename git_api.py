import os
from shutil import rmtree
from simplecmd import cmd
import subprocess
import time
from tempfile import mkdtemp
import logging


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

    def clone(self, reference=''):
        if reference:
            reference = '--reference ' + reference
        self.cmd('git clone %s %s' % (reference, self._url))
        repo_slug = self._url.split('/')[-1].replace('.git', '')
        # all commands will now execute from repo directory
        self.cmd_directory = os.path.join(self.tmp_directory, repo_slug)

    def fetch_all_branches(self):
        for remote in self.cmd("git branch -r").split('\n')[:-1]:
            local = remote.replace('origin/', '').split()[-1]
            self.cmd("git branch --track {0} {1} || exit 0"
                     .format(local, remote))
        self.cmd('git fetch --all')
        self.cmd('git pull --all || exit 0')

    def config(self, key, value):
        self.cmd('git config %s %s' % (key, value))

    def remote_branch_exists(self, name):
        """Test if a remote branch exists.

        Args:
            name: the name of the remote branch

        Returns:
            A boolean: True if the remote branch exists.
        """
        try:
            cmd('git ls-remote --heads --exit-code %s %s' % (self._url, name))
        except subprocess.CalledProcessError:
            return False

        return True

    def checkout(self, name):
        try:
            self.cmd('git checkout ' + name)
        except subprocess.CalledProcessError:
            raise CheckoutFailedException(name)

    def push(self, name):
        try:
            self.cmd('git push --set-upstream origin ' + name)
        except subprocess.CalledProcessError:
            raise PushFailedException(name)

    def cmd(self, command, retry=0, **kwargs):
        cwd = kwargs.get('cwd', self.cmd_directory)
        try:
            ret = cmd(command, cwd=cwd, **kwargs)
        except subprocess.CalledProcessError:
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

    def merge(self, source_branch, do_push=False, force_commit=False):
        self.repo.checkout(source_branch.name)
        self.checkout()

        try:
            # Set renamelimit high enough to make it 
            # work with the Confluence source
            self.repo.cmd('git config merge.renameLimit 999999')
            self.repo.cmd('git merge --no-edit %s %s'
                          % ('--no-ff' if force_commit else '',
                             source_branch.name))  # <- May fail if conflict
        except subprocess.CalledProcessError:
            self.repo.cmd('git merge --abort')
            raise MergeFailedException(self.name, source_branch.name)
        if do_push:
            self.push()

    def get_all_commits(self, source_branch):
        self.repo.checkout(source_branch.name)
        log = self.repo.cmd('git log --no-merges --pretty=%%H %s..%s' % (
            source_branch.name, self.name), universal_newlines=True)
        return log.splitlines()

    def includes_commit(self, sha1):
        try:
            self.repo.cmd('git merge-base --is-ancestor %s %s' % (sha1,
                                                                  self.name))
        except subprocess.CalledProcessError:
            return False
        return True

    def get_latest_commit(self):
        return self.repo.cmd(('git rev-parse %s' % self.name))[0:12]

    def exists(self):
        try:
            self.checkout()
            return True
        except CheckoutFailedException:
            return False

    def checkout(self):
        self.repo.checkout(self.name)

    def push(self):
        self.repo.push(self.name)

    def create(self, source_branch):
        self.repo.checkout(source_branch.name)
        try:
            self.repo.cmd('git checkout -b ' + self.name)
        except subprocess.CalledProcessError:
            msg = "branch:%s source:%s" % (self.name, source_branch.name)
            raise BranchCreationFailedException(msg)
        self.push()

    def remove(self):
        # hardcode a security since wall-e is all-powerful
        if (self.name.startswith('development') or
                self.name.startswith('release')):
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
