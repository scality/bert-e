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

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4 as uuid

from marshmallow import Schema, fields

from bert_e.lib.dispatcher import Dispatcher
from bert_e.lib.settings_dict import SettingsDict
from bert_e.lib.schema import dumps as dump_schema


class JobSchema(Schema):
    id = fields.UUID(dump_only=True)
    start_time = fields.DateTime(dump_only=True)
    end_time = fields.DateTime(dump_only=True, allow_none=True)
    status = fields.Str(dump_only=True, allow_none=True)
    details = fields.Str(dump_only=True, allow_none=True)
    url = fields.Url(dump_only=True, allow_none=True)
    settings = fields.Dict()


class Job:
    """Generic job class."""
    def __init__(self, bert_e, settings=None, url=''):
        settings = settings or {}
        self.id = uuid()
        self.bert_e = bert_e
        self.settings = SettingsDict(settings, bert_e.settings)
        self.start_time = datetime.now()
        self.end_time = None
        self.status = ''
        self.details = ''
        self.external_url = url

    def complete(self):
        self.end_time = datetime.now()

    @property
    def duration(self) -> timedelta:
        if not self.end_time:
            return datetime.now() - self.start_time
        else:
            return self.end_time - self.start_time

    @property
    def url(self) -> str:
        return self.external_url

    @property
    def active_options(self):
        return [key for key, val in self.settings.maps[0].items() if val]

    @property
    def done(self):
        return self.end_time is not None

    def json(self):
        return dump_schema(JobSchema, {
            'id': self.id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'status': self.status,
            'details': self.details,
            'url': self.url,
            'settings': self.settings.maps[0]
        })

    def __str__(self):
        return '{}(id={})'.format(type(self).__name__, self.id)

    def __repr__(self):
        return "{}({})".format(
            self.__class__.__name__,
            ''.join((
                str(self),
                ', start_time={}'.format(self.start_time),
                ', url={}'.format(self.url) if self.url else ''
            ))
        )


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
        return "Webhook PR #{}".format(self.pull_request.id)

    def __eq__(self, other):
        return (isinstance(other, PullRequestJob) and
                self.project_repo.full_name == other.project_repo.full_name and
                self.pull_request.id == other.pull_request.id)


class CommitJob(RepoJob):
    """Job triggered when a commit status was updated."""
    def __init__(self, commit, **kwargs):
        super().__init__(**kwargs)
        self.commit = commit

    def __str__(self):
        return "Commit {}".format(self.commit)

    def __eq__(self, other):
        return (isinstance(other, CommitJob) and
                self.project_repo.full_name == other.project_repo.full_name and
                self.commit == other.commit)


class QueuesJob(RepoJob):
    """Job triggered when the queues were updated."""
    def __str__(self):
        return "QueuesJob"


class APIJob(RepoJob):
    """Command sent to Bert-E via its API."""
    def __init__(self, args=None, kwargs=None, **kwargs_):
        super().__init__(**kwargs_)
        self.args = args or []
        self.kwargs = kwargs or {}


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
