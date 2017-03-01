"""
Git host module
"""
# flake8: noqa
# these imports initialize the public API
from .base import Error, RepositoryExists, NoSuchRepository, NoSuchGitHost
from .factory import client_factory
from . import bitbucket, github, mock
