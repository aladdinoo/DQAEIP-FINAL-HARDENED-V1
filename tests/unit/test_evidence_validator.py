"""Evidence validator tests (DQAVP hardening, Section 4).

Positive: a real engine run produces a fully valid evidence directory.
Negative (fail closed): every corruption / tamper / contradiction /
missing-file scenario must invalidate the report.
"""

import csv
import json
import os
import shutil

import pytest

from data_quality_platform.contracts import SOURCE_COLUMNS
from data_quality_platform.validation.evidence_validator import (
    EvidenceValidationError,
    require_valid_evidence,
    validate_evidence_dir,
)
from data_quality_platform.validation.engine import ValidationEngine


def _make_csv(path, n=5):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SOURCE_COLUMNS)
        for i in range(1, n + 1):
            row = {c: "" for c in SOURCE_COLUMNS}
            row.update({"id": str(i), "email_address": f"u{i}@x.com",
                        "zip": "10001", "state": "NY", "source": "web",
                        "country": "US"})
            w.writerow([row[c] for c in SOURCE_COLUMNS])
    return str(path)


@pytest.fixture(scope="module")
def good_run(tmp_path_factory):
    """One real engine run reused across module tests."""
    base = tmp_path_factory.mktemp("good")
    src = _make_csv(base / "in.csv", 5)
    out = base / "out.csv"
    evd = base / "evidence"
    engine = ValidationEngine(run_id="evtest", evidence_dir=str(evd))
    result = engine.validate(src, str(out))
    assert result.success, result.error
    return {"evidence_dir": str(evd), "out": str(out), "src": src}


class TestValidEvidencePasses:
    def test_real_engine_run_is_valid(self, good_run):
        report = validate_evidence_dir(good_run["evidence_dir"])
        assert report["valid"] is True, report["issues"]
        assert report["run_id"] == "evtest"
        assert report["details"]["output_column_count"] == 41
        assert "required_files_exist" in report["checks_performed"]
        assert "lineage_serialization" in report["checks_performed"]
        assert "referenced_artifacts" in report["checks_performed"]

    def test_strict_wrapper_accepts_valid(self, good_run):
        report = require_valid_evidence(good_run["evidence_dir"])
        assert report["valid"] is True

    def test_lineage_row_records_are_structured_dicts(self, good_run):
        lineage = json.load(open(os.path.join(
            good_run["evidence_dir"], "lineage.json"), encoding="utf-8"))
        assert lineage["row_records"], "flagged rows expected in fixture"
        for rec in lineage["row_records"]:
            assert isinstance(rec, dict)
            for field in ("run_id", "row_number", "rule_id", "rule_version",
                         "flag_value", "row_hash", "timestamp"):
                assert field in rec


class TestFailClosed:
    def _copy(self, good_run, tmp_path):
        dest = tmp_path / "ev"
        shutil.copytree(good_run["evidence_dir"], dest)
        return dest

    def test_missing_evidence_dir(self, tmp_path):
        report = validate_evidence_dir(str(tmp_path / "nowhere"))
        assert report["valid"] is False
        assert report["issues"][0]["code"] == "evidence_dir_missing"

    def test_missing_manifest(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        os.remove(evd / "manifest.json")
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "required_file_missing"
                   for i in report["issues"])

    def test_corrupt_json(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        (evd / "manifest.json").write_text("{not json")
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "json_invalid" for i in report["issues"])

    def test_row_count_tamper(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        m["source_row_count"] = 99999
        json.dump(m, open(evd / "manifest.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        codes = [i["code"] for i in report["issues"]]
        assert "row_count_mismatch" in codes

    def test_output_file_tamper_hash_mismatch(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        out_path = m["generated_files"]["output"]
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("tampered\n")
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        codes = [i["code"] for i in report["issues"]]
        assert "file_hash_mismatch" in codes or \
            "row_count_mismatch" in codes

    def test_referenced_artifact_deleted(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        os.remove(m["generated_files"]["monitoring"])
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "referenced_artifact_missing"
                   for i in report["issues"])

    def test_run_id_mismatch(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        a = json.load(open(evd / "audit.json"))
        a["run_id"] = "different_run"
        json.dump(a, open(evd / "audit.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "run_id_mismatch" for i in report["issues"])

    def test_rule_hash_format_invalid(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        m["rule_hashes"]["email_blank"] = "ZZZ"
        json.dump(m, open(evd / "manifest.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "hash_format_invalid"
                   for i in report["issues"])

    def test_missing_rule_hash(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        del m["rule_hashes"]["zip_state_assessable"]
        json.dump(m, open(evd / "manifest.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "rule_hashes_incomplete"
                   for i in report["issues"])

    def test_failure_manifest_rejected_when_success_expected(self, good_run,
                                                              tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        m["manifest_type"] = "failure"
        json.dump(m, open(evd / "manifest.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "manifest_not_success"
                   for i in report["issues"])

    def test_contradictory_run_failed_event(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        a = json.load(open(evd / "audit.json"))
        a["events"].append({"event_type": "run_failed", "run_id": "x",
                            "timestamp": "now", "details": {
                                "error_type": "FakeError",
                                "error_message": "boom",
                                "failed_step": "x"}})
        json.dump(a, open(evd / "audit.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "contradictory_status"
                   for i in report["issues"])

    def test_lineage_repr_leak_detected(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        l = json.load(open(evd / "lineage.json"))
        l["row_records"] = [
            "<data_quality_platform.lineage.recorder.RowLineageRecord "
            "object at 0x7f0000000000>"] * 3
        l["total_row_records"] = 3
        json.dump(l, open(evd / "lineage.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        codes = [i["code"] for i in report["issues"]]
        assert "lineage_repr_leak" in codes
        assert "lineage_record_not_dict" in codes

    def test_lineage_row_record_missing_field(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        l = json.load(open(evd / "lineage.json"))
        if l["row_records"]:
            del l["row_records"][0]["rule_version"]
        json.dump(l, open(evd / "lineage.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "lineage_field_missing"
                   for i in report["issues"])

    def test_lineage_unknown_rule_reference(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        l = json.load(open(evd / "lineage.json"))
        if l["row_records"]:
            l["row_records"][0]["rule_id"] = "bogus_rule"
        json.dump(l, open(evd / "lineage.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "lineage_unknown_rule"
                   for i in report["issues"])

    def test_strict_wrapper_raises(self, good_run, tmp_path):
        evd = self._copy(good_run, tmp_path)
        os.remove(evd / "lineage.json")
        with pytest.raises(EvidenceValidationError):
            require_valid_evidence(str(evd))

    def test_flag_count_impossible_exceeds_rows_x_rules(self, good_run,
                                                         tmp_path):
        evd = self._copy(good_run, tmp_path)
        m = json.load(open(evd / "manifest.json"))
        m["flag_counts"]["email_blank"] = 10 ** 9
        json.dump(m, open(evd / "manifest.json", "w"))
        report = validate_evidence_dir(str(evd))
        assert report["valid"] is False
        assert any(i["code"] == "flag_count_impossible"
                   for i in report["issues"])
