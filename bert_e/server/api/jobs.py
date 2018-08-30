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

from flask import abort, current_app, jsonify

from .base import APIEndpoint


class GetJob(APIEndpoint):
    rule = '/jobs/<string:job_id>'
    method = 'GET'
    admin = False

    def view(self, job_id):
        job = current_app.bert_e.get_job_as_dict(job_id)
        if job is None:
            abort(404)
        return jsonify(job), 200, {'Content-Type': 'text/json'}


class ListJobs(APIEndpoint):
    rule = '/jobs'
    method = 'GET'
    admin = False

    def view(self):
        jobs = current_app.bert_e.get_jobs_as_dict()
        return jsonify(jobs), 200, {'Content-Type': 'text/json'}
