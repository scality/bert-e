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

"""Template filter functions for Bert-E server."""

from ..git_host.cache import BUILD_STATUS_CACHE


def configure(app):
    """Configure extra template filters for Bert-E Flask server."""

    def pr_url_filter(id_or_revision):
        """Transform a pull request id/commit sha1 into a link to Git host."""
        config = app.bert_e.settings
        if len(str(id_or_revision)) in [12, 40]:
            return config.commit_base_url.format(commit_id=id_or_revision)
        else:
            return config.pull_request_base_url.format(pr_id=id_or_revision)

    def build_url_filter(sha1):
        """Transform a commit sha1 into a link to the CI build."""
        build_key = app.bert_e.settings.build_key
        status = BUILD_STATUS_CACHE[build_key].get(sha1, None)
        return status.url if status else ''

    app.jinja_env.filters['pr_url'] = pr_url_filter
    app.jinja_env.filters['build_url'] = build_url_filter
