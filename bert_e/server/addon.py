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

"""This module defines the server webhook endpoints."""

import logging
import os

from flask import abort, Blueprint, current_app, render_template

LOG = logging.getLogger(__name__)
APPLICATION_ROOT = os.getenv('APPLICATION_ROOT', '/')
blueprint = Blueprint('Bert-E server githost addon endpoints', __name__,
                      url_prefix=APPLICATION_ROOT)


@blueprint.route('/install-bitbucket-addon', methods=['GET'])
def bitbucket_addon():
    if current_app.bert_e.settings.repository_host != 'bitbucket':
        abort(404)

    if (not current_app.bert_e.settings.bitbucket_addon_base_url or
            not current_app.bert_e.settings.bitbucket_addon_client_id or
            not current_app.bert_e.settings.bitbucket_addon_url):
        abort(404)

    return render_template(
        'bitbucket_addon.json',
        base_url=current_app.bert_e.settings.bitbucket_addon_base_url,
        client_id=current_app.bert_e.settings.bitbucket_addon_client_id,
        url=current_app.bert_e.settings.bitbucket_addon_url,
    ), 200, {'Content-Type': 'application/json'}
