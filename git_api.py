import os
from shutil import rmtree
from simplecmd import cmd
import subprocess
from tempfile import mkdtemp


class Repository(object):
    def __init__(self, url):
        self._url = url
        self.directory = mkdtemp()

    def __enter__(self):
        return self

    def __exit__(self, type_, value, tb):
        self.delete()

    def delete(self):
        rmtree(self.directory)
        self.directory = None

    def clone(self, reference=''):
        if reference:
            reference = '--reference ' + reference
        self.cmd('git clone %s %s' % (reference, self._url))
        repo_slug = self._url.split('/')[-1].replace('.git', '')
        self.directory = os.path.join(self.directory, repo_slug)

    def config(self, key, value):
        self.cmd('git config %s %s' % (key, value))

    def push_everything(self):
        self.cmd('git push --all origin -u')

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

    def cmd(self, command):
        return cmd(command, cwd=self.directory)


class Branch(object):
    def __init__(self, name):
        self.name = name

    def merge(self, source_branch, do_push=False, force_commit=False):
        source_branch.checkout()
        self.checkout()

        try:
            cmd('git merge --no-edit %s %s'
                % ('--no-ff' if force_commit else '',
                   source_branch.name))  # <- May fail if conflict
        except subprocess.CalledProcessError:
            cmd('git merge --abort')
            raise MergeFailedException(self.name, source_branch.name)
        if do_push:
            self.push()

    def get_all_commits_since_started_from(self, source_branch):
        source_branch.checkout()
        log = cmd('git log --no-merges --pretty=%%H %s..%s' % (
            source_branch.name, self.name))
        return log.splitlines()

    def includes_commit(self, sha1):
        try:
            cmd('git merge-base --is-ancestor %s %s' % (sha1, self.name))
        except subprocess.CalledProcessError:
            return False
        return True

    def exists(self):
        try:
            self.checkout()
            return True
        except CheckoutFailedException:
            return False

    def checkout(self):
        try:
            cmd('git checkout ' + self.name)
        except subprocess.CalledProcessError:
            raise CheckoutFailedException(self.name)

    def push(self):
        self.checkout()
        try:
            cmd('git push --set-upstream origin ' + self.name)
        except subprocess.CalledProcessError:
            raise PushFailedException(self.name)

    def create(self, source_branch):
        source_branch.checkout()
        try:
            cmd('git checkout -b ' + self.name)
        except subprocess.CalledProcessError:
            msg = "branch:%s source:%s" % (self.name, source_branch.name)
            raise BranchCreationFailedException(msg)
        self.push()

    def create_if_not_exists(self, source_branch):
        if not self.exists():
            self.create(source_branch)


class GitException(Exception):
    pass


class MergeFailedException(GitException):
    pass


class CheckoutFailedException(GitException):
    pass


class PushFailedException(GitException):
    pass


class BranchCreationFailedException(GitException):
    pass
