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
"""Jobs implementation.

In Bert-E, a job is triggered in reaction of an event, and holds all the
possibly short-lived information needed to process it.

"""

from types import SimpleNamespace
from typing import Callable

from bert_e.lib.dispatcher import Dispatcher
from bert_e.lib.settings_dict import SettingsDict


class Job:
    """Generic job class."""
    def __init__(self, bert_e, settings={}):
        self.bert_e = bert_e
        self.settings = SettingsDict(settings, bert_e.settings)

    @property
    def active_options(self):
        return [key for key, val in self.settings.maps[0].items() if val]

    def __str__(self):
        return repr(self)


class RepoJob(Job):
    """Job related to a repository."""
    def __init__(self, project_repo=None, git_repo=None, **kwargs):
        super().__init__(**kwargs)
        self.project_repo = project_repo or self.bert_e.project_repo
        self.git = SimpleNamespace(
            repo=git_repo or self.bert_e.git_repo, cascade=None
        )


class PullRequestJob(RepoJob):
    """Job triggered when a pull request was updated."""
    def __init__(self, pull_request, **kwargs):
        super().__init__(**kwargs)
        self.pull_request = pull_request
        self.git.src_branch = None
        self.git.dst_branch = None

    def __str__(self):
        return "PullRequestJob(repo={}/{}, id={})".format(
            self.project_repo.owner, self.project_repo.slug,
            self.pull_request.id)


class CommitJob(RepoJob):
    """Job triggered when a commit status was updated."""
    def __init__(self, commit, **kwargs):
        super().__init__(**kwargs)
        self.commit = commit


class QueuesJob(RepoJob):
    """Job triggered when the queues were updated."""
    def __str__(self):
        return "QueuesJob"


class JobDispatcher(Dispatcher):
    """Base dispatcher class that handles jobs."""
    @classmethod
    def set_callback(cls, job_class: type, callback: Callable) -> Callable:
        """Register a new handler to the dispatcher class.

        Raises:
            - TypeError if the key isn't a Job subclass.

        """
        if not issubclass(job_class, Job):
            raise TypeError(
                "{} is not a Job subclass".format(job_class.__name__)
            )
        cls.__callbacks__[job_class] = callback
        return callback

    def dispatch(self, job, default=None):
        """Dispatch a job and process it with the right method.

        This method supports inheritance: if there is no callback registered
        for this job's class, walk the inheritance tree up (using Python's
        method resolution order) and call the callback for the first registered
        parent.

        Raises:
            - TypeError if no handler can be found.

        """
        # Loop on method resolution order list to find the closest managed
        # parent.
        for base in type(job).__mro__:
            handler = super().dispatch(base, default)
            if handler:
                return handler(job)

        raise TypeError("No handler for job {}".format(job))


handler = JobDispatcher.register
