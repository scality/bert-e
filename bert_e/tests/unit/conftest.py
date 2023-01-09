
"""Unit tests fixtures."""
import os
from os.path import abspath
import pytest

from bert_e.settings import setup_settings


@pytest.fixture
def settings():
    """Simple settings fixture."""
    return setup_settings(os.path.abspath('settings.sample.yml'))


@pytest.fixture
def settings_env():
    """Simple settings fixture."""
    os.environ['BERT_E_REPOSITORY_HOST'] = 'github'
    os.environ['BERT_E_REPOSITORY_OWNER'] = 'scality'
    os.environ['BERT_E_REPOSITORY_SLUG'] = 'bert-e'
    os.environ['BERT_E_ROBOT'] = 'robot_username'
    os.environ['BERT_E_ROBOT_EMAIL'] = 'robot_email@nowhere.com'
    os.environ['BERT_E_BUILD_KEY'] = 'github_actions'
    os.environ['BERT_E_REQUIRED_PEER_APPROVALS'] = '2'
    os.environ['BERT_E_NEED_AUTHOR_APPROVAL'] = 'true'
    os.environ['BERT_E_JIRA_ACCOUNT_URL'] = 'https://my_account.atlassian.net'
    os.environ['BERT_E_JIRA_EMAIL'] = 'my_jira@email.com'
    return setup_settings(abspath('bert_e/tests/assets/settings-env.yml'))
