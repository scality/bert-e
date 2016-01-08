import os
from simplecmd import cmd
from tempfile import mkdtemp
import subprocess


class Repository(object):
    def __init__(self, url):
        self._url = url
        self.directory = mkdtemp()
        os.chdir(self.directory)

    def clone(self, reference=''):
        if reference:
            reference = '--reference ' + reference
        cmd('git clone %s %s' % (reference, self._url))
        repo_slug = self._url.split('/')[-1].replace('.git', '')
        os.chdir(repo_slug)
        self.directory += '/' + repo_slug

    def config(self, key, value):
        cmd('git config %s %s' % (key, value))

    def push_everything(self):
        cmd('git push --all origin -u')

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


class Branch(object):
    def __init__(self, name):
        self.name = name

    def merge(self, source_branch):
        source_branch.checkout()
        self.checkout()
        try:
            cmd('git merge --no-edit %s'
                % (source_branch.name))  # <- May fail if conflict
        except subprocess.CalledProcessError:
            raise MergeFailedException(self.name, source_branch.name)

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

    def update_or_create_and_merge(self, source_branch, push=True):
        if self.exists():
            self.merge(source_branch)
        else:
            self.create(source_branch)
        self.push()


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
