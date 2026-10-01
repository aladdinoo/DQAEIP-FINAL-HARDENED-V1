"""Absolute-path release gate tests (Phase 3, task-book section 4).

Covers every required detection class:

    - positive detection (a machine path IS detected)
    - negative detection (clean text is NOT flagged)
    - Windows path          C:\\Users\\dave\\data.csv
    - Linux path            /home/z/repo/scripts/x.py
    - WSL path              /mnt/c/Users/dave/data.csv
    - repo-root absolute path
    - legitimate HTTPS URL  (never flagged)
    - legitimate SHA-256    (never flagged)
    - documented example    (allowed ONLY via an exact-path exception)

Plus fail-closed properties of the exception mechanism:

    - an exception exempts exactly ONE file (path-specificity)
    - an over-broad exception (pattern/directory) invalidates the
      registry and FAILS the gate
    - a malformed registry fails the gate
    - a missing scope file fails the gate (never silently skipped)
"""

import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from tools.absolute_path_release_gate import (  # noqa: E402
    run_gate, scan_text, validate_exception_registry)

REPO_ROOT_ABS = REPO_ROOT.rstrip("/") + "/"


def write(tmpdir, rel, content):
    path = os.path.join(tmpdir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def make_registry(tmpdir, entries):
    rel = write(tmpdir, "exceptions.json", json.dumps(
        {"exceptions": entries}))
    return rel


@pytest.fixture()
def repo(tmp_path):
    return str(tmp_path)


# ------------------------------------------------------------ scanning

def test_positive_detection_linux_home():
    v = scan_text("command: /home/z/repo/scripts/run.py --out x\n",
                  "f.txt")
    assert v and v[0]["rule"] == "posix_home"
    assert v[0]["line"] == 1


def test_negative_detection_clean():
    v = scan_text(
        "command: python scripts/run.py --csv data/in.csv\n"
        "url: https://github.com/example/repo.git\n"
        "sha: 59624a53c72f908f1dde673ceecf59e0662ae721bb8f9a"
        "b1d156b8c3029f1a6f\n",
        "f.txt")
    assert v == []


def test_windows_path_detected():
    v = scan_text(r"output: C:\Users\dave\data.csv", "f.txt")
    assert any(x["rule"] == "windows_drive" for x in v)
    v2 = scan_text(r"backup on D:\archive\2026\run1", "f.txt")
    assert any(x["rule"] == "windows_drive" for x in v2)


def test_wsl_path_detected():
    v = scan_text("mount: /mnt/c/Users/dave/data.csv", "f.txt")
    assert any(x["rule"] == "mounted_volume" for x in v)


def test_repo_root_absolute_path_detected():
    # location-agnostic: a repo-root absolute path must be DETECTED
    # as machine-local wherever the tree lives (authoring checkout
    # under /home, clean-room extraction under /tmp, macOS /Users,
    # WSL /mnt, ...). The specific rule id depends on the mount
    # point; the fail-closed property is the detection itself.
    v = scan_text(f"checker: {REPO_ROOT_ABS}scripts/final_3m_validation.py",
                  "f.txt")
    assert v and v[0]["rule"] in ("posix_home", "root_home", "machine_tmp",
                                  "macos_users", "mounted_volume")


def test_macos_users_path_detected():
    v = scan_text("log: /Users/dave/project/out.txt", "f.txt")
    assert any(x["rule"] == "macos_users" for x in v)


def test_file_uri_detected():
    v = scan_text("open file:///home/z/secret.txt please", "f.txt")
    assert any(x["rule"] == "file_uri" for x in v)


def test_https_url_not_flagged():
    v = scan_text(
        "repo: https://github.com/aladdinoo/"
        "Data-Quality-Validation-Platform-v2.git", "f.txt")
    assert v == []


def test_sha256_not_flagged():
    v = scan_text(
        "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009f"
        "dd7be9fc2276", "f.txt")
    assert v == []


def test_unc_share_detected():
    # plain (non-raw) string: text is \\fileserver\evidence\run1.csv
    v = scan_text("share \\\\fileserver\\evidence\\run1.csv", "f.txt")
    assert any(x["rule"] == "unc_share" for x in v)


def test_tilde_user_detected():
    v = scan_text("home is ~dave/project", "f.txt")
    assert any(x["rule"] == "tilde_named_user" for x in v)


# ---------------------------------------------------- gate behavior

def test_gate_fails_on_machine_path(repo):
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/example.json",
              '{"command": "/home/z/repo/scripts/run.py"}')
        reg = make_registry(root, [])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/example.json"],
            base_dirs=["docs"])
        assert rep["verdict"] == "FAIL"
        assert rep["violation_count"] >= 1


def test_gate_passes_on_clean_scope(repo):
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/example.json",
              '{"command": "python scripts/run.py"}')
        reg = make_registry(root, [])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/example.json"],
            base_dirs=["docs"])
        assert rep["verdict"] == "PASS"
        assert rep["violation_count"] == 0


def test_documented_example_allowed_only_via_exact_exception():
    content = ("Documentation example (do not run):\n"
               r"    dqvp validate --csv C:\data\consumer.csv" + "\n")
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/example.md", content)
        # 1) without the exception the gate fails
        reg = make_registry(root, [])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/example.md"], base_dirs=[])
        assert rep["verdict"] == "FAIL"
        # 2) with the exact-path documented exception it passes
        reg2 = make_registry(root, [{
            "path": "docs/example.md",
            "reason": "documentation example of a Windows path",
            "classification": "documented_example",
        }])
        rep2 = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg2), base_files=["docs/example.md"], base_dirs=[])
        assert rep2["verdict"] == "PASS"
        assert rep2["exception_registry"]["granted"][0]["applied"] is True


def test_exception_is_path_specific_not_content_specific():
    content = '{"path": "/home/z/repo/data.csv"}'
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", content)
        write(root, "docs/b.json", content)  # identical content
        reg = make_registry(root, [{
            "path": "docs/a.json",
            "reason": "documented fixture",
            "classification": "documented_test_fixture",
        }])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json", "docs/b.json"],
            base_dirs=[])
        assert rep["verdict"] == "FAIL"
        flagged = {v["source"] for v in rep["violations"]}
        assert flagged == {"docs/b.json"}


def test_overbroad_registry_fails_the_gate():
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        reg = make_registry(root, [{
            "path": "docs/",  # directory — forbidden
            "reason": "global exemption attempt",
            "classification": "documented_test_fixture",
        }])
        problems = validate_exception_registry(json.load(open(
            os.path.join(root, reg), encoding="utf-8")))
        assert any("over-broad" in p for p in problems)
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json"], base_dirs=[])
        assert rep["verdict"] == "FAIL"
        assert rep["exception_registry"]["registry_problems"]


def test_pattern_registry_fails_the_gate():
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        reg = make_registry(root, [{
            "path": "docs/*.json",  # glob — forbidden
            "reason": "glob attempt",
            "classification": "documented_test_fixture",
        }])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json"], base_dirs=[])
        assert rep["verdict"] == "FAIL"


def test_unknown_classification_registry_fails():
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        reg = make_registry(root, [{
            "path": "docs/a.json",
            "reason": "mystery",
            "classification": "ignore_everything",  # not a valid class
        }])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json"], base_dirs=[])
        assert rep["verdict"] == "FAIL"


def test_malformed_registry_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        bad = write(root, "bad.json", "{not json")
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, bad), base_files=["docs/a.json"], base_dirs=[])
        assert rep["verdict"] == "FAIL"
        assert any("unreadable" in p for p in
                   rep["exception_registry"]["registry_problems"])


def test_missing_scope_file_fails(repo):
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        reg = make_registry(root, [])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json", "docs/gone.json"],
            base_dirs=[])
        assert rep["verdict"] == "FAIL"
        assert "docs/gone.json" in rep["scope"]["missing_scope_entries"]


def test_stale_exception_reported(repo):
    with tempfile.TemporaryDirectory() as td:
        root = td
        write(root, "docs/a.json", '{"x": 1}')
        reg = make_registry(root, [{
            "path": "docs/removed_fixture.json",
            "reason": "documented fixture that no longer exists",
            "classification": "documented_test_fixture",
        }])
        rep = run_gate(repo_root=root, exceptions_path=os.path.join(
            root, reg), base_files=["docs/a.json"], base_dirs=[])
        # stale exception alone does not fail a clean gate, but it is
        # REPORTED so it can never silently linger
        assert rep["exception_registry"]["stale_exceptions"] == [
            "docs/removed_fixture.json"]


# ------------------------------------------- real-repo smoke checks

def test_real_repo_gate_report_current():
    """The shipped gate report reflects the real repository scope."""
    report_path = os.path.join(
        REPO_ROOT, "evidence", "FINAL_CLEAN_REBUILD_RELEASE_2026-09-18",
        "release_gate", "absolute_path_gate_report.json")
    if not os.path.isfile(report_path):
        pytest.skip("gate report not yet generated in this checkout")
    with open(report_path, encoding="utf-8") as f:
        rep = json.load(f)
    assert rep["verdict"] in ("PASS", "FAIL")
    assert rep["gate_version"] == "1.0.0"
    # every granted exception carries its reason + classification
    for e in rep["exception_registry"]["granted"]:
        assert e["reason"]
        assert e["classification"]
