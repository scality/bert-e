"""
Git host module
"""
# flake8: noqa: this import initializes the factory
from .base import Error, RepositoryExists, NoSuchRepository, NoSuchGitHost
from .factory import client_factory
from . import bitbucket, mock
