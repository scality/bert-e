"""Unit tests for the template of the pull request status comment."""
from types import SimpleNamespace

import pytest
from jinja2.exceptions import UndefinedError

from bert_e.lib.template_loader import render
from bert_e.workflow.pr_utils import STATUS_COMMENT_HEADER

ROWS = [
    {'branch': 'w/5/feature/x', 'pr_id': 10, 'build': 'SUCCESSFUL'},
    {'branch': 'w/6/feature/x', 'pr_id': None, 'build': None},
]


def render_status(**kwargs):
    context = dict(icon=':x:', label='Conflict', code=114, integration=None,
                   status={}, active_options=[])
    context.update(kwargs)
    return render('pr_status.md', **context)


def test_starts_with_the_header_which_identifies_it():
    assert render_status().startswith(STATUS_COMMENT_HEADER)


def test_state():
    msg = render_status()
    assert ':x: **Conflict** (message 114)' in msg


def test_state_without_code():
    msg = render_status(code=None, label='Declined')
    assert '**Declined**' in msg
    assert 'message' not in msg


def test_integration_table():
    msg = render_status(integration=ROWS)
    assert 'integration branch | pull request | build' in msg
    assert '`w/5/feature/x` | #10 | SUCCESSFUL' in msg
    assert '`w/6/feature/x` | - | -' in msg


def test_no_integration_branch():
    msg = render_status(integration=[])
    assert '*No integration branch.*' in msg
    assert 'integration branch |' not in msg


def test_unknown_integration_data_is_not_shown():
    msg = render_status(integration=None)
    assert 'integration branch' not in msg
    assert 'No integration branch' not in msg


def test_checklist():
    item = SimpleNamespace(display_name='Approvals',
                           details=['1 peer approval(s) missing'],
                           **{'pass': False})
    msg = render_status(status={'approvals': item})
    assert 'check    | status' in msg
    assert '**Approvals** | :exclamation: 1 peer approval(s) missing' in msg
    assert 'check    | status' not in render_status(status={})


def test_active_options_are_displayed():
    msg = render_status(active_options=['wait', 'approve'])
    assert '**wait, approve**' in msg


def test_never_talks_to_the_bot():
    """The robot reacts to what is written after its name: the status comment
    must not contain any mention of it."""
    msg = render_status(integration=ROWS, active_options=['wait'])
    assert '@' not in msg


@pytest.mark.parametrize('missing', ['icon', 'label', 'integration'])
def test_strict_context(missing):
    context = dict(icon=':x:', label='Conflict', code=1, integration=None,
                   status={}, active_options=[])
    del context[missing]
    with pytest.raises(UndefinedError):
        render('pr_status.md', **context)
