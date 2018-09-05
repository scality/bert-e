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

"""This module defines the server authentication."""

from functools import wraps

from authlib.flask.client import OAuth, RemoteApp
from flask import Blueprint, Response, current_app, jsonify, \
    request, session, url_for, redirect
from loginpass import Bitbucket, GitHub, create_flask_blueprint
from loginpass._core import register_to


def invalid(message='The request is invalid for that endpoint.'):
    """Sends a 400 response."""
    return Response(message, 400)


def authenticate():
    """Sends a 401 response."""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials.', 401)


def unauthorized():
    """Sends a 403 response."""
    return Response(
        'You are not authorized to access that resource.\n'
        'You have to login with sufficient privileges.', 403)


def authenticate_basic():
    """Sends a 401 response and triggers basic auth prompt."""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})


def check_basic_auth(username, password):
    """Checks username/password combination is valid."""
    return username == current_app.config['WEBHOOK_LOGIN'] and \
        password == current_app.config['WEBHOOK_PWD']


def requires_basic_auth(func):
    """Decorator to require basic auth on selected operations."""
    @wraps(func)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_basic_auth(auth.username, auth.password):
            return authenticate_basic()
        return func(*args, **kwargs)
    return decorated


def requires_auth(admin=False):
    """Decorator to require auth on decorated endpoints.

    Args:
      - admin (bool): When True, the authentication is accepted
        if and only if the admin flag of the session has been set
        to True.

    """
    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            if not session.get('user'):
                return unauthorized()

            user_admin = session.get('admin')
            if admin and not user_admin:
                return unauthorized()

            return func(*args, **kwargs)
        return decorated
    return decorator


def _handle_authorize(bert_e, user_info):
    """Parse user identification and configure session.

    This method is called once the OAuth identification process has
    completed. The provided user information is checked to determine
    if the session is authorized or not, and if so, the level of
    access is also set.

    If Bert-E is configured with the field 'organization', the user
    email is checked before authorizing access.

    If authorized, the session is updated with fields 'user' (a copy
    of the Git host user handle); The session is also updated with an
    'admin' flag.  This flag is set to True if the handle of the user
    belongs to the list of admins as configured in Bert-E's settings.

    Args:
      - bert_e: unique instance of running Bert-E
      - user_info (dict): normalized loginpass user information

    """
    user = user_info.get('preferred_username', None)
    if not user:
        return unauthorized()

    org = bert_e.settings.organization
    if org:
        email = user_info.get('email', None)
        if not email or not email.endswith('@{}'.format(org)):
            return unauthorized()

    session['user'] = user
    session['admin'] = user in bert_e.settings.admins

    if request.is_json:
        return jsonify(user_info), 200, {'Content-Type': 'text/json'}

    return redirect(url_for('status page.display'), code=302)


def configure(app):
    """Configure OAuth and register auth blueprint."""
    def handle_authorize(remote, token, user_info):
        return _handle_authorize(app.bert_e, user_info)

    # configure web oauth
    if app.bert_e.settings.repository_host == 'github':
        backend = GitHub
        app.config['GITHUB_CLIENT_ID'] = app.config['CLIENT_ID']
        app.config['GITHUB_CLIENT_SECRET'] = app.config['CLIENT_SECRET']
    else:
        backend = Bitbucket
        app.config['BITBUCKET_CLIENT_ID'] = app.config['CLIENT_ID']
        app.config['BITBUCKET_CLIENT_SECRET'] = app.config['CLIENT_SECRET']

    oauth = OAuth(app)
    bp = create_flask_blueprint(backend, oauth, handle_authorize)
    app.register_blueprint(bp)

    # create additional path for token based authentication
    bp = Blueprint('auth', __name__)
    remote = register_to(backend, oauth, RemoteApp)

    @bp.route('/api/auth')
    def api_auth():
        access_token = request.args.get('access_token')
        if access_token:
            token = {'access_token': access_token, 'token_type': 'bearer'}
            user_info = remote.profile(token=token)
            return handle_authorize(remote, access_token, user_info)
        return unauthorized()

    @bp.route('/logout')
    def logout():
        session.pop('user')
        session.pop('admin')
        return redirect(url_for('status page.display'))

    app.register_blueprint(bp)
