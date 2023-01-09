"""Unit tests for settings.py."""

import logging
import os
from distutils.util import strtobool

from bert_e.settings import BertEContextFilter


def test_log_filter(settings):
    """Test a simple instanciation of BertEContextFilter."""
    logging.basicConfig(format='%(instance)s - %(level)s - %(message)s')
    logger = logging.getLogger(__name__)
    log_filter = BertEContextFilter(settings)
    logger.addFilter(log_filter)
    logger.info('hello')
    assert len(logger.filters) == 1


def test_env_settings(settings_env):
    """Setup BERT_E_REPOSITORY_HOST as github and check that it is used."""

    for key, value in os.environ.items():
        if key.startswith('BERT_E_'):
            print(key)
            config_value = settings_env[key[7:].lower()]
            if isinstance(config_value, bool):
                assert config_value == strtobool(value)
            elif isinstance(config_value, int):
                assert config_value == int(value)
            else:
                assert config_value == value


def test_repository_host_url(settings_env):
    """Test that repository_host_url is set correctly."""
    assert settings_env['repository_host_url'] == 'https://github.com'


def test_pull_request_base_url(settings_env):
    """Test that pull_request_base_url is set correctly."""
    assert settings_env['pull_request_base_url'] == \
        'https://github.com/scality/bert-e/pull/{pr_id}'


def test_commit_base_url(settings_env):
    """Test that commit_base_url is set correctly."""
    assert settings_env['commit_base_url'] == \
        'https://github.com/scality/bert-e/commits/{commit_id}'
