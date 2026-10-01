"""H-4 regression tests: release identity uses ANCESTOR semantics.

The recorded git_identity.head represents the BUILD COMMIT (the HEAD
at evidence-generation time). The release commit (which contains the
evidence) is a DESCENDANT of the build commit. Evidence cannot contain
its own commit SHA (circular dependency). Therefore the correct check
is ANCESTOR: recorded build commit must be an ancestor of (or equal to)
live HEAD.

Tests:
  A. Same commit (recorded == live HEAD) → PASS
  B. Direct descendant (recorded = parent, live = child) → PASS
  C. Deep ancestor (recorded = grandparent, live = grandchild) → PASS
  D. Unreachable/invalid SHA → FAIL
  E. Unrelated history → FAIL
  F. Missing/malformed identity → FAIL
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)


def _git(repo, *args, env=None):
    """Run git in repo, return CompletedProcess."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    full_env.setdefault("GIT_AUTHOR_NAME", "test")
    full_env.setdefault("GIT_AUTHOR_EMAIL", "test@test")
    full_env.setdefault("GIT_COMMITTER_NAME", "test")
    full_env.setdefault("GIT_COMMITTER_EMAIL", "test@test")
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                           capture_output=True, text=True, check=False,
                           env=full_env)


def _make_commit(repo, msg="commit", allow_empty=True):
    """Make a commit and return its SHA."""
    if not allow_empty:
        with open(os.path.join(str(repo), "f"), "a") as f:
            f.write("x\n")
        _git(repo, "add", "f")
    _git(repo, "commit", "--allow-empty" if allow_empty else "-q",
         "-m", msg)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _ancestor_check(recorded, live, repo="."):
    """The ANCESTOR check: is 'recorded' an ancestor of (or equal to) 'live'?

    Returns (ok, exit_code).
    - recorded == live → True (same commit is its own ancestor)
    - recorded is parent of live → True
    - recorded is unreachable → False (git exits 128)
    - recorded is unrelated → False (git exits 1)
    - recorded is None/empty → False (no subprocess)
    """
    if not recorded:
        return False, -1
    r = _git(repo, "merge-base", "--is-ancestor", recorded, live)
    return r.returncode == 0, r.returncode


class TestH4AncestorSemantics:
    """H-4: release identity uses ANCESTOR semantics (not strict equality)."""

    def test_a_same_commit_passes(self):
        """A: recorded == live HEAD → PASS (same commit is its own ancestor)."""
        live = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        ok, code = _ancestor_check(live, live)
        assert ok, (
            f"same commit should be its own ancestor; "
            f"exit={code}")

    def test_b_direct_descendant_passes(self, tmp_path):
        """B: recorded = parent, live = child → PASS."""
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "checkout", "-b", "main", "-q")
        parent = _make_commit(tmp_path, "parent")
        child = _make_commit(tmp_path, "child")
        ok, code = _ancestor_check(parent, child, repo=str(tmp_path))
        assert ok, (
            f"parent should be ancestor of child; "
            f"parent={parent[:8]} child={child[:8]} exit={code}")

    def test_c_deep_ancestor_passes(self, tmp_path):
        """C: recorded = grandparent, live = grandchild → PASS."""
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "checkout", "-b", "main", "-q")
        grandparent = _make_commit(tmp_path, "gp")
        _make_commit(tmp_path, "parent")
        grandchild = _make_commit(tmp_path, "child")
        ok, code = _ancestor_check(grandparent, grandchild, repo=str(tmp_path))
        assert ok, (
            f"grandparent should be ancestor of grandchild; exit={code}")

    def test_d_unreachable_sha_fails(self):
        """D: unreachable SHA → FAIL (git exits 128)."""
        live = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        unreachable = "970b57f7" + "0" * 32
        ok, code = _ancestor_check(unreachable, live)
        assert not ok, (
            f"unreachable SHA should fail; exit={code}")
        assert code == 128, (
            f"git should exit 128 for unreachable SHA; got {code}")

    def test_e_unrelated_history_fails(self, tmp_path):
        """E: SHA from unrelated repo → FAIL (not an ancestor)."""
        # Create repo 1 with commits
        repo1 = tempfile.mkdtemp()
        _git(repo1, "init", "-q")
        _git(repo1, "checkout", "-b", "main", "-q")
        sha1 = _make_commit(repo1, "repo1")
        # Create repo 2 (unrelated history)
        repo2 = tempfile.mkdtemp()
        _git(repo2, "init", "-q")
        _git(repo2, "checkout", "-b", "main", "-q")
        sha2 = _make_commit(repo2, "repo2")
        # sha1 is NOT an ancestor of sha2 (unrelated repos)
        ok, code = _ancestor_check(sha1, sha2, repo=str(repo2))
        assert not ok, (
            f"unrelated SHA should fail; exit={code}")
        # git exit 1 = "not an ancestor" (vs 128 = "bad object")
        assert code != 0, f"unrelated SHA should not pass; exit={code}"

    def test_f_missing_identity_fails(self):
        """F: None/empty recorded → FAIL (no subprocess, ok=False)."""
        ok, code = _ancestor_check(None, "HEAD")
        assert not ok, "None recorded should fail"
        ok, code = _ancestor_check("", "HEAD")
        assert not ok, "empty recorded should fail"

    def test_g_real_repository_build_commit_passes(self):
        """G: verify the ACTUAL repository's recorded build commit
        is an ancestor of (or equal to) the live HEAD."""
        fr = json.load(open(os.path.join(REPO_ROOT, "FINAL_RESULTS.json")))
        recorded = fr["git_identity"]["head"]
        live = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        ok, code = _ancestor_check(recorded, live)
        assert ok, (
            f"recorded build commit {recorded[:16]}... should be "
            f"ancestor of live HEAD {live[:16]}...; exit={code}")

    def test_h_real_repository_stale_sha_fails(self):
        """H: verify the STALE SHA (970b57f7...) is correctly rejected."""
        live = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        stale = "970b57f7894253340e3f7789f886b0402f9f363a"
        ok, code = _ancestor_check(stale, live)
        assert not ok, (
            f"stale SHA {stale[:16]}... should fail; exit={code}")
        assert code == 128, (
            f"git should exit 128 for unreachable SHA; got {code}")

    def test_i_consistency_matrix_uses_ancestor(self):
        """I: verify consistency_matrix.py source uses ANCESTOR (merge-base),
        NOT strict equality (==)."""
        src = open(os.path.join(
            REPO_ROOT, "scripts", "consistency_matrix.py")).read()
        assert "merge-base" in src, (
            "consistency_matrix.py must use merge-base ANCESTOR check")
        assert "--is-ancestor" in src, (
            "consistency_matrix.py must use --is-ancestor")
        assert "lineage_ok" in src, (
            "consistency_matrix.py must use lineage_ok variable")
        # Verify strict equality is NOT used for this check
        assert "head_matches_live" not in src, (
            "consistency_matrix.py must NOT use head_matches_live (strict eq)")

    def test_j_all_release_identity_fields_agree(self):
        """J: all release identity sources must agree on the build commit
        AND the build commit must be an ANCESTOR of live HEAD (H-4).

        Under H-4 ANCESTOR semantics (not strict equality):
        - git_commit_at_build is the BUILD commit (parent of release)
        - git_identity.head is the LIVE HEAD (release commit)
        - These are DIFFERENT values by design: evidence cannot contain
          its own commit's SHA (circular dependency). The build commit
          is the parent; after the release commit is created, the
          recorded (parent) != live (child), but ancestor → PASS.

        The test was previously asserting strict equality
        (git_commit_at_build == git_identity.head), which contradicts
        H-4 ANCESTOR semantics. The correct contract is:
        1. All sources that record git_commit_at_build agree on the
           same value (the BUILD commit)
        2. That BUILD commit IS an ancestor of the LIVE HEAD
        3. git_identity.head (BUILD commit) is consistent across docs
        and is an ANCESTOR of (not equal to) the live HEAD.
        """
        fr = json.load(open(os.path.join(REPO_ROOT, "FINAL_RESULTS.json")))
        rm = json.load(open(os.path.join(REPO_ROOT, "release_manifest.json")))
        ri = json.load(open(os.path.join(
            REPO_ROOT, "evidence", "FINAL_HARDENED_RELEASE_2026-09-19",
            "release_identity", "RELEASE_IDENTITY.json")))
        # The canonical BUILD commit (from RELEASE_IDENTITY.json —
        # the single authoritative source for git_commit_at_build)
        build = ri["git_commit_at_build"]
        # All sources that record git_commit_at_build must agree
        assert fr.get("git_commit_at_build") == build, (
            f"FINAL_RESULTS git_commit_at_build {fr.get('git_commit_at_build')} "
            f"!= RELEASE_IDENTITY {build}")
        # Fixed-point model: git_identity.head records the BUILD commit
        # (not the live HEAD). This is consistent with
        # hardening_final_results_builder.py (line 391) and
        # hardening_release_manifest_builder.py (line 89-90).
        # Both FINAL_RESULTS and release_manifest should agree on
        # the BUILD commit value as the evidence head.
        evidence_head = fr["git_identity"]["head"]
        assert rm["git"]["head"] == evidence_head, (
            f"release_manifest git.head {rm['git']['head']} != "
            f"FINAL_RESULTS git_identity.head {evidence_head}")
        # The BUILD commit must be an ANCESTOR of the LIVE HEAD
        # (NOT equal — strict equality would create circularity)
        actual_live = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        ok, _ = _ancestor_check(build, actual_live)
        assert ok, (
            f"build commit {build[:16]}... must be ancestor of "
            f"live HEAD {actual_live[:16]}...")
        # Verify that evidence_head != actual_live (they MUST differ:
        # evidence records the BUILD commit, not the live release commit)
        assert evidence_head != actual_live, (
            f"git_identity.head ({evidence_head[:16]}...) must NOT equal "
            f"live HEAD ({actual_live[:16]}...); H-4 ANCESTOR "
            f"semantics require the evidence head to be the BUILD "
            f"commit (ancestor of the release commit), not the release "
            f"commit itself")

    def test_k_b7_remains_within_run(self):
        """K: verify B-7 is a within-run check (not cross-commit).

        B-7 checks run.get("git_commit") == git_commit (captured at
        finalize time). It does NOT compare against a later commit.
        This is distinct from the release/build ancestry check."""
        src = open(os.path.join(
            REPO_ROOT, "scripts", "final_3m_validation.py")).read()
        assert "provenance.git_commit_matches" in src
        assert "run.get(\"git_commit\") == git_commit" in src
        # B-7 does NOT use merge-base (it's within-run, not cross-commit)
        assert "merge-base" not in src.split(
            "provenance.git_commit_matches")[1].split(
            "def evaluate_final_verdict")[0]
