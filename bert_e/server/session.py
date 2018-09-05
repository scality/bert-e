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

"""helper functions for Bert-E server sessions."""

from flask_session import Session


def configure(app):
    """Configure sessions for Bert-E's Flask server."""
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = '/tmp/bert-e-sessions'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_FILE_THRESHOLD'] = 500
    Session(app)
