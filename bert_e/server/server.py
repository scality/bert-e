#!/usr/bin/env python3

# Copyright 2016-2018 Scality
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

"""Runner for Bert-E Flask server."""

import argparse

from . import setup_bert_e, setup_server


def parse_args():
    """Read command line arguments for server."""
    parser = argparse.ArgumentParser(
        add_help=True,
        description='Bert-E debug server.'
    )

    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='server host (defaults to 0.0.0.0)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='server port (defaults to 5000)')
    parser.add_argument('--settings-file', '-f', type=str, default='settings',
                        help='settings-file location (defaults to `settings`')
    parser.add_argument('--verbose', '-v', action='store_true', default=True,
                        help='verbose mode')

    return parser.parse_args()


# Start up Bert-E and server!
args = parse_args()
bert_e = setup_bert_e(args.settings_file, args.verbose)
app = setup_server(bert_e)


def main():
    """Debug server entry point."""
    app.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    main()
