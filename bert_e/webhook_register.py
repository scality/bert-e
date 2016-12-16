#!/usr/bin/env python

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

""" A simple script used to register the Bitbucket WebHook required by Bert-E.

    It needs credentials that have the permission to add/delete webhooks
"""
from . import bitbucket_api
import argparse

EVENTS = (
    # 'issue:created',
    # 'issue:comment_created',
    # 'issue:updated',

    # 'project:updated',

    'pullrequest:created',
    'pullrequest:updated',
    'pullrequest:approved',
    'pullrequest:unapproved',
    'pullrequest:rejected',
    'pullrequest:fulfilled',

    'pullrequest:comment_created',
    'pullrequest:comment_updated',
    'pullrequest:comment_deleted',

    # 'repo:fork',
    # 'repo:imported',
    # 'repo:updated',
    # 'repo:deleted',
    # 'repo:push',

    'repo:commit_status_created',
    'repo:commit_status_updated',
    # 'repo:commit_comment_created',
)


def main():
    parser = argparse.ArgumentParser(description='Launches Bert-E tests.')
    parser.add_argument('repo_owner',
                        help='The repo owner')
    parser.add_argument('repo_slug',
                        help='The repo slug')
    parser.add_argument('url',
                        help='The url to send webhooks to, '
                             'e.g., http://login:password@example.com:5000')
    parser.add_argument('login',
                        help='Your bitbucket login')
    parser.add_argument('password',
                        help='Your bitbucket password')
    args = parser.parse_args()

    request = {
        'url': args.url,
        'active': True,
        'events': EVENTS,
        'description': 'Bert-E',

    }
    bbconn = bitbucket_api.Client(args.login, args.password, None)
    bbrepo = bitbucket_api.Repository(bbconn, owner=args.repo_owner,
                                      repo_slug=args.repo_slug)

    bbrepo.delete_webhooks_with_title('Bert-E')
    bbrepo.create_webhook(**request)


if __name__ == '__main__':
    main()
