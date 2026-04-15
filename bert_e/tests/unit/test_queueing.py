"""Unit tests for the queueing module."""
from types import SimpleNamespace

from bert_e.workflow.gitwaterflow.branches import (
    DevelopmentBranch, HotfixBranch
)
from bert_e.workflow.gitwaterflow.queueing import get_queue_integration_branch


class _FakeRepo:
    """Minimal git-repo stub that satisfies GWFBranch.__init__."""
    def __init__(self):
        self._url = ''
        self._remote_branches = {}

    def cmd(self, *args, **kwargs):
        return ''


def _make_job(dst_branch, src_branch='bugfix/TEST-00001'):
    """Return a minimal job stub for get_queue_integration_branch."""
    cascade = SimpleNamespace(dst_branches=[dst_branch])
    git = SimpleNamespace(cascade=cascade, repo=_FakeRepo())
    return SimpleNamespace(git=git,
                           pull_request=SimpleNamespace(src_branch=src_branch))


def test_get_queue_integration_branch_hotfix_uses_dst_version():
    """HotfixBranch destination — queue name must embed dst_branch.version."""
    dst = HotfixBranch(_FakeRepo(), 'hotfix/10.0.0')  # hfrev=0 → '10.0.0.0'
    wbranch = SimpleNamespace(version='10.0.0.0')

    result = get_queue_integration_branch(_make_job(dst), pr_id=1,
                                          wbranch=wbranch)
    assert result.name == 'q/w/1/10.0.0.0/bugfix/TEST-00001'


def test_get_queue_integration_branch_dev_uses_wbranch_version():
    """DevelopmentBranch destination — queue name must embed wbranch.version.

    This is the regression test for Risk 3: the old guard was ``hfrev >= 0``
    which would *incorrectly* activate for any non-hotfix branch whose hfrev
    was patched to 0.  The correct guard is ``isinstance(..., HotfixBranch)``.

    Without the fix (hfrev >= 0): hfrev=0 on a DevelopmentBranch would make
    the condition True, so the queue name would use dst.version ('10') instead
    of wbranch.version ('10.1') — the assertion below would then fail.
    """
    dst = DevelopmentBranch(_FakeRepo(), 'development/10')
    # Artificially set hfrev=0 to expose the old `hfrev >= 0` bug path.
    dst.hfrev = 0

    # wbranch.version intentionally differs from dst.version to make the
    # wrong-branch-name visible.
    wbranch = SimpleNamespace(version='10.1')
    result = get_queue_integration_branch(_make_job(dst), pr_id=1,
                                          wbranch=wbranch)

    # Must be based on wbranch.version, not dst.version
    assert '/10.1/' in result.name
    assert result.name == 'q/w/1/10.1/bugfix/TEST-00001'
