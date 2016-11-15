#!/usr/bin/env python
"""A python script that parses the data sent by bitbucket in Json,
and extracts the information required to launch Bert-E.

The information is stored in a filename in the format key:value.

The script returns 0 on success and something else in the case
of failure.
"""
import sys
import json

if __name__ == '__main__':

    if len(sys.argv) != 3:
        print('Error: the script needs two arguments '
              '(properties filename and JSON string).')
        sys.exit(1)

    prop_file = sys.argv[1]
    data = sys.argv[2]

    try:
        with open(data, 'r') as f:
            json_data = json.load(f)
    except ValueError:
        print('Error: input is not recognised as a valid JSON format:')
        print(data)
        sys.exit(1)

    with open(prop_file, "w") as f:
        try:
            pr_id = json_data['pullrequest']['id']
        except KeyError:
            print('Error: could not find a valid pull request in the JSON.')
            json.dumps(json_data, indent=4)
            sys.exit(1)
        print('found PULL_REQUEST_ID: %s' % pr_id)
        f.write("PULL_REQUEST_ID:%s\n" % pr_id)

        try:
            full_name = json_data['repository']['full_name']
        except KeyError:
            print('Error: could not find the repository in the JSON.')
            json.dumps(json_data, indent=4)
            sys.exit(1)

        owner, slug = full_name.split('/')

        print('found REPOSITORY_SLUG: %s' % slug)
        f.write("REPOSITORY_SLUG:%s\n" % slug)

        print('found REPOSITORY_OWNER: %s' % owner)
        f.write("REPOSITORY_OWNER:%s\n" % owner)

    sys.exit(0)
