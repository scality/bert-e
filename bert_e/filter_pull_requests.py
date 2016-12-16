#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2016 Scality
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import re
import six
import logging

from .bitbucket_api import (Repository as BitBucketRepository,
                            Client)

if six.PY2:
    import sys
    import codecs

fields = {
    'author': ['author/username', 'author/display_name'],
    'close_source_branch': ['close_source_branch'],
    'title': ['title'],
    'destination': ['destination/branch/name'],
    'source': ['branch/name'],
    'state': ['state'],
    'created_on': ['created_on'],
    'updated_on': ['updated_on']
}


def filter_pr(your_login, your_password, your_mail, owner, slug, **kwargs):
    """Because Atlassian does not have a pull request search feature"""

    client = Client(your_login, your_password, your_mail)
    bbrepo = BitBucketRepository(client, owner=owner, repo_slug=slug)
    pr_list = []

    for pr in bbrepo.get_pull_requests():
        pr_match = True
        for field_name, data_accessessors in fields.items():
            regex = kwargs[field_name]
            if not regex:
                continue
            field_match = False
            for data_accessessor in data_accessessors:
                x = pr
                for accessessor_item in data_accessessor.split('/'):
                    x = x[accessessor_item]
                if re.search(regex, x, flags=re.IGNORECASE):
                    field_match = True
                    break
            pr_match = pr_match and field_match
            if not field_match:
                break

        if not pr_match:
            continue

        pr_id = ('%s (%s) [%s]->[%s]https://bitbucket.org'
                 '/%s/%s/pull-requests/%s'
                 % (pr['id'],
                    pr['author']['display_name'],
                    pr['source']['branch']['name'],
                    pr['destination']['branch']['name'],
                    owner,
                    slug,
                    pr['id']))
        pr_list.append(pr_id)
    return pr_list


def main():
    parser = (argparse
              .ArgumentParser(description='Searches for pull requests.'))

    for field_name, data_accessed in fields.items():
        parser.add_argument('--' + field_name,
                            help='Regular expression for the %s field'
                                 % field_name)

    parser.add_argument('your_login',
                        help='Your Bitbucket login')
    parser.add_argument('your_password',
                        help='Your Bitbucket password')
    parser.add_argument('your_mail',
                        help='Your Bitbucket email address')
    parser.add_argument('owner',
                        help='The owner of the repo')
    parser.add_argument('slug',
                        help='The repo\'s slug')

    args = vars(parser.parse_args())
    logging.info(filter_pr(**args))


if __name__ == '__main__':
    if six.PY2:
        sys.stdout = (codecs
                      .getwriter('utf8')(sys.stdout))  # required for piping
    main()
