"""Unit tests for the pinned pull request status comment template."""
from bert_e.lib.template_loader import render
from bert_e.workflow.pr_utils import STATUS_COMMENT_MARKER, STATUS_PR_RE


def _render(**kwargs):
    params = dict(marker=STATUS_COMMENT_MARKER, state='Conflict', code=1,
                  status=None, integration_prs=[], active_options=None)
    params.update(kwargs)
    return render('pr_status_comment.md', **params)


def test_starts_with_marker_and_shows_state():
    text = _render()
    assert text.startswith(STATUS_COMMENT_MARKER)
    assert 'Conflict' in text


def test_lists_integration_prs_parseable():
    text = _render(integration_prs=[
        {'id': 12, 'src': 'w/1.1/feature/x', 'dst': 'development/1.1'},
        {'id': 13, 'src': 'w/2.0/feature/x', 'dst': 'development/2.0'}])
    found = [m.groupdict() for m in STATUS_PR_RE.finditer(text)]
    assert [f['id'] for f in found] == ['12', '13']
    assert found[1]['dst'] == 'development/2.0'


def test_result_and_options():
    text = _render(status='failure', active_options=['after_pull_request'])
    assert 'failure' in text
    assert 'after_pull_request' in text
