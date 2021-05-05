from os.path import exists

import yaml
import logging
from marshmallow import Schema, fields, post_load, pre_load

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


class Username(fields.Str):
    def _deserialize(self, value, attr, data, **kwargs):
        return value.lower()


class UserDict(SettingsDict):

    def __repr__(self):
        repr = "<User(username=%s, account_id=%s)>" %\
            (self.username, self.account_id)
        return repr

    def __hash__(self):
        if self.account_id:
            return hash(self.account_id)
        return hash(self.username)

    def __str__(self):
        return str(self.username)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            if other.account_id and self.account_id:
                return other.account_id == self.account_id
            return other.username == self.username

        elif isinstance(other, str):
            return other == self.account_id or other == self.username
        else:
            raise ValueError('Comparing %s with %s' %
                             (self.__class__, type(other)))

    def lower(self):
        return self.__str__().lower()


class UserSettingSchema(Schema):
    username = Username(required=True)
    account_id = fields.Str(required=False, missing=None)

    @pre_load
    def split_usernames(self, username):
        data = iter(username.split('@'))
        user = dict(username=None, account_id=None)
        user['username'] = next(data, None)
        user['account_id'] = next(data, None)
        return user

    @post_load
    def output(self, data):
        return UserDict(data)


class PrAuthorsOptions(fields.Dict):
    BYPASS_LIST = [
        'bypass_author_approval',
        'bypass_jira_check',
        'bypass_build_status',
        'bypass_commit_size',
        'bypass_incompatible_branch',
        'bypass_peer_approval',
        'bypass_leader_approval',
    ]

    def serialize(self, value, attr=None, obj=None):
        data = super(PrAuthorsOptions, self).serialize(value, attr, obj)
        res = dict()
        for user, values in data.items():
            res[user] = [key for key, value in data.items() if value]

        return res

    def deserialize(self, value, attr=None, data=None):
        data = super(PrAuthorsOptions, self).deserialize(value, attr, data)

        found_elem = []
        res = dict()
        for user, bypass_list in data.items():
            for elem in bypass_list:
                if elem in self.BYPASS_LIST:
                    found_elem.append(elem)
                else:
                    raise IncorrectSettingsFile(
                        f'This bypass does not exist: {elem}'
                    )

            res[user] = dict([
                (key, key in bypass_list) for key in self.BYPASS_LIST
            ])
        return res


class SettingsSchema(Schema):
    # Settings defined in config files
    always_create_integration_pull_requests = fields.Bool(missing=True)

    frontend_url = fields.Str(missing='')

    repository_owner = fields.Str(required=True)
    repository_slug = fields.Str(required=True)
    repository_host = fields.Str(required=True)

    robot = fields.Nested(UserSettingSchema, required=True)
    robot_email = fields.Str(required=True)

    pull_request_base_url = fields.Str(required=True)
    commit_base_url = fields.Str(required=True)

    build_key = fields.List(fields.Str(), missing=["pre-merge"])

    need_author_approval = fields.Bool(missing=True)
    required_leader_approvals = fields.Int(missing=0)
    required_peer_approvals = fields.Int(missing=2)
    pr_author_options = PrAuthorsOptions(missing={})

    jira_account_url = fields.Str(missing='')
    jira_email = fields.Str(missing='')
    jira_keys = fields.List(fields.Str(), missing=[])

    prefixes = fields.Dict(missing={})
    bypass_prefixes = fields.List(fields.Str(), missing=[])

    disable_version_checks = fields.Bool(missing=False)

    organization = fields.Str(fields.Str(), missing='')
    admins = fields.Nested(UserSettingSchema, many=True, missing=[])
    project_leaders = fields.Nested(UserSettingSchema, many=True, missing=[])
    tasks = fields.List(fields.Str(), missing=[])

    max_commit_diff = fields.Int(missing=0)

    sentry_dsn = fields.Str(missing='')

    bitbucket_addon_base_url = fields.Str(missing='')
    bitbucket_addon_client_id = fields.Str(missing='')
    bitbucket_addon_url = fields.Str(missing='')

    # Settings coming from CLI arguments
    robot_password = fields.Str(missing='')
    jira_token = fields.Str(missing='')

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
