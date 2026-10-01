"""Hardened execution orchestrator — wires layers A-H around the engine.

Execution order (fail-closed; the first blocking verdict stops the
pipeline and no engine subprocess is started):

1. Layer A  input contract firewall        (INPUT_CONTRACT_REJECTED -> stop)
2. Layer F  schema evolution guard         (SCHEMA_INCOMPATIBLE or
                                            REQUIRES_AUTHORIZATION -> stop)
3. Layer G  reference-data versioning      (REFERENCE_DATA_INCOMPLETE -> stop)
4. Layer B  execution authorization gate   (AUTHORIZATION_REJECTED -> stop)
5. Layer C  idempotency ledger check       (DUPLICATE_BLOCKED / LEDGER_
                                            UNUSABLE -> stop;
                                            IDEMPOTENT_COMPLETE -> done)
6. Layer H  pre-execution resource guard   (trip -> stop)
7.          engine subprocess under Layer H runtime monitor
   (engine argv is a TEMPLATE: ``{OUTPUT_DIR}`` and ``{INPUT}``
   placeholders are substituted with the staging directory and the
   input path, so the engine always writes into staging)
8. Layer H  post-execution output guard    (trip -> clean failure)
9. Layer D  atomic output commit           (failure -> clean failure)
10. Layer C register committed outputs     (ledger finalization)

Every step appends its structured verdict to the machine-readable
execution report. The report verdict is
``HARDENED_EXECUTION_PASS`` only when every participating layer passed
AND the engine exited 0 AND the atomic commit completed AND the ledger
finalized; anything else is ``HARDENED_EXECUTION_FAIL`` with explicit
reasons (never a silent pass).

Layer E (checkpoint contract) is consulted whenever a blocked PARTIAL
state is encountered, so the report documents WHY resume is refused.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from data_quality_platform.hardening import (
    HARDENING_LAYER_VERSION,
    HARDENING_RELEASE_ID,
)
from data_quality_platform.hardening.input_contract import (
    validate_input_contract,
)
from data_quality_platform.hardening.schema_guard import (
    assess_schema_evolution,
)
from data_quality_platform.hardening.reference_data import (
    fingerprint_reference_data,
)
from data_quality_platform.hardening.authorization import (
    AuthorizationScope,
    evaluate_authorization,
    observe_scope,
)
from data_quality_platform.hardening.idempotency import (
    ExecutionLedger,
    VERDICT_IDEMPOTENT,
    VERDICT_NEW,
)
from data_quality_platform.hardening.checkpoint_contract import (
    evaluate_resume_request,
)
from data_quality_platform.hardening.resource_guard import (
    ExecutionMonitor,
    ResourceLimits,
    check_post_execution,
    check_pre_execution,
    guard_result_from_error,
)
from data_quality_platform.hardening.atomic_commit import (
    commit_directory_atomically,
    discard_staging,
    staging_directory,
    write_partial_manifest,
)

VERDICT_PASS = "HARDENED_EXECUTION_PASS"
VERDICT_FAIL = "HARDENED_EXECUTION_FAIL"
VERDICT_IDEMPOTENT_COMPLETE = "HARDENED_EXECUTION_IDEMPOTENT_COMPLETE"

LEDGER_FILENAME = "execution_ledger.json"


@dataclass
class HardenedExecutionSpec:
    """Everything the orchestrator needs to run one hardened execution."""

    input_path: str
    expected_input_sha256: str
    authorized_columns: List[str]
    v1_rules_path: str
    reference_data_paths: Dict[str, str]
    config: dict
    execution_mode: str
    # engine argv template; '{OUTPUT_DIR}' -> staging dir,
    # '{INPUT}' -> spec.input_path
    engine_argv: List[str]
    engine_cwd: str
    engine_python: str
    output_member_names: List[str]
    work_dir: str
    final_dir: str
    granted_scope: Optional[AuthorizationScope] = None
    column_types: Optional[Dict[str, str]] = None
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    verify_hook: Optional[Callable[[str], bool]] = None
    run_label: str = "hardened-execution"


@dataclass
class HardenedExecutionReport:
    release_id: str = HARDENING_RELEASE_ID
    layer_bundle_version: str = HARDENING_LAYER_VERSION
    run_label: str = ""
    verdict: str = VERDICT_FAIL
    reasons: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict in (VERDICT_PASS,
                                VERDICT_IDEMPOTENT_COMPLETE)

    def add_layer(self, result) -> None:
        self.layers.append(result.as_dict())

    def as_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "layer_bundle_version": self.layer_bundle_version,
            "run_label": self.run_label,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "layers": list(self.layers),
            "details": dict(self.details),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def _read_header(input_path: str) -> List[str]:
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        return next(csv.reader(f), [])


def run_hardened_execution(spec: HardenedExecutionSpec) \
        -> HardenedExecutionReport:
    report = HardenedExecutionReport(run_label=spec.run_label)
    add = report.reasons.append
    os.makedirs(spec.work_dir, exist_ok=True)
    ledger = ExecutionLedger(os.path.join(spec.work_dir, LEDGER_FILENAME))

    # ── 1. Layer A: input contract firewall ─────────────────────────────
    layer_a = validate_input_contract(
        spec.input_path,
        spec.expected_input_sha256,
        spec.authorized_columns,
        column_types=spec.column_types,
        max_rows=spec.limits.max_rows,
        max_input_bytes=spec.limits.max_input_bytes,
    )
    report.add_layer(layer_a)
    if not layer_a.accepted:
        add("Layer A rejected the input; execution never started")
        report.details["stopped_at"] = "A"
        return report

    # ── 2. Layer F: schema evolution guard ──────────────────────────────
    observed_header = _read_header(spec.input_path)
    layer_f = assess_schema_evolution(
        observed_header, spec.authorized_columns,
        observed_types=None, authorized_types=spec.column_types)
    report.add_layer(layer_f)
    if layer_f.blocked:
        add("Layer F classified the schema as INCOMPATIBLE; execution "
            "never started")
        report.details["stopped_at"] = "F"
        return report
    if layer_f.verdict == "REQUIRES_AUTHORIZATION":
        add("Layer F classified the schema as REQUIRES_AUTHORIZATION "
            "(additive columns) but no updated grant was supplied; "
            "execution never started")
        report.details["stopped_at"] = "F"
        return report

    # ── 3. Layer G: reference-data versioning ───────────────────────────
    layer_g = fingerprint_reference_data(spec.reference_data_paths)
    report.add_layer(layer_g)
    if not layer_g.pinned:
        add("Layer G could not pin the reference data; execution never "
            "started")
        report.details["stopped_at"] = "G"
        return report

    # ── 4. Layer B: execution authorization gate ────────────────────────
    software_paths = default_software_paths(spec.v1_rules_path)
    try:
        observed_scope = observe_scope(
            input_path=spec.input_path,
            authorized_columns=spec.authorized_columns,
            v1_rules_path=spec.v1_rules_path,
            reference_data_paths=spec.reference_data_paths,
            config=spec.config,
            execution_mode=spec.execution_mode,
            software_paths=software_paths,
        )
    except Exception as exc:
        observed_scope = None
        report.details["scope_observation_error"] = repr(exc)
    layer_b = evaluate_authorization(spec.granted_scope, observed_scope)
    report.add_layer(layer_b)
    if not layer_b.authorized:
        add("Layer B refused authorization; execution never started")
        report.details["stopped_at"] = "B"
        return report
    identity_sha = observed_scope.identity_sha256()
    report.details["execution_identity_sha256"] = identity_sha

    # ── 5. Layer C: idempotency ledger check ────────────────────────────
    expected_outputs = [
        os.path.join(spec.final_dir, name)
        for name in spec.output_member_names
    ]
    layer_c = ledger.check_execution(identity_sha, expected_outputs)
    report.add_layer(layer_c)
    if layer_c.verdict == VERDICT_IDEMPOTENT:
        report.verdict = VERDICT_IDEMPOTENT_COMPLETE
        report.details["stopped_at"] = "C-idempotent"
        report.details["committed_outputs"] = expected_outputs
        return report
    if layer_c.verdict != VERDICT_NEW:
        add(f"Layer C blocked execution ({layer_c.verdict})")
        resume = evaluate_resume_request({})
        report.details["stopped_at"] = "C"
        report.details["layer_e_resume_decision"] = resume.as_dict()
        return report
    partial = ledger.register_partial(identity_sha)
    if partial.verdict != VERDICT_NEW:
        add("Layer C could not record the partial marker; execution "
            "never started")
        report.details["stopped_at"] = "C-partial"
        return report

    # ── 6. Layer H: pre-execution resource guard ────────────────────────
    pre = check_pre_execution(spec.limits, spec.input_path)
    report.add_layer(pre)
    if not pre.pass_:
        add(f"Layer H tripped before execution ({pre.trip_reason})")
        ledger.clear_partial(identity_sha)
        report.details["stopped_at"] = "H-pre"
        return report

    # ── 7. engine subprocess under the runtime monitor ──────────────────
    staging_dir = staging_directory(spec.work_dir, identity_sha)
    discard_staging(staging_dir)
    write_partial_manifest(
        staging_dir, identity_sha, spec.output_member_names)
    argv = [spec.engine_python] + [
        arg.replace("{OUTPUT_DIR}", staging_dir)
           .replace("{INPUT}", spec.input_path)
        for arg in spec.engine_argv
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            argv, cwd=spec.engine_cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        monitor = ExecutionMonitor(spec.limits)
        monitor.start(proc)
        stdout, stderr = proc.communicate()
        runtime = monitor.finish(proc.returncode)
    except Exception as exc:
        runtime = guard_result_from_error(exc)
        stdout = stderr = ""
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
    report.add_layer(runtime)
    report.details["engine_argv_resolved"] = argv
    report.details["engine_stdout_tail"] = (stdout or "")[-2000:]
    report.details["engine_stderr_tail"] = (stderr or "")[-2000:]
    engine_returncode = proc.returncode if proc is not None else None
    if not runtime.pass_ or engine_returncode != 0:
        add(f"engine execution failed (returncode="
            f"{engine_returncode}, guard="
            f"{runtime.verdict})")
        discard_staging(staging_dir)
        ledger.clear_partial(identity_sha)
        report.details["stopped_at"] = "engine"
        return report

    # ── 8. Layer H: post-execution output guard ─────────────────────────
    produced = [
        os.path.join(staging_dir, name)
        for name in spec.output_member_names
    ]
    post = check_post_execution(spec.limits, produced)
    report.add_layer(post)
    if not post.pass_:
        add(f"Layer H tripped after execution ({post.trip_reason})")
        discard_staging(staging_dir)
        ledger.clear_partial(identity_sha)
        report.details["stopped_at"] = "H-post"
        return report

    # ── 9. Layer D: atomic output commit ────────────────────────────────
    commit = commit_directory_atomically(
        staging_dir, spec.final_dir, verify_hook=spec.verify_hook)
    report.add_layer(commit)
    if not commit.committed:
        add("Layer D could not atomically commit the outputs")
        discard_staging(staging_dir)
        ledger.clear_partial(identity_sha)
        report.details["stopped_at"] = "D"
        return report

    # ── 10. Layer C: ledger finalization ────────────────────────────────
    final = ledger.register_committed(identity_sha, expected_outputs)
    report.add_layer(final)
    if final.verdict != VERDICT_IDEMPOTENT:
        add("Layer C could not finalize the committed ledger entry")
        report.details["stopped_at"] = "C-final"
        return report

    report.verdict = VERDICT_PASS
    report.details["committed_outputs"] = expected_outputs
    report.details["committed_manifest_sha256"] = commit.details.get(
        "committed_manifest_sha256")
    return report


def default_software_paths(v1_rules_path: str) -> Dict[str, str]:
    """Canonical software identity map: the 9 hardening modules + V1."""
    return {
        "hardening.input_contract": _module_path(
            "data_quality_platform.hardening.input_contract"),
        "hardening.authorization": _module_path(
            "data_quality_platform.hardening.authorization"),
        "hardening.idempotency": _module_path(
            "data_quality_platform.hardening.idempotency"),
        "hardening.atomic_commit": _module_path(
            "data_quality_platform.hardening.atomic_commit"),
        "hardening.checkpoint_contract": _module_path(
            "data_quality_platform.hardening.checkpoint_contract"),
        "hardening.schema_guard": _module_path(
            "data_quality_platform.hardening.schema_guard"),
        "hardening.reference_data": _module_path(
            "data_quality_platform.hardening.reference_data"),
        "hardening.resource_guard": _module_path(
            "data_quality_platform.hardening.resource_guard"),
        "hardening.pipeline": _module_path(
            "data_quality_platform.hardening.pipeline"),
        "frozen.v1_rules": v1_rules_path,
    }


def _module_path(module_name: str) -> str:
    import importlib
    module = importlib.import_module(module_name)
    return os.path.abspath(module.__file__)
