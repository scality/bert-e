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

"""Setup functions for Bert-E Flask server."""

import logging
import os
from pkg_resources import get_distribution
import secrets
from threading import Thread

from flask import Flask, render_template, request

from ..bert_e import BertE
from ..settings import setup_settings, BertEContextFilter
from .addon import blueprint as addon_blueprint
from .api import configure as configure_api
from .auth import configure as configure_auth
from .doc import (blueprint as doc_blueprint,
                  configure as configure_doc)
from .manage import blueprint as manage_blueprint
from .reverse_proxy import ReverseProxied
from .session import configure as configure_sessions
from .status import blueprint as status_blueprint
from .template_filter import configure as configure_filters
from .webhook import blueprint as webhook_blueprint


def setup_bert_e(settings_file, debug):
    """Create and configure Bert-E instance."""
    settings = setup_settings(settings_file)
    settings['robot_password'] = os.environ['BERT_E_GITHOST_PWD']
    settings['jira_token'] = os.environ['BERT_E_JIRA_TOKEN']
    settings['backtrace'] = True

    bert_e = BertE(settings)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(instance)s - %(levelname)-8s - %(name)s: %(message)s'
    )
    log_filter = BertEContextFilter(settings)
    for handler in logging.root.handlers:
        handler.addFilter(log_filter)

    def bert_e_launcher():
        """Basic worker loop that waits for Bert-E jobs and launches them."""
        while True:
            bert_e.process_task()

    worker = Thread(target=bert_e_launcher)
    worker.daemon = True
    worker.start()

    return bert_e


def setup_server(bert_e):
    """Create and configure Flask server app."""
    app = Flask(__name__)

    app.config.update({
        'WEBHOOK_LOGIN': os.environ['WEBHOOK_LOGIN'],
        'WEBHOOK_PWD': os.environ['WEBHOOK_LOGIN'],
        'CLIENT_ID': os.environ['BERT_E_CLIENT_ID'],
        'CLIENT_SECRET': os.environ['BERT_E_CLIENT_SECRET'],
        'WTF_CSRF_SECRET_KEY': secrets.token_hex(24),
    })

    app_prefix = os.getenv('APP_PREFIX', '/')

    app.wsgi_app = ReverseProxied(app.wsgi_app, app_prefix)

    app.bert_e = bert_e

    configure_filters(app)
    configure_sessions(app)
    configure_auth(app)
    configure_api(app)
    configure_doc(app)

    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(status_blueprint)
    app.register_blueprint(manage_blueprint)
    app.register_blueprint(doc_blueprint)
    app.register_blueprint(addon_blueprint)

    @app.context_processor
    def inject_global_vars():
        try:
            version = get_distribution('bert_e').version
        except Exception:
            version = 'unset_version'

        return {
            'bert_e_version': version,
            'githost': bert_e.settings.repository_host,
            'owner': bert_e.settings.repository_owner,
            'slug': bert_e.settings.repository_slug,
        }

    @app.errorhandler(404)
    def not_found(e):
        """Sends a 404 response."""
        if request.is_json:
            return 'not found', 404

        return render_template(
            'error.html',
            navigation=request.args.get('navoff', True),
            error_msg='Page not found.'
        ), 404

    return app
