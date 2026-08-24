"""Unit tests for check_source_branch_lineage."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bert_e import exceptions as messages
from bert_e.lib.simplecmd import CommandError
from bert_e.workflow.gitwaterflow import check_source_branch_lineage


def _make_branch(name, latest_commit, ancestor_of=None):
    """Build a fake branch stub.

    ancestor_of: set of commit shas that this branch considers as ancestors.
    """
    b = SimpleNamespace(name=name)
    b.get_latest_commit = MagicMock(return_value=latest_commit)
    ancestor_of = ancestor_of or set()
    b.includes_commit = MagicMock(
        side_effect=lambda commit: commit in ancestor_of
    )
    return b


def _make_job(src_name, dst_name, dst_ancestors, cascade_branches,
              merge_base_map):
    """Return a minimal job stub for check_source_branch_lineage.

    merge_base_map: dict[(src, higher)] -> merge-base sha.
    Missing keys raise CommandError (no common ancestor).
    """
    def fake_cmd(template, *args):
        key = (args[0], args[1])
        result = merge_base_map.get(key)
        if result is None:
            raise CommandError('no common ancestor')
        return result + '\n'

    repo = SimpleNamespace(cmd=fake_cmd)
    src = SimpleNamespace(
        name=src_name,
        get_latest_commit=MagicMock(return_value='src-tip'),
    )
    dst = _make_branch(dst_name, 'dst-tip', ancestor_of=dst_ancestors)
    cascade = SimpleNamespace(dst_branches=cascade_branches)

    git = SimpleNamespace(src_branch=src, dst_branch=dst, cascade=cascade,
                          repo=repo)
    return SimpleNamespace(git=git, active_options={})


class TestCheckSourceBranchLineageClean:
    """Source branch is cleanly based on the target — no error expected."""

    def test_no_higher_branches(self):
        """Single branch in cascade: nothing to compare against."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst],
            merge_base_map={},
        )
        check_source_branch_lineage(job)  # must not raise

    def test_higher_branch_but_merge_base_in_dst(self):
        """Merge-base with the higher branch is already in dst — clean."""
        dst_ancestors = {'common-base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher = _make_branch('development/4', 'higher-tip',
                              ancestor_of=set())

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher],
            merge_base_map={
                ('feature/BERTE-612-something', 'development/4'): 'common-base'
            },
        )
        check_source_branch_lineage(job)  # must not raise

    def test_merge_base_command_raises(self):
        """If git merge-base fails for a higher branch, skip it silently."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={},  # missing key → raises CommandError
        )
        check_source_branch_lineage(job)  # must not raise

    def test_two_higher_branches_first_clean_second_clean(self):
        """Loop iterates all higher branches; no raise when both are clean."""
        dst_ancestors = {'base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('feature/BERTE-612-something', 'development/5.1'): 'base',
                ('feature/BERTE-612-something', 'development/10.0'): 'base',
            },
        )
        check_source_branch_lineage(job)  # must not raise

    def test_higher_get_latest_commit_raises_is_skipped(self):
        """If higher.get_latest_commit() raises CommandError, skip it."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())
        higher.get_latest_commit.side_effect = CommandError('branch gone')

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={},
        )
        check_source_branch_lineage(job)  # must not raise

    def test_src_get_latest_commit_raises_skips_entire_check(self):
        """If src.get_latest_commit() raises CommandError, skip the check."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={
                ('feature/BERTE-612-something', 'development/4'): 'foreign',
            },
        )
        # Make src.get_latest_commit() fail
        job.git.src_branch.get_latest_commit.side_effect = CommandError(
            'src gone'
        )
        check_source_branch_lineage(job)  # must not raise even though foreign

    def test_lower_branch_already_in_dst_is_skipped(self):
        """Branches whose tip is already in dst are skipped without merge-base.

        This covers the dst.includes_commit(higher.get_latest_commit()) guard:
        a branch that is BELOW dst in the cascade (its tip is in dst's history)
        must never trigger the merge-base check.
        """
        # lower_branch tip is included in dst — it comes before dst
        dst_ancestors = {'lower-tip'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        lower = _make_branch('development/4.2', 'lower-tip',
                             ancestor_of=set())

        job = _make_job(
            src_name='feature/BERTE-612-something',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, lower],
            merge_base_map={},  # no merge-base call expected
        )
        check_source_branch_lineage(job)  # must not raise


class TestCheckSourceBranchLineageBackport:
    """Source branch was already merged into the higher branch (legitimate
    backport) — ForeignCommitsInSourceBranch must NOT be raised."""

    def test_src_already_merged_into_higher(self):
        """When higher already includes src tip, skip the contamination check.

        This models: PR was merged into dev/5.1 first, now being backported
        to dev/4.3. higher.includes_commit(src.get_latest_commit()) is True.

        The merge_base_map is set so that without the backport guard the
        merge-base would be 'foreign-commit', which is NOT in dst_ancestors,
        making ForeignCommitsInSourceBranch fire. The guard must prevent that.
        """
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        # higher already includes 'src-tip' SHA (the default from _make_job)
        higher = _make_branch('development/5.1', 'higher-tip',
                              ancestor_of={'src-tip'})

        job = _make_job(
            src_name='bugfix/TEST-0001',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={
                ('bugfix/TEST-0001', 'development/5.1'): 'foreign-commit',
            },
        )
        check_source_branch_lineage(job)  # must not raise


class TestCheckSourceBranchLineageContaminated:
    """Source branch carries foreign history — ForeignCommitsInSourceBranch
    must be raised."""

    def test_raises_when_merge_base_not_in_dst(self):
        """Merge-base with higher branch is NOT in dst → contamination."""
        dst_ancestors = {'dst-only-commit'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher],
            merge_base_map={
                ('feature/ARTESCA-17922-fix', 'development/4'): 'a5c998726'
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)

    def test_error_contains_branch_names(self):
        """Exception kwargs carry the three branch names."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={
                ('feature/ARTESCA-17922-fix', 'development/4'): 'a5c998726'
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        kwargs = exc_info.value.kwargs
        assert kwargs['src_branch'] == 'feature/ARTESCA-17922-fix'
        assert kwargs['dst_branch'] == 'development/4.3'
        assert kwargs['foreign_branch'] == 'development/4'

    def test_two_higher_branches_first_contaminated_raises_immediately(self):
        """Loop raises on the first contaminated branch; others not checked."""
        dst_ancestors = {'base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        # higher1 is contaminated: merge-base is 'foreign', not in dst
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        # higher2 would also be clean, but we never reach it
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('feature/ARTESCA-17922-fix', 'development/5.1'): 'foreign',
                ('feature/ARTESCA-17922-fix', 'development/10.0'): 'base',
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        assert exc_info.value.kwargs['foreign_branch'] == 'development/5.1'

    def test_two_higher_branches_first_clean_second_contaminated(self):
        """Loop skips clean higher branch and raises on contaminated one."""
        dst_ancestors = {'base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        # higher1 is clean: merge-base is 'base', which is in dst
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        # higher2 is contaminated: merge-base is 'foreign', not in dst
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('feature/ARTESCA-17922-fix', 'development/5.1'): 'base',
                ('feature/ARTESCA-17922-fix', 'development/10.0'): 'foreign',
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        assert exc_info.value.kwargs['foreign_branch'] == 'development/10.0'


class TestCheckSourceBranchLineageKnownLimitations:
    """Document known false-positive scenarios (see function docstring)."""

    def test_extended_backport_false_positive(self):
        """Known false positive: branch merged into higher, then extended.

        If a feature branch was previously merged into development/5.1 (so its
        OLD tip is now in dev/5.1 history), and the developer adds new commits
        before opening a backport PR targeting development/4.3, the backport
        guard does NOT fire (new tip is not in dev/5.1). The merge-base with
        dev/5.1 resolves to the developer's old tip, which is not in dev/4.3
        (it was merged to dev/5.1 only) — ForeignCommitsInSourceBranch is
        raised even though the branch is clean.

        This test pins the behavior so it is visible if the heuristic changes.
        """
        # 'old-tip' is the developer's previous tip that was merged into
        # dev/5.1 but never cascaded to dev/4.3.
        dst_ancestors = set()  # 'old-tip' not in dev/4.3
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        # higher includes 'old-tip' (was merged there) but NOT 'src-tip'
        higher = _make_branch('development/5.1', 'h-tip',
                              ancestor_of={'old-tip'})

        job = _make_job(
            src_name='feature/BERTE-001-backport',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher],
            merge_base_map={
                # merge-base is 'old-tip': dev's own past commit, not a
                # foreign commit from dev/5.1, but indistinguishable here.
                ('feature/BERTE-001-backport', 'development/5.1'): 'old-tip',
            },
        )
        # Known false positive: ForeignCommitsInSourceBranch is raised even
        # though the branch is clean. This test documents the limitation.
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)
