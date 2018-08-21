from os.path import exists

import yaml
import logging
from marshmallow import Schema, fields, post_load

from bert_e.exceptions import (IncorrectSettingsFile, MalformedSettings,
                               SettingsFileNotFound)
from bert_e.lib.settings_dict import SettingsDict


class BertEContextFilter(logging.Filter):
    """This is a filter which will inject Bert-E contextual
    information into the log.

    """
    def __init__(self, settings):
        self.settings = settings

    def filter(self, record):
        record.instance = "{host}-{owner}-{slug}".format(
            host=self.settings['repository_host'],
            owner=self.settings['repository_owner'],
            slug=self.settings['repository_slug']
        )
        return True


class SettingsSchema(Schema):
    # Settings defined in config files
    always_create_integration_pull_requests = fields.Bool(missing=True)

    repository_owner = fields.Str(required=True)
    repository_slug = fields.Str(required=True)
    repository_host = fields.Str(required=True)

    robot_username = fields.Str(required=True)
    robot_email = fields.Str(required=True)

    pull_request_base_url = fields.Str(required=True)
    commit_base_url = fields.Str(required=True)

    build_key = fields.Str(missing="pre-merge")

    need_author_approval = fields.Bool(missing=True)
    required_leader_approvals = fields.Int(missing=0)
    required_peer_approvals = fields.Int(missing=2)

    jira_account_url = fields.Str(missing='')
    jira_username = fields.Str(missing='')
    jira_keys = fields.List(fields.Str(), missing=[])

    prefixes = fields.Dict(missing={})
    bypass_prefixes = fields.List(fields.Str(), missing=[])

    organization = fields.Str(fields.Str(), missing='')
    admins = fields.List(fields.Str(), missing=[])
    project_leaders = fields.List(fields.Str(), missing=[])
    tasks = fields.List(fields.Str(), missing=[])

    max_commit_diff = fields.Int(missing=0)

    sentry_dsn = fields.Str(missing='')

    # Settings coming from CLI arguments
    robot_password = fields.Str(missing='')
    jira_password = fields.Str(missing='')

    backtrace = fields.Bool(missing=False)
    interactive = fields.Bool(missing=False)
    no_comment = fields.Bool(missing=False)
    quiet = fields.Bool(missing=False)
    disable_queues = fields.Bool(missing=False)
    use_queues = fields.Bool(missing=True)
    cmd_line_options = fields.List(fields.Str(), missing=[])

    @post_load
    def mk_settings(self, data):
        return SettingsDict(data)


def setup_settings(settings_file: str) -> dict:
    """Load and checks settings from a yaml file.

    Args:
        - settings_file (str): path of the yaml file to load.

    Raises:
        - SettingsFileNotFound
        - IncorrectSettingsFile if the yaml syntax can't be parsed
        - MalformedSettings if one or more fields from the settings are
                            incorrect (wrong types or missing values)

    Returns:
        The settings as a deserialized yaml object.

    """
    if not exists(settings_file):
        raise SettingsFileNotFound(settings_file)

    with open(settings_file, 'r') as f:
        try:
            # read the yaml data as pure string (no conversion)
            data = yaml.load(f, Loader=yaml.BaseLoader)
        except Exception as err:
            raise IncorrectSettingsFile(settings_file) from err

    settings, errors = SettingsSchema().load(data)
    if errors:
        raise MalformedSettings(settings_file, errors, data)

    # beyond individual setting validity,
    # check now for inter-settings validity

    if (settings['required_leader_approvals'] >
            settings['required_peer_approvals']):
        errors['required_leader_approvals'] = [
            'required_peer_approvals must be equal to, '
            'or exceed, required_leader_approvals'
        ]

    if (settings['required_leader_approvals'] >
            len(settings['project_leaders'])):
        errors['required_leader_approvals'] = [
            'the number of project leaders must be equal to, '
            'or exceed, the value of required_leader_approvals'
        ]

    if errors:
        raise MalformedSettings(settings_file, errors, data)

    return settings
