#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
import datetime

from . import bitbucket_api


"""
TODOs: turn this script into a part of the Bert-E CLI.
This is for manual usage for now.
"""


def list_pull_requests(r, key):

    for i in r.get_pull_requests():
        try:
            p = r.get_build_status(revision=i['source']['commit']['hash'],
                                   key=key)
            updated = datetime.datetime.strptime(i['updated_on'],
                                                 '%Y-%m-%dT%H:%M:%S.%f+00:00')
            lastxdays = datetime.datetime.now() - datetime.timedelta(time)
            if p == "NOTSTARTED" and updated > lastxdays:
                print(i['links']['diff']['href'])
        except Exception:
            raise


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="PRs without build status")
    parser.add_argument('user', action="store", help="Username")
    parser.add_argument('pwd', action="store", help="Password")
    parser.add_argument('email', action="store", help="Email")
    parser.add_argument('--repo', action="store", default='ring', help="Repo")
    parser.add_argument('--owner', action="store", default='scality',
                        help="Repo owner")
    parser.add_argument('--key', action="store", default="pre-merge",
                        help="Pipeline key")
    parser.add_argument('--time', action="store", default="15",
                        help="Go up to x days in the past")
    args = parser.parse_args()

    user = args.user
    pwd = args.pwd
    email = args.email
    repo = args.repo
    owner = args.owner
    key = args.key
    time = int(args.time)

    c = bitbucket_api.Client(user, pwd, email)
    r = bitbucket_api.Repository(c, owner=owner, repo_slug=repo)
    list_pull_requests(r, key)
