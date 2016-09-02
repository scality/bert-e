#!/usr/bin/env python
""" A simple script used to register the Bitbucket WebHook required by Wall-E.

    It needs credentials that have the permission to add/delete webhooks
"""
import bitbucket_api
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
    'repo:push',

    'repo:commit_status_created',
    'repo:commit_status_updated',
    'repo:commit_comment_created',
)


def main():
    parser = argparse.ArgumentParser(description='Launches Wall-E tests.')
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
        'description': 'Wall-E',

    }
    bbconn = bitbucket_api.Client(args.login, args.password, None)
    bbrepo = bitbucket_api.Repository(bbconn, owner=args.repo_owner,
                                      repo_slug=args.repo_slug)

    bbrepo.delete_webhooks_with_title('Wall-E')
    bbrepo.create_webhook(**request)


if __name__ == '__main__':
    main()
