#!/usr/bin/env python3

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
import logging
import os
from threading import Thread

from . import server
from .bert_e import BertE
from .settings import setup_settings, BertEContextFilter


def serve():
    """Program entry point."""
    parser = argparse.ArgumentParser(
        add_help=True,
        description='Handles webhook calls.'
    )

    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='server host (defaults to 0.0.0.0)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='server port (defaults to 5000)')
    parser.add_argument('--settings-file', '-f', type=str, required=True,
                        help='settings-file location')
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='verbose mode')

    args = parser.parse_args()

    settings = setup_settings(args.settings_file)
    settings['robot_password'] = os.environ['BERT_E_BB_PWD']
    settings['jira_password'] = os.environ['BERT_E_JIRA_PWD']
    settings['backtrace'] = True

    server.BERTE = BertE(settings)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(instance)s - %(levelname)-8s - %(name)s: %(message)s'
    )
    log_filter = BertEContextFilter(settings)
    for handler in logging.root.handlers:
        handler.addFilter(log_filter)
    worker = Thread(target=server.bert_e_launcher)
    worker.daemon = True
    worker.start()

    return server.APP.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    serve()
