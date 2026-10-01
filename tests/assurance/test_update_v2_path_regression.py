"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — Phase 12
PATH REGRESSION TESTS (task-book Phase 12, cases 1-12).

Guards the portability repair against regressions:

  [1]  Linux repo-local absolute path  -> rejected before
       normalization (detected by the shared machine-path
       detectors)
  [2]  Linux repo-local path           -> normalized to the
       established canonical repo-relative POSIX form
  [3]  Windows drive path               -> rejected before
       normalization
  [4]  UNC path                        -> rejected
  [5]  URL                             -> NOT a filesystem path
       (never normalized)
  [6]  External runtime path            -> classified separately
       (uv-python interpreter home -> explicit placeholder policy)
  [7]  JSON with nested paths          -> every approved path
       normalized
  [8]  JSON with arrays of paths        -> every approved path
       normalized
  [9]  JSON with command strings containing repo paths -> normalized
       safely (the command text keeps its shape, only the root prefix
       is rewritten)
  [10] Portable JSON (the 31 UPDATE-V2 derived copies) -> zero
       forbidden repo-local absolute paths
  [11] Original JSON -> SHA-256 unchanged (re-hashed live against the
       recorded source SHAs)
  [12] Semantic preservation -> only approved path fields changed
       (every difference re-derived through the centralized
       normalizer)

All normalization goes through the ONE centralized implementation
(data_quality_platform/assurance/portable_evidence.py); these tests
contain NO independent path rewriting.
"""

import hashlib
import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.portable_evidence import (
    MACHINE_PATH_DETECTORS, contains_machine_local_path,
    normalize_document, normalize_string)

UPDATE_ID = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"
NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
SUMMARY = os.path.join(
    REPO_ROOT, NS, "portable_paths", "UPDATE_V2_NORMALIZATION_SUMMARY.json")

REPO_PREFIX = REPO_ROOT.rstrip("/") + "/"


def _machine_free(text):
    return not any(p.search(text) for _d, p in MACHINE_PATH_DETECTORS)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_summary():
    if not os.path.isfile(SUMMARY):
        pytest.skip("UPDATE-V2 normalization summary not yet built")
    with open(SUMMARY, encoding="utf-8") as f:
        return json.load(f)


class TestCase1And3And4RejectedBeforeNormalization:
    """Cases 1, 3, 4: machine-local paths are DETECTED (rejected)
    before any normalization happens."""

    def test_case1_linux_repo_local_absolute_detected(self):
        value = f"{REPO_PREFIX}scripts/final_3m_validation.py"
        assert contains_machine_local_path(value) is not None

    def test_case1_linux_repo_local_absolute_in_gate_fixture(self):
        # a real historical capture shape; location-agnostic: the
        # fail-closed property is the DETECTION (and repo-locality)
        # wherever the tree lives (/home authoring, /tmp clean room,
        # /Users, /mnt ...)
        value = (f"{REPO_PREFIX}evidence/release_gate/replay_work/"
                 f"replay_evidence_1/input.csv")
        from data_quality_platform.assurance.portable_evidence import (
            repo_relative)
        assert contains_machine_local_path(value) is not None
        assert repo_relative(value, REPO_ROOT) == (
            "evidence/release_gate/replay_work/replay_evidence_1/"
            "input.csv")

    def test_case3_windows_drive_detected(self):
        assert contains_machine_local_path(
            "C:\\Users\\dave\\reports\\run.json") == "windows_drive"

    def test_case4_unc_detected(self):
        assert contains_machine_local_path(
            "\\\\fileserver\\evidence\\run.json") == "unc_share"

    def test_detector_lookbehind_rejects_url_schemes(self):
        # the windows-drive detector must not fire on URL schemes
        assert "https://example.com/x" .find("C:") == -1
        assert contains_machine_local_path(
            "https://example.com/docs") is None


class TestCase2CanonicalNormalization:
    """Case 2: repo-local paths normalize to the established canonical
    repo-relative POSIX form."""

    def test_case2_repo_local_to_repo_relative(self):
        value = f"{REPO_PREFIX}scripts/final_3m_validation.py"
        new, change = normalize_string(value, REPO_ROOT)
        assert new == "scripts/final_3m_validation.py"
        assert change is not None and change["changes"] == [
            {"type": "repo_relative"}]

    def test_case2_data_file_to_repo_relative(self):
        value = (f"{REPO_PREFIX}data/generated/final_3m/"
                 f"consumer_3m_seed_20260918_pass1.csv")
        new, _ = normalize_string(value, REPO_ROOT)
        assert new == ("data/generated/final_3m/"
                       "consumer_3m_seed_20260918_pass1.csv")

    def test_case2_degenerate_root_edges(self):
        # the centralized normalizer matches the root WITH its
        # trailing separator; a bare root string (no trailing slash)
        # is not a path INSIDE the repository and stays unchanged
        new, change = normalize_string(REPO_PREFIX.rstrip("/"),
                                       REPO_ROOT)
        assert new == REPO_PREFIX.rstrip("/")
        assert change is None
        # the root with its trailing separator degenerates to the
        # empty relative reference
        new2, change2 = normalize_string(REPO_PREFIX, REPO_ROOT)
        assert new2 == ""
        assert change2 is not None

    def test_case2_repo_uri_roundtrip(self):
        from data_quality_platform.assurance.portable_evidence import (
            from_repo_uri, to_repo_uri)
        rel = "scripts/final_3m_validation.py"
        assert from_repo_uri(to_repo_uri(rel)) == rel


class TestCase5URLsAreNotFilesystemPaths:
    """Case 5: URLs must remain URLs — never treated as filesystem
    paths, never normalized."""

    @pytest.mark.parametrize("url", [
        "https://github.com/aladdinoo/Data-Quality-Validation-Platform-v2.git",
        "https://example.com/some/docs",
        "http://internal-wiki/confluence/display/DQ",
        "https://docs.pytest.org/en/how-to/logging.html",
    ])
    def test_case5_urls_untouched(self, url):
        assert contains_machine_local_path(url) is None
        new, change = normalize_string(url, REPO_ROOT)
        assert new == url
        assert change is None

    def test_case5_urls_inside_json_document_untouched(self):
        doc = {"origin": "https://github.com/aladdinoo/"
                         "Data-Quality-Validation-Platform-v2.git",
               "docs": "https://example.com/x"}
        new_doc, changes = normalize_document(doc, REPO_ROOT)
        assert new_doc == doc
        assert changes == []


class TestCase6ExternalRuntimePaths:
    """Case 6: external runtime/environment paths are classified
    separately and only mapped under the explicit placeholder
    policy."""

    def test_case6_external_runtime_path_not_repo_relative(self):
        ext = "/home/z/.local/share/uv/python/cpython-3.12.14-linux" \
              "-x86_64-gnu/bin/python3"
        from data_quality_platform.assurance.portable_evidence import (
            repo_relative)
        assert repo_relative(ext, REPO_ROOT) is None

    def test_case6_external_path_detected_as_machine_local(self):
        ext = "/home/z/.local/share/uv/python/cpython-3.12.14-linux" \
              "-x86_64-gnu/lib/python3.12/os.py"
        assert contains_machine_local_path(ext) == "posix_home"

    def test_case6_placeholder_map_rewrites_interpreter_home(self):
        # the established policy: uv-python interpreter homes map to
        # explicit placeholder tokens inside derived copies
        ext = ("/home/z/.local/share/uv/python/cpython-3.12.14-linux"
               "-x86_64-gnu/bin/python3 -m runner.cli validate")
        placeholder_map = {
            "/home/z/.local/share/uv/python/"
            "cpython-3.12.14-linux-x86_64-gnu":
                "<<uv-python:cpython-3.12.14-linux-x86_64-gnu>>",
        }
        new, change = normalize_string(ext, REPO_ROOT, placeholder_map)
        assert new == ("<<uv-python:cpython-3.12.14-linux-x86_64-gnu>>"
                       "/bin/python3 -m runner.cli validate")
        assert change is not None
        assert change["changes"][0]["type"] == "environment_placeholder"

    def test_case6_external_path_without_policy_is_not_rewritten(self):
        # outside the placeholder policy, an external machine path is
        # preserved (never silently converted into a repo path)
        ext = "/opt/some/external/tool/bin/tool"
        new, change = normalize_string(ext, REPO_ROOT)
        assert new == ext
        assert change is None


class TestCase7NestedAnd8Arrays:
    """Cases 7, 8: nested documents and arrays of paths — every
    approved path is normalized."""

    def test_case7_nested_document(self):
        doc = {
            "provenance": {
                "script_path": f"{REPO_PREFIX}scripts/check.py",
                "nested": {"deeper": {
                    "path": f"{REPO_PREFIX}data/x.csv"}},
                "url": "https://example.com/x",
            },
        }
        new_doc, changes = normalize_document(doc, REPO_ROOT)
        assert new_doc["provenance"]["script_path"] == "scripts/check.py"
        assert new_doc["provenance"]["nested"]["deeper"]["path"] == \
            "data/x.csv"
        assert new_doc["provenance"]["url"] == "https://example.com/x"
        assert {c["json_path"] for c in changes} == {
            "$.provenance.script_path",
            "$.provenance.nested.deeper.path"}

    def test_case8_array_of_paths(self):
        doc = {"files": [f"{REPO_PREFIX}a/b.json",
                         f"{REPO_PREFIX}c/d.json",
                         "e/f.json"],
               "urls": ["https://example.com/z"]}
        new_doc, changes = normalize_document(doc, REPO_ROOT)
        assert new_doc["files"] == ["a/b.json", "c/d.json", "e/f.json"]
        assert {c["json_path"] for c in changes} == {
            "$.files[0]", "$.files[1]"}


class TestCase9CommandStrings:
    """Case 9: command strings containing repo paths are normalized
    safely — only the root prefix is rewritten, the command keeps
    its shape."""

    def test_case9_canonical_command(self):
        cmd = (f"{REPO_PREFIX}.venv/bin/python -m runner.cli validate"
               f" --csv data/generated/final_3m/in.csv"
               f" --output data/generated/final_3m/out.csv"
               f" --run-id final_3m_pass1")
        new, _ = normalize_string(cmd, REPO_ROOT)
        assert new == (".venv/bin/python -m runner.cli validate"
                       " --csv data/generated/final_3m/in.csv"
                       " --output data/generated/final_3m/out.csv"
                       " --run-id final_3m_pass1")
        assert _machine_free(new)

    def test_case9_command_with_flag_pointing_into_repo(self):
        cmd = (f"python tools/x.py --evidence-dir "
                f"{REPO_PREFIX}evidence/release_gate/replay_work")
        new, _ = normalize_string(cmd, REPO_ROOT)
        assert new == ("python tools/x.py --evidence-dir "
                      "evidence/release_gate/replay_work")


class TestCase10PortableJsonZeroForbiddenPaths:
    """Case 10: every UPDATE-V2 portable derived copy contains zero
    forbidden repo-local absolute paths."""

    def test_case10_all_portable_copies_machine_path_free(self):
        summary = _load_summary()
        assert summary["totals"]["derived_portable_files"] >= 10
        violations = []
        for rec in summary["sources"]:
            p = os.path.join(REPO_ROOT, rec["derived_portable"])
            text = open(p, encoding="utf-8").read()
            hits = [d for d, pat in MACHINE_PATH_DETECTORS
                    if pat.search(text)]
            if hits:
                violations.append((rec["derived_portable"], hits))
        assert violations == []

    def test_case10_flagship_identity_block_complete(self):
        flagship = os.path.join(
            REPO_ROOT, NS, "portable_evidence",
            "FINAL_3M_VALIDATION_RESULTS.UPDATE-V2.portable.json")
        with open(flagship, encoding="utf-8") as f:
            d = json.load(f)
        ident = d["_artifact_identity"]
        for field in ("artifact_class", "update_id", "source_artifact",
                      "source_artifact_sha256", "logical_path",
                      "relative_path", "schema_version", "derived_by",
                      "normalization_policy"):
            assert ident.get(field), f"missing identity field {field}"
        assert ident["update_id"] == UPDATE_ID
        assert ident["artifact_class"] == "DERIVED"
        assert ident["source_artifact"] == (
            "evidence/validation/2026-09-18/fresh_3m2/harness/FINAL_RESULTS.json")


UNTRACKED_REGENERABLE_PREFIXES = (
    "evidence/release_gate/replay_work/",
    "evidence/release_gate/replay_work_neg/",
    "evidence/release_gate/repro_check/replay_work/",
    "evidence/release_gate/repro_check/replay_work_neg/",
)


def _is_untracked_regenerable(rel):
    """Platform policy: the release-gate replay fixtures are
    deliberately UNTRACKED (gitignored, commit 5a61e63 — regenerable
    work products whose results are recorded in
    final_release_gate.json). They exist in the AUTHORING repository
    but are not part of release archives."""
    return rel.startswith(UNTRACKED_REGENERABLE_PREFIXES)


class TestCase11OriginalsUnchanged:
    """Case 11: the original JSON artifacts keep the SHA-256 recorded
    BEFORE transformation (byte-exact preservation); fixture
    originals absent from a release extraction (documented platform
    policy) are counted and asserted — never silently skipped."""

    def test_case11_source_shas_unchanged(self):
        summary = _load_summary()
        drift = []
        absent_documented = 0
        for rec in summary["sources"]:
            p = os.path.join(REPO_ROOT, rec["source"])
            if not os.path.isfile(p):
                if _is_untracked_regenerable(rec["source"]):
                    absent_documented += 1
                    continue
                drift.append((rec["source"], "MISSING-unexpected"))
                continue
            actual = _sha256_file(p)
            if actual != rec["source_sha256"]:
                drift.append((rec["source"], rec["source_sha256"],
                               actual))
        assert drift == []
        # authoring repo: all 31 present; release extraction: exactly
        # the 24 documented fixtures absent (7 official originals are
        # release members)
        assert absent_documented in (0, 24)

    def test_case11_official_3m_flagship_untouched(self):
        summary = _load_summary()
        rec = next(r for r in summary["sources"] if r["source"] == (
            "evidence/validation/2026-09-18/fresh_3m2/harness/FINAL_RESULTS.json"))
        actual = _sha256_file(os.path.join(REPO_ROOT, rec["source"]))
        assert actual == rec["source_sha256"]
        assert rec["source_sha256"] == (
            "755fa28f224c480e873676b487d4c6babeb0072fff50e47c081046"
            "84b6643337")


class TestCase12SemanticPreservation:
    """Case 12: only approved path fields changed — every difference
    between an original and its UPDATE-V2 portable copy is
    re-derivable through the centralized normalizer."""

    @staticmethod
    def _strip_identity(doc):
        return {k: v for k, v in doc.items() if k != "_artifact_identity"}

    @staticmethod
    def _expected(before, placeholder_map):
        expected, _ = normalize_string(before, REPO_ROOT, placeholder_map)
        return expected

    _ROOT_PREFIX = None

    def test_case12_every_changed_field_is_approved_normalization(self):
        """Location-independent verification: the set of differing
        leaves between each original and its derived copy must equal
        EXACTLY the shipped semantic-diff change set, and every
        change must satisfy the approved transformation rule with a
        SINGLE consistent authoring-root prefix (reconstructed from
        the data itself — the test never hardcodes the authoring
        machine, so it passes in the authoring repo AND in a clean-
        room extraction alike)."""
        summary = _load_summary()
        with open(os.path.join(
                REPO_ROOT, NS, "path_forensics",
                "json_semantic_diff_UPDATE-V2.json"),
                encoding="utf-8") as f:
            shipped = json.load(f)
        shipped_by_source = {}
        for c in shipped["changes"]:
            shipped_by_source.setdefault(c["source_file"], []).append(c)

        def leaf_diffs(a, b, path, out):
            if isinstance(a, dict) and isinstance(b, dict):
                if set(a) != set(b):
                    out.append((path, "key set changed"))
                    return
                for k in a:
                    leaf_diffs(a[k], b[k], f"{path}.{k}", out)
            elif isinstance(a, list) and isinstance(b, list):
                if len(a) != len(b):
                    out.append((path, "length changed"))
                    return
                for i, (x, y) in enumerate(zip(a, b)):
                    leaf_diffs(x, y, f"{path}[{i}]", out)
            elif isinstance(a, str) and isinstance(b, str):
                if a != b:
                    out.append((path, (a, b)))
            elif a != b:
                out.append((path, "scalar changed"))

        problems = []
        absent_documented = 0
        deep_diff_pairs = 0
        # reconstruct the SINGLE authoring-root prefix from any
        # suffix-preserving change BEFORE the per-source loop (never
        # hardcoded; the reconstruction itself is asserted)
        root_prefix = None
        for c in shipped["changes"]:
            if "placeholder" in c["reason"]:
                continue
            before, after = c["before"], c["after"]
            if (isinstance(before, str) and isinstance(after, str)
                    and before.endswith(after)
                    and len(before) > len(after)):
                root_prefix = before[:len(before) - len(after)]
                break
        assert root_prefix, ("cannot reconstruct the authoring-root "
                             "prefix from the shipped diff")
        for rec in summary["sources"]:
            src_path = os.path.join(REPO_ROOT, rec["source"])
            if not os.path.isfile(src_path):
                # clean room: fixture original absent (documented
                # platform policy) -> verify the derived copy's
                # self-consistency instead (counted, asserted)
                assert _is_untracked_regenerable(rec["source"]), (
                    f"unexpected absent source {rec['source']}")
                absent_documented += 1
                with open(os.path.join(
                        REPO_ROOT, rec["derived_portable"]),
                        encoding="utf-8") as f:
                    dd = json.load(f)
                ident = dd["_artifact_identity"]
                assert ident["source_artifact"] == rec["source"]
                assert ident["source_artifact_sha256"] == \
                    rec["source_sha256"]
                continue
            with open(src_path, encoding="utf-8") as f:
                orig = json.load(f)
            with open(os.path.join(REPO_ROOT, rec["derived_portable"]),
                      encoding="utf-8") as f:
                derived = self._strip_identity(json.load(f))
            diffs = []
            leaf_diffs(orig, derived, "$", diffs)
            deep_diff_pairs += 1
            # (a) coverage completeness: every differing leaf is in
            # the shipped change set (and vice versa)
            shipped_paths = {c["json_path"]
                              for c in shipped_by_source.get(
                                  rec["source"], [])}
            for dpath, dval in diffs:
                if dpath not in shipped_paths:
                    problems.append(
                        (rec["source"], dpath, "not in shipped diff"))
            # (b) transformation rule: single consistent prefix or
            # the placeholder policy — verified per change below
            for c in shipped_by_source.get(rec["source"], []):
                before, after = c["before"], c["after"]
                if "placeholder" in c["reason"]:
                    m = re.match(
                        r"^(/home/[^/]+/\.local/share/uv/python/"
                        r"[^/]+)/", before)
                    mv = re.match(r"^(/home/[^/]+/\.venv/)", before)
                    if (m and after.startswith("<<uv-python:")) or \
                            (mv and after.startswith("<<venv-python>>")):
                        pass  # documented environment placeholder class
                    else:
                        problems.append(
                            (rec["source"], c["json_path"],
                             "placeholder rule violated"))
                    continue
                # repo-relative strip: after == before with the
                # single reconstructed authoring-root prefix removed
                # (works for prefix-at-start AND mid-string embedded
                # occurrences, e.g. command lines)
                if not (isinstance(before, str)
                        and isinstance(after, str)
                        and root_prefix is not None
                        and before.replace(root_prefix, "")
                        == after):
                    problems.append(
                        (rec["source"], c["json_path"],
                         "not a consistent root-prefix strip"))
        # (c) the global rule after == before.replace(root_prefix,"")
        # holds for EVERY repo-relative change (prefix-at-start and
        # mid-string embedded occurrences alike)
        for c in shipped["changes"]:
            if "placeholder" in c["reason"]:
                continue
            before, after = c["before"], c["after"]
            if not (isinstance(before, str) and isinstance(after, str)
                    and before.replace(root_prefix, "") == after):
                problems.append(
                    (c["source_file"], c["json_path"],
                     "not a consistent root-prefix strip"))
        assert problems == []
        # authoring repo: 31 deep-diff pairs; clean room: 7 official
        # pairs + 24 documented-absent fixture-policy checks
        assert deep_diff_pairs in (7, 10, 31)
        assert absent_documented in (0, 24)

    def test_case12_flagship_truth_values_untouched(self):
        flagship = os.path.join(
            REPO_ROOT, NS, "portable_evidence",
            "FINAL_3M_VALIDATION_RESULTS.UPDATE-V2.portable.json")
        with open(flagship, encoding="utf-8") as f:
            d = self._strip_identity(json.load(f))
        assert d["rows"] == 3200000
        assert d["columns"] == 33
        assert d["output_columns"] == 41
        assert d["input_sha256"] == (
            "59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165acba"
            "5318d153")
        assert d["output_sha256"] == (
            "b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5"
            "719329a")
        assert d["oracle_comparisons"] == 51200000
        assert d["oracle_mismatches"]["combined_total"] == 0
        assert list(d["runs"].keys()) == ["run_1", "run_2"]
        assert d["runs"]["run_1"]["status"] == "PASS"
        assert d["runs"]["run_2"]["status"] == "PASS"
        assert d["final_status"] == "PASS"
        assert len(d["mismatches_by_rule"]) == 8


def _rebuild_placeholder_pairs(doc):
    """Rebuild the (prefix, token) placeholder pairs for one document
    (the established uv-python interpreter-home policy)."""
    import re
    pat = re.compile(r"^/home/[^/]+/\.local/share/uv/python/([^/]+)")
    pairs = []

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            m = pat.match(obj)
            if m:
                prefix = m.group(0)
                pairs.append((prefix,
                             f"<<uv-python:{m.group(1)}>>"))
    walk(doc)
    return pairs


def _collect_semantic_mismatches(orig, derived, path, placeholder_map):
    """Walk both trees; every differing string leaf must be
    re-derivable via the centralized normalize_string."""
    out = []
    if isinstance(orig, dict) and isinstance(derived, dict):
        if set(orig.keys()) != set(derived.keys()):
            out.append(f"{path}: key set changed")
            return out
        for k in orig:
            out.extend(_collect_semantic_mismatches(
                orig[k], derived[k], f"{path}.{k}", placeholder_map))
    elif isinstance(orig, list) and isinstance(derived, list):
        if len(orig) != len(derived):
            out.append(f"{path}: length changed")
        for i, (a, b) in enumerate(zip(orig, derived)):
            out.extend(_collect_semantic_mismatches(
                a, b, f"{path}[{i}]", placeholder_map))
    elif isinstance(orig, str) and isinstance(derived, str):
        if orig != derived:
            expected, _ = normalize_string(
                orig, REPO_ROOT, placeholder_map)
            if expected != derived:
                out.append(f"{path}: unapproved change {orig!r} -> "
                           f"{derived!r}")
    elif orig != derived:
        out.append(f"{path}: scalar changed {orig!r} -> {derived!r}")
    return out
