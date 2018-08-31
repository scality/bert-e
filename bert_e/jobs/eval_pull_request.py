# Copyright 2017 Scality
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

from bert_e import exceptions
from bert_e.job import APIJob, PullRequestJob, handler


class EvalPullRequestJob(APIJob):
    """Job that will evaluate a single pull request."""
    def __init__(self, pr_id, **kwargs):
        super().__init__(**kwargs)
        self.pr_id = pr_id

    @property
    def url(self) -> str:
        return self.bert_e.settings.pull_request_base_url.format(
            pr_id=self.pr_id)

    def __str__(self):
        return "Evaluate PR #{}".format(self.pr_id)


@handler(EvalPullRequestJob)
def evaluate_pull_request(job: EvalPullRequestJob):
    """Evaluate a single pull request."""
    try:
        pr = job.project_repo.get_pull_request(job.pr_id)
    except Exception:
        raise exceptions.JobFailure('Pull request %s was not found.' %
                                    job.pr_id)

    job.bert_e.process(
        PullRequestJob(
            bert_e=job.bert_e,
            pull_request=pr
        )
    )
