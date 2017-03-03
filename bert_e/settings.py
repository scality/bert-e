from os.path import exists

import yaml
from marshmallow import Schema, fields, post_load

from bert_e.exceptions import (IncorrectSettingsFile, MalformedSettings,
                               SettingsFileNotFound)
from bert_e.lib.settings_dict import SettingsDict


class PrefixesSchema(Schema):
    Story = fields.Str(allow_none=True)
    Bug = fields.Str(allow_none=True)
    Improvement = fields.Str(allow_none=True)


class SettingsSchema(Schema):
    # Settings defined in config files
    repository_owner = fields.Str(required=True)
    repository_slug = fields.Str(required=True)
    repository_host = fields.Str(required=True)

    robot_username = fields.Str(required=True)
    robot_email = fields.Str(required=True)

    pull_request_base_url = fields.Str(required=True)
    commit_base_url = fields.Str(required=True)

    build_key = fields.Str(missing="pre-merge")

    need_author_approval = fields.Bool(missing=True)
    required_peer_approvals = fields.Int(missing=2)

    jira_account_url = fields.Str(missing='')
    jira_username = fields.Str(missing='')
    jira_keys = fields.List(fields.Str(), missing=[])

    prefixes = fields.Nested(PrefixesSchema, missing={})

    admins = fields.List(fields.Str(), missing=[])
    testers = fields.List(fields.Str(), missing=[])
    tasks = fields.List(fields.Str(), missing=[])

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

    return settings
