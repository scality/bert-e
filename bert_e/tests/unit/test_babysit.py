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
"""Tests for the babysit feature."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bert_e.exceptions import BabysitRetry, BabysitExhausted, BabysitCancelled
from bert_e.git_host.github import AggregatedWorkflowRuns, Client
from bert_e.workflow.gitwaterflow.babysit import (
    count_babysit_retries_per_workflow, handle_babysit_retry,
    BABYSIT_RETRY_MARKER, COMMIT_SHA_PATTERN, WORKFLOW_RETRY_PATTERN
)
from bert_e.workflow.gitwaterflow.queueing import (
    _check_pr_babysit_enabled, _handle_queue_babysit_retry
)
# Import setup to register reactor options
from bert_e.workflow.gitwaterflow.commands import setup as gwf_setup

# Call setup to register all options including babysit
gwf_setup()


@pytest.fixture
def client():
    return Client(
        login='login',
        password='password',
        email='email@org.com',
        base_url="http://localhost:4010",
        accept_header="application/json"
    )


@pytest.fixture
def failed_workflow_run_json():
    """Workflow run JSON with failed run on an integration branch."""
    return {
        'workflow_runs': [
            {
                'id': 12345,
                'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3',
                'head_branch': 'w/5.0/feature/test',
                'status': 'completed',
                'event': 'pull_request',
                'workflow_id': 1,
                'check_suite_id': 1,
                'conclusion': 'failure',
                'run_attempt': 2,
                'name': 'CI Build',
                'html_url': 'https://github.com/org/repo/actions/runs/12345',
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {'login': 'octo-org'},
                    'name': 'Hello-World'
                }
            },
        ],
        'total_count': 1
    }


@pytest.fixture
def successful_workflow_run_json():
    """Workflow run JSON with a successful run."""
    return {
        'workflow_runs': [
            {
                'id': 12345,
                'head_sha': 'd6fde92930d4715a2b49857d24b940956b26d2d3',
                'head_branch': 'w/5.0/feature/test',
                'status': 'completed',
                'event': 'pull_request',
                'workflow_id': 1,
                'check_suite_id': 1,
                'conclusion': 'success',
                'run_attempt': 1,
                'name': 'CI Build',
                'repository': {
                    'full_name': 'octo-org/Hello-World',
                    'owner': {'login': 'octo-org'},
                    'name': 'Hello-World'
                }
            },
        ],
        'total_count': 1
    }


class TestGetFailedRuns:
    """Tests for AggregatedWorkflowRuns.get_failed_runs()."""

    def test_get_failed_runs_returns_failed_workflows(
            self, client, failed_workflow_run_json):
        """Test that get_failed_runs returns failed workflow runs."""
        workflow_runs = AggregatedWorkflowRuns(
            client, **failed_workflow_run_json)

        failed_runs = workflow_runs.get_failed_runs()

        assert len(failed_runs) == 1
        assert failed_runs[0]['id'] == 12345
        assert failed_runs[0]['run_attempt'] == 2
        assert failed_runs[0]['workflow_id'] == 1
        assert failed_runs[0]['name'] == 'CI Build'

    def test_get_failed_runs_returns_empty_for_successful(
            self, client, successful_workflow_run_json):
        """Test that get_failed_runs returns empty for successful runs."""
        workflow_runs = AggregatedWorkflowRuns(
            client, **successful_workflow_run_json)

        failed_runs = workflow_runs.get_failed_runs()

        assert len(failed_runs) == 0

    def test_get_failed_runs_default_run_attempt(self, client):
        """Test that run_attempt defaults to 1 if not present."""
        workflow_run_json = {
            'workflow_runs': [
                {
                    'id': 99999,
                    'head_sha': 'abc123',
                    'head_branch': 'feature',
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 1,
                    'check_suite_id': 1,
                    'conclusion': 'failure',
                    # run_attempt not present
                    'repository': {
                        'full_name': 'org/repo',
                        'owner': {'login': 'org'},
                        'name': 'repo'
                    }
                },
            ],
            'total_count': 1
        }
        workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

        failed_runs = workflow_runs.get_failed_runs()

        assert len(failed_runs) == 1
        assert failed_runs[0]['run_attempt'] == 1  # default


class TestPatterns:
    """Tests for regex patterns."""

    def test_commit_sha_pattern_matches_short_sha(self):
        """Test matching a short commit SHA (7 chars)."""
        text = 'branch `w/5.0/test` (commit `abc1234`)'
        match = COMMIT_SHA_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == 'abc1234'

    def test_commit_sha_pattern_matches_full_sha(self):
        """Test matching a full commit SHA (40 chars)."""
        full_sha = 'd6fde92930d4715a2b49857d24b940956b26d2d3'
        text = f'(commit `{full_sha}`)'
        match = COMMIT_SHA_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == full_sha

    def test_commit_sha_pattern_no_match_without_backticks(self):
        """Test that commit without backticks doesn't match."""
        text = '(commit abc1234)'
        match = COMMIT_SHA_PATTERN.search(text)
        assert match is None

    def test_workflow_retry_pattern_matches(self):
        """Test that workflow retry pattern matches table rows."""
        text = '| `CI Build` | 2/5 |'
        match = WORKFLOW_RETRY_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == 'CI Build'
        assert match.group(2) == '2'
        assert match.group(3) == '5'

    def test_workflow_retry_pattern_matches_multiple(self):
        """Test extracting multiple workflows from a table."""
        text = '''| Workflow | Retry |
|:---------|:-----:|
| `CI Build` | 1/5 |
| `Tests` | 3/5 |
| `Lint` | 2/5 |
'''
        matches = list(WORKFLOW_RETRY_PATTERN.finditer(text))
        assert len(matches) == 3
        assert matches[0].group(1) == 'CI Build'
        assert matches[1].group(1) == 'Tests'
        assert matches[2].group(1) == 'Lint'


class TestCountBabysitRetriesPerWorkflow:
    """Tests for count_babysit_retries_per_workflow function."""

    def _make_comment(self, author, text):
        """Create a mock comment."""
        comment = MagicMock()
        comment.author = author
        comment.text = text
        return comment

    def _make_pr(self, comments):
        """Create a mock PR with comments."""
        pr = MagicMock()
        pr.comments = comments
        return pr

    def _make_retry_comment(self, branch_name, commit, workflows):
        """Create a BabysitRetry-like comment text."""
        lines = [
            BABYSIT_RETRY_MARKER,
            f'failed on branch `{branch_name}` (commit `{commit[:7]}`)',
            '| Workflow | Retry |',
            '|:---------|:-----:|',
        ]
        for wf_name, retry_count, max_retries in workflows:
            lines.append(f'| `{wf_name}` | {retry_count}/{max_retries} |')
        return '\n'.join(lines)

    def test_no_comments_returns_empty(self):
        """Test counting with no comments returns empty dict."""
        pr = self._make_pr([])
        retries, is_stale, prev = count_babysit_retries_per_workflow(
            pr, 'bert-e', 'w/5.0/feature/test', 'abc1234567890')
        assert retries == {}
        assert is_stale is False
        assert prev is None

    def test_counts_retries_per_workflow(self):
        """Test counting retries per workflow from comments."""
        branch_name = 'w/5.0/feature/test'
        commit = 'abc1234567890'
        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 1, 5), ('Tests', 1, 5)]
            )),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 2, 5)]  # Only CI failed this time
            )),
        ]
        pr = self._make_pr(comments)
        retries, is_stale, prev = count_babysit_retries_per_workflow(
            pr, 'bert-e', branch_name, commit)

        # CI Build was retried twice, Tests once
        assert retries == {'CI Build': 2, 'Tests': 1}
        assert is_stale is False

    def test_babysit_command_resets_all_counts(self):
        """Test that a new /babysit command resets all workflow counts."""
        branch_name = 'w/5.0/feature/test'
        commit = 'abc1234567890'
        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 1, 5), ('Tests', 1, 5)]
            )),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 2, 5), ('Tests', 2, 5)]
            )),
            # User re-invokes babysit
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 1, 5)]
            )),
        ]
        pr = self._make_pr(comments)
        retries, is_stale, prev = count_babysit_retries_per_workflow(
            pr, 'bert-e', branch_name, commit)

        # Only 1 retry for CI Build since the reset
        assert retries == {'CI Build': 1}
        assert is_stale is False

    def test_detects_stale_babysit(self):
        """Test detection of stale babysit when commit changed."""
        branch_name = 'w/5.0/feature/test'
        old_commit = 'abc1234567890'
        new_commit = 'def9876543210'
        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, old_commit,
                [('CI Build', 1, 5)]
            )),
        ]
        pr = self._make_pr(comments)
        retries, is_stale, prev = count_babysit_retries_per_workflow(
            pr, 'bert-e', branch_name, new_commit)

        assert retries == {'CI Build': 1}
        assert is_stale is True
        assert prev == old_commit[:7]

    def test_new_babysit_clears_stale(self):
        """Test that re-invoking /babysit clears stale flag."""
        branch_name = 'w/5.0/feature/test'
        old_commit = 'abc1234567890'
        new_commit = 'def9876543210'
        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, old_commit,
                [('CI Build', 1, 5)]
            )),
            # User pushes new commit and re-invokes babysit
            self._make_comment('user', '@bert-e babysit'),
        ]
        pr = self._make_pr(comments)
        retries, is_stale, prev = count_babysit_retries_per_workflow(
            pr, 'bert-e', branch_name, new_commit)

        assert retries == {}
        assert is_stale is False
        assert prev is None


class TestBabysitExceptions:
    """Tests for BabysitRetry, BabysitExhausted, and BabysitCancelled."""

    def test_babysit_retry_exception(self):
        """Test BabysitRetry exception creation."""
        branch = SimpleNamespace(name='w/5.0/feature/test')
        exc = BabysitRetry(
            active_options=['babysit'],
            branch=branch,
            build_url='https://github.com/org/repo/actions/runs/123',
            commit_sha='abc1234567890',
            workflows=[
                {'id': 1, 'name': 'CI Build', 'retry_count': 2},
                {'id': 2, 'name': 'Tests', 'retry_count': 1},
            ],
            max_retries=5,
        )

        assert exc.code == 140
        assert exc.status == "in_progress"

    def test_babysit_exhausted_exception(self):
        """Test BabysitExhausted exception creation."""
        branch = SimpleNamespace(name='w/5.0/feature/test')
        exc = BabysitExhausted(
            active_options=['babysit'],
            branch=branch,
            build_url='https://github.com/org/repo/actions/runs/123',
            max_retries=5,
            robot='bert-e',
            exhausted_workflows=['CI Build', 'Tests'],
        )

        assert exc.code == 141
        assert exc.status == "failure"

    def test_babysit_cancelled_exception(self):
        """Test BabysitCancelled exception creation."""
        branch = SimpleNamespace(name='w/5.0/feature/test')
        exc = BabysitCancelled(
            active_options=['babysit'],
            branch=branch,
            previous_commit='abc1234567890',
            current_commit='def9876543210',
            robot='bert-e',
        )

        assert exc.code == 142
        assert exc.status == "in_progress"


class TestHandleBabysitRetry:
    """Tests for handle_babysit_retry function."""

    def _make_comment(self, author, text):
        """Create a mock comment."""
        comment = MagicMock()
        comment.author = author
        comment.text = text
        return comment

    def _make_retry_comment(self, branch_name, commit, workflows):
        """Create a BabysitRetry-like comment text."""
        lines = [
            BABYSIT_RETRY_MARKER,
            f'failed on branch `{branch_name}` (commit `{commit[:7]}`)',
            '| Workflow | Retry |',
            '|:---------|:-----:|',
        ]
        for wf_name, retry_count, max_retries in workflows:
            lines.append(f'| `{wf_name}` | {retry_count}/{max_retries} |')
        return '\n'.join(lines)

    def _make_job(self, babysit=False, host='github',
                  build_key='github_actions', max_retries=5, comments=None):
        """Create a mock job with settings."""
        settings = SimpleNamespace(
            babysit=babysit,
            repository_host=host,
            repository_owner='octo-org',
            repository_slug='Hello-World',
            max_babysit_retries=max_retries,
            robot='bert-e',
        )
        project_repo = MagicMock()
        project_repo.get_build_url.return_value = 'https://example.com/build'
        project_repo.rerun_failed_workflow_jobs = MagicMock()

        pull_request = MagicMock()
        pull_request.comments = comments or []

        job = SimpleNamespace(
            settings=settings,
            project_repo=project_repo,
            active_options=['babysit'] if babysit else [],
            pull_request=pull_request,
        )
        return job

    def _make_branch(self, commit='abc1234567890', name='w/5.0/feature/test'):
        """Create a mock branch."""
        branch = MagicMock()
        branch.name = name
        branch.get_latest_commit.return_value = commit
        return branch

    def test_babysit_disabled_returns_false(self):
        """Test that babysit logic is skipped when disabled."""
        job = self._make_job(babysit=False)
        branch = self._make_branch()

        result = handle_babysit_retry(job, branch, 'github_actions')

        assert result is False

    def test_babysit_skips_non_github(self):
        """Test that babysit is skipped for non-GitHub hosts."""
        job = self._make_job(babysit=True, host='bitbucket')
        branch = self._make_branch()

        result = handle_babysit_retry(job, branch, 'github_actions')

        assert result is False

    def test_babysit_retry_per_workflow(self, client):
        """Test that babysit tracks retries per workflow."""
        branch_name = 'w/5.0/feature/test'
        commit = 'abc1234567890'

        # CI Build has 2 retries, Tests has 0
        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 1, 5)]
            )),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, commit,
                [('CI Build', 2, 5)]
            )),
        ]
        job = self._make_job(babysit=True, max_retries=5, comments=comments)
        branch = self._make_branch(commit=commit, name=branch_name)

        # Both workflows fail
        workflow_run_json = {
            'workflow_runs': [
                {
                    'id': 11111,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 1,
                    'check_suite_id': 1,
                    'conclusion': 'failure',
                    'run_attempt': 3,
                    'name': 'CI Build',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
                {
                    'id': 22222,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 2,
                    'check_suite_id': 2,
                    'conclusion': 'failure',
                    'run_attempt': 1,
                    'name': 'Tests',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
            ],
            'total_count': 2
        }
        workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

        with patch.object(AggregatedWorkflowRuns, 'get',
                          return_value=workflow_runs):
            with pytest.raises(BabysitRetry) as exc_info:
                handle_babysit_retry(job, branch, 'github_actions')

        # Both workflows should be retried
        assert job.project_repo.rerun_failed_workflow_jobs.call_count == 2

        # Check the workflows in the exception
        workflows = exc_info.value.kwargs['workflows']
        wf_names = {wf['name'] for wf in workflows}
        assert 'CI Build' in wf_names
        assert 'Tests' in wf_names

        # CI Build should be at retry 3, Tests at retry 1
        ci_wf = next(wf for wf in workflows if wf['name'] == 'CI Build')
        tests_wf = next(wf for wf in workflows if wf['name'] == 'Tests')
        assert ci_wf['retry_count'] == 3
        assert tests_wf['retry_count'] == 1

    def test_workflow_exhausted_individually(self, client):
        """Test that workflows are exhausted individually."""
        branch_name = 'w/5.0/feature/test'
        commit = 'abc1234567890'

        # CI Build has 5 retries (exhausted), Tests has 2
        comments = [
            self._make_comment('user', '@bert-e babysit'),
        ]
        for i in range(5):
            comments.append(self._make_comment(
                'bert-e',
                self._make_retry_comment(
                    branch_name, commit, [('CI Build', i + 1, 5)]
                )
            ))
        for i in range(2):
            comments.append(self._make_comment(
                'bert-e',
                self._make_retry_comment(
                    branch_name, commit, [('Tests', i + 1, 5)]
                )
            ))

        job = self._make_job(babysit=True, max_retries=5, comments=comments)
        branch = self._make_branch(commit=commit, name=branch_name)

        # Both workflows fail
        workflow_run_json = {
            'workflow_runs': [
                {
                    'id': 11111,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 1,
                    'check_suite_id': 1,
                    'conclusion': 'failure',
                    'run_attempt': 6,
                    'name': 'CI Build',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
                {
                    'id': 22222,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 2,
                    'check_suite_id': 2,
                    'conclusion': 'failure',
                    'run_attempt': 3,
                    'name': 'Tests',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
            ],
            'total_count': 2
        }
        workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

        with patch.object(AggregatedWorkflowRuns, 'get',
                          return_value=workflow_runs):
            with pytest.raises(BabysitRetry) as exc_info:
                handle_babysit_retry(job, branch, 'github_actions')

        # Only Tests should be retried (CI Build is exhausted)
        job.project_repo.rerun_failed_workflow_jobs.assert_called_once_with(
            22222
        )

        # Check that only Tests is in the retry list
        workflows = exc_info.value.kwargs['workflows']
        assert len(workflows) == 1
        assert workflows[0]['name'] == 'Tests'
        assert workflows[0]['retry_count'] == 3

    def test_all_workflows_exhausted(self, client):
        """Test BabysitExhausted raised when all workflows exhausted."""
        branch_name = 'w/5.0/feature/test'
        commit = 'abc1234567890'

        # Both workflows have 5 retries (exhausted)
        comments = [
            self._make_comment('user', '@bert-e babysit'),
        ]
        for i in range(5):
            comments.append(self._make_comment(
                'bert-e',
                self._make_retry_comment(
                    branch_name, commit,
                    [('CI Build', i + 1, 5), ('Tests', i + 1, 5)]
                )
            ))

        job = self._make_job(babysit=True, max_retries=5, comments=comments)
        branch = self._make_branch(commit=commit, name=branch_name)

        # Both workflows fail
        workflow_run_json = {
            'workflow_runs': [
                {
                    'id': 11111,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 1,
                    'check_suite_id': 1,
                    'conclusion': 'failure',
                    'run_attempt': 6,
                    'name': 'CI Build',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
                {
                    'id': 22222,
                    'head_sha': commit,
                    'head_branch': branch_name,
                    'status': 'completed',
                    'event': 'pull_request',
                    'workflow_id': 2,
                    'check_suite_id': 2,
                    'conclusion': 'failure',
                    'run_attempt': 6,
                    'name': 'Tests',
                    'repository': {
                        'full_name': 'octo-org/Hello-World',
                        'owner': {'login': 'octo-org'},
                        'name': 'Hello-World'
                    }
                },
            ],
            'total_count': 2
        }
        workflow_runs = AggregatedWorkflowRuns(client, **workflow_run_json)

        with patch.object(AggregatedWorkflowRuns, 'get',
                          return_value=workflow_runs):
            with pytest.raises(BabysitExhausted) as exc_info:
                handle_babysit_retry(job, branch, 'github_actions')

        # No reruns should be called
        job.project_repo.rerun_failed_workflow_jobs.assert_not_called()

        # Check exhausted workflows
        exhausted = exc_info.value.kwargs['exhausted_workflows']
        assert 'CI Build' in exhausted
        assert 'Tests' in exhausted

    def test_babysit_cancelled_on_new_commit(self, client):
        """Test that babysit is cancelled when new commits are pushed."""
        branch_name = 'w/5.0/feature/test'
        old_commit = 'abc1234567890'
        new_commit = 'def9876543210'

        comments = [
            self._make_comment('user', '@bert-e babysit'),
            self._make_comment('bert-e', self._make_retry_comment(
                branch_name, old_commit,
                [('CI Build', 1, 5)]
            )),
        ]

        job = self._make_job(babysit=True, max_retries=5, comments=comments)
        branch = self._make_branch(commit=new_commit, name=branch_name)

        with pytest.raises(BabysitCancelled) as exc_info:
            handle_babysit_retry(job, branch, 'github_actions')

        assert exc_info.value.kwargs['previous_commit'] == old_commit[:7]
        assert exc_info.value.kwargs['current_commit'] == new_commit


class TestCheckPrBabysitEnabled:
    """Tests for _check_pr_babysit_enabled function."""

    def test_babysit_enabled_in_comments(self):
        """Test detecting babysit option from PR comments."""
        comment = MagicMock()
        comment.author = 'user'
        comment.text = '@bert-e babysit'

        pull_request = MagicMock()
        pull_request.comments = [comment]
        pull_request.author = 'user'

        settings = SimpleNamespace(
            robot='bert-e',
            admins=[],
        )

        result = _check_pr_babysit_enabled(pull_request, settings)
        assert result is True

    def test_babysit_not_enabled(self):
        """Test when babysit is not in PR comments."""
        comment = MagicMock()
        comment.author = 'user'
        comment.text = '@bert-e approve'

        pull_request = MagicMock()
        pull_request.comments = [comment]
        pull_request.author = 'user'

        settings = SimpleNamespace(
            robot='bert-e',
            admins=[],
        )

        result = _check_pr_babysit_enabled(pull_request, settings)
        assert result is False


class TestQueueBabysitRetry:
    """Tests for queue babysit retry functionality."""

    def test_queue_babysit_skips_non_github(self):
        """Test queue babysit is skipped for non-GitHub hosts."""
        settings = SimpleNamespace(
            repository_host='bitbucket',
            max_babysit_retries=5,
        )
        job = SimpleNamespace(settings=settings)
        queues = MagicMock()
        queues.build_key = 'github_actions'

        result = _handle_queue_babysit_retry(job, queues, [123])
        assert result is False

    def test_queue_babysit_skips_non_github_actions(self):
        """Test queue babysit skipped for non-github_actions build key."""
        settings = SimpleNamespace(
            repository_host='github',
            max_babysit_retries=5,
        )
        job = SimpleNamespace(settings=settings)
        queues = MagicMock()
        queues.build_key = 'pre-merge'

        result = _handle_queue_babysit_retry(job, queues, [123])
        assert result is False
