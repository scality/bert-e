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
              merge_base_map, bypass=False):
    """Return a minimal job stub for check_source_branch_lineage.

    merge_base_map: dict[(src_sha, higher_tip)] -> merge-base sha.
    The implementation passes pre-resolved SHAs to git merge-base, so keys
    must be commit SHAs, not branch names.
    Missing keys raise CommandError (no common ancestor).
    bypass: if True, sets bypass_source_branch_lineage on settings.
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
    settings = SimpleNamespace(bypass_source_branch_lineage=bypass)
    return SimpleNamespace(git=git, active_options={}, settings=settings,
                           author_bypass={})


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
            # keys are (src_sha, higher_tip): 'src-tip' and 'higher-tip'
            merge_base_map={
                ('src-tip', 'higher-tip'): 'common-base'
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
                ('src-tip', 'h1-tip'): 'base',
                ('src-tip', 'h2-tip'): 'base',
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
                ('src-tip', 'higher-tip'): 'foreign',
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
        a branch whose full history is already absorbed into dst is skipped
        since any merge-base with src would trivially be in dst too.
        """
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
                ('src-tip', 'higher-tip'): 'foreign-commit',
            },
        )
        check_source_branch_lineage(job)  # must not raise

    def test_src_tip_equals_higher_tip_is_contamination(self):
        """When src_sha == higher_tip the backport guard must NOT fire.

        A branch created directly from development/5.1 without any new commits
        has src_sha == higher_tip. git considers every commit an ancestor of
        itself, so higher.includes_commit(src_sha) would be True — incorrectly
        treating this as a legitimate backport. The `src_sha != higher_tip`
        pre-condition prevents this: the merge-base check is reached and
        correctly detects the contamination.
        """
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        # higher_tip == 'src-tip': developer branched directly from dev/5.1
        higher = _make_branch('development/5.1', 'src-tip',
                              ancestor_of={'src-tip'})

        job = _make_job(
            src_name='feature/DIRECT-BRANCH-FROM-5.1',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            # merge-base(src-tip, src-tip) = src-tip; not in dst → contamination
            merge_base_map={
                ('src-tip', 'src-tip'): 'src-tip',
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)


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
                ('src-tip', 'higher-tip'): 'a5c998726'
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)

    def test_error_contains_branch_names(self):
        """Exception kwargs carry the branch names and foreign_branches list."""
        dst = _make_branch('development/4.3', 'dst-tip', ancestor_of=set())
        higher = _make_branch('development/4', 'higher-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=set(),
            cascade_branches=[dst, higher],
            merge_base_map={
                ('src-tip', 'higher-tip'): 'a5c998726'
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        kwargs = exc_info.value.kwargs
        assert kwargs['src_branch'] == 'feature/ARTESCA-17922-fix'
        assert kwargs['dst_branch'] == 'development/4.3'
        assert kwargs['foreign_branches'] == ['development/4']

    def test_two_higher_branches_one_contaminated(self):
        """Only the contaminated branch appears in foreign_branches."""
        dst_ancestors = {'base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('src-tip', 'h1-tip'): 'foreign',
                ('src-tip', 'h2-tip'): 'base',  # clean
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        assert exc_info.value.kwargs['foreign_branches'] == ['development/5.1']

    def test_two_higher_branches_first_clean_second_contaminated(self):
        """Loop skips clean higher branch and includes contaminated one."""
        dst_ancestors = {'base'}
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('src-tip', 'h1-tip'): 'base',      # clean
                ('src-tip', 'h2-tip'): 'foreign',   # contaminated
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        assert exc_info.value.kwargs['foreign_branches'] == ['development/10.0']

    def test_two_higher_branches_both_contaminated(self):
        """When both higher branches are contaminated, both appear in the error."""
        dst_ancestors = set()
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher1 = _make_branch('development/5.1', 'h1-tip', ancestor_of=set())
        higher2 = _make_branch('development/10.0', 'h2-tip', ancestor_of=set())

        job = _make_job(
            src_name='feature/ARTESCA-17922-fix',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher1, higher2],
            merge_base_map={
                ('src-tip', 'h1-tip'): 'foreign-1',
                ('src-tip', 'h2-tip'): 'foreign-2',
            },
        )
        with pytest.raises(messages.ForeignCommitsInSourceBranch) as exc_info:
            check_source_branch_lineage(job)

        assert exc_info.value.kwargs['foreign_branches'] == [
            'development/5.1', 'development/10.0',
        ]


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
                ('src-tip', 'h-tip'): 'old-tip',
            },
        )
        # Known false positive: ForeignCommitsInSourceBranch is raised even
        # though the branch is clean. This test documents the limitation.
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)


class TestBypassSourceBranchLineage:
    """bypass_source_branch_lineage skips the check entirely."""

    def _contaminated_job(self, bypass):
        """Return a job that would normally raise ForeignCommitsInSourceBranch."""
        dst_ancestors = set()
        dst = _make_branch('development/4.3', 'dst-tip',
                           ancestor_of=dst_ancestors)
        higher = _make_branch('development/4', 'h-tip', ancestor_of=set())
        return _make_job(
            src_name='bugfix/BERTE-001',
            dst_name='development/4.3',
            dst_ancestors=dst_ancestors,
            cascade_branches=[dst, higher],
            merge_base_map={
                ('src-tip', 'h-tip'): 'foreign-sha',
            },
            bypass=bypass,
        )

    def test_bypass_via_settings(self):
        """bypass_source_branch_lineage=True on settings skips the check."""
        job = self._contaminated_job(bypass=True)
        check_source_branch_lineage(job)  # must not raise

    def test_bypass_via_author_bypass(self):
        """bypass_source_branch_lineage in author_bypass skips the check."""
        job = self._contaminated_job(bypass=False)
        job.author_bypass['bypass_source_branch_lineage'] = True
        check_source_branch_lineage(job)  # must not raise

    def test_no_bypass_still_raises(self):
        """Without bypass, contamination is still detected."""
        job = self._contaminated_job(bypass=False)
        with pytest.raises(messages.ForeignCommitsInSourceBranch):
            check_source_branch_lineage(job)
