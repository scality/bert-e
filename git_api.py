import os
from simplecmd import cmd
from tempfile import mkdtemp
import subprocess


class Repository:
    def __init__(self, url):
        self._url = url
        self.directory = mkdtemp()
        os.chdir(self.directory)

    def init(self):
        """resets the git repo"""
        assert '/ring/' not in self._url  # This is a security, do not remove
        cmd('git init')
        cmd('touch a')
        cmd('git add a')
        cmd('git commit -m "Initial commit"')
        cmd('git remote add origin ' + self._url)
        cmd('git push --set-upstream origin master')

    def clone(self, reference=''):
        if reference:
            reference = '--reference ' + reference
        cmd('git clone %s %s' % (reference, self._url))
        repo_slug = self._url.split('/')[-1].replace('.git', '')
        os.chdir(repo_slug)
        self.directory += '/' + repo_slug

    def config(self, key, value):
        cmd('git config %s %s' % (key, value))

    @staticmethod
    def create_branch(name, from_branch=None, file=False, do_push=True):
        if from_branch:
            cmd('git checkout '+from_branch)
        cmd('git checkout -b '+name)
        if file:
            if file is True:
                file = name.replace('/', '-')
            cmd('echo %s >  a.%s' % (name, file))
            cmd('git add a.'+file)
            cmd('git commit -m "commit %s"' % file)
        if do_push:
            cmd('git push --set-upstream origin '+name)

    def create_ring_branching_model(self):
        for version in ['4.3', '5.1', '6.0', 'trunk']:
            self.create_branch('release/'+version)
            self.create_branch('development/'+version,
                               'release/'+version, file=True)


class Branch:
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
