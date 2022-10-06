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

from authlib.integrations.flask_client import OAuth, LocalProxy

from flask import Response, current_app, \
    render_template, request, session, url_for, redirect


def invalid(message='The request is invalid for that endpoint.'):
    """Sends a 400 response."""
    if request.is_json:
        return message, 400

    return render_template(
        'error.html',
        navigation=request.args.get('navoff', True),
        error_msg=message
    ), 400


def authenticate(message='Unauthorized.'):
    """Sends a 401 response."""
    if request.is_json:
        return message, 401

    return render_template(
        'error.html',
        navigation=request.args.get('navoff', True),
        error_msg=message
    ), 401


def unauthorized(message="Forbidden."):
    """Sends a 403 response."""
    if request.is_json:
        return message, 403

    return render_template(
        'error.html',
        navigation=request.args.get('navoff', True),
        error_msg=message
    ), 403


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
                return authenticate('You are not logged in.')

            user_admin = session.get('admin')
            if admin and not user_admin:
                return unauthorized('You do not have admin privileges.')

            return func(*args, **kwargs)
        return decorated
    return decorator


def github_handle_authorize(auth: LocalProxy, token, owner, slug):
    """Parse user identification and configure session.

    This method is called once the OAuth identification process has
    completed. The provided user information is checked to determine
    if the session is authorized or not, and if so, the level of
    access is also set.

    If authorized, the session is updated with fields 'user' (a copy
    of the Git host user handle); The session is also updated with an
    'admin' flag.  This flag is set to True if the handle of the user
    posess admin rights on the repository or belongs
    to the list of admins as configured in Bert-E's settings.

    Args:
      - auth: oauth LocalProxy
      - token: User token
      - owner: the owner of the repository
      - slug: name of the repository configured with Bert-E

    """

    profile = auth.get('user', token=token).json()
    repo = auth.get(
        f'/repos/{owner}/{slug}',
        token=token).json()
    permissions = repo.get('permissions')
    if permissions.get('push', False) is False:
        return unauthorized('The user does not have write access to the repository')

    session['user'] = profile.get('login').lower()
    # TODO support admins key
    session['admin'] = permissions.get('admin', False)

    return redirect(url_for('status page.display'), code=302)


def configure(app):
    """Configure OAuth"""

    oauth = OAuth(app)
    if app.bert_e.settings.repository_host == 'github':
        app.config['GITHUB_CLIENT_ID'] = app.config['CLIENT_ID']
        app.config['GITHUB_CLIENT_SECRET'] = app.config['CLIENT_SECRET']

        auth = oauth.register(
            name=app.bert_e.settings.repository_host,
            access_token_url='https://github.com/login/oauth/access_token',
            authorize_url='https://github.com/login/oauth/authorize',
            api_base_url='https://api.github.com/',
            client_kwargs={'scope': 'user:email read:org'},
        )
        handle_authorize = github_handle_authorize
    else:
        raise Exception('Repository oauth is not supported')

    owner = app.bert_e.settings.repository_owner
    slug = app.bert_e.settings.repository_slug

    @app.route('/login')
    def login():
        redirect_url = url_for("authorize", _external=True)
        return auth.authorize_redirect(redirect_url)

    @app.route("/authorize")
    def authorize():
        token = auth.authorize_access_token()
        return handle_authorize(auth, token, owner, slug)

    @app.route('/api/auth')
    def api_auth():
        access_token = request.args.get('access_token')
        if access_token:
            token = {'access_token': access_token, 'token_type': 'bearer'}
            return handle_authorize(auth, token, owner, slug)
        return unauthorized('Missing access token in request.')

    @app.route('/logout')
    def logout():
        session.pop('user')
        session.pop('admin')
        return redirect(url_for('status page.display'))
