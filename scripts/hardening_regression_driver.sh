#!/bin/bash
# DQAEIP 2026-09-19 hardened release — full certified regression battery.
# Fresh 3.2M dual-run validation via the FROZEN checker harness
# (scripts/final_3m_validation.py, byte-identical to the harness that
# produced the certified 2026-09-18 evidence).
#
# New namespaces only:
#   data:     data/generated/fresh_3m2_regression/
#   evidence: evidence/validation/2026-09-19/fresh_3m2/
#
# Expected reproduction of the certified baseline:
#   rows 3,200,000, seed 20260918, 2 passes
#   input  SHA 59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165acba5318d153
#   output SHA b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5719329a
#   25,600,000 oracle comparisons per pass, 0 mismatches, byte-identical
set -o pipefail
cd /home/z/my-project/dqvp-work/repo
PY=/home/z/my-project/dqvp-work/repo/.venv/bin/python
EV=evidence/validation/2026-09-19/fresh_3m2
DD=data/generated/fresh_3m2_regression
COMMON="--rows 3200000 --seed 20260918 --data-dir $DD --evidence-dir $EV"

echo "=== regression driver start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "checker sha256 (must be 0ef7c10c...):"
sha256sum scripts/final_3m_validation.py

for PASS_NO in 1 2; do
  echo "=== PASS $PASS_NO generate $(date -u +%H:%M:%S) ==="
  $PY scripts/final_3m_validation.py --phase generate --pass-no $PASS_NO $COMMON
  rc=$?
  echo "[generate pass$PASS_NO rc=$rc]"
  if [ $rc -ne 0 ]; then echo "DRIVER_ABORT generate pass$PASS_NO"; exit 1; fi

  echo "=== PASS $PASS_NO validate $(date -u +%H:%M:%S) ==="
  $PY scripts/final_3m_validation.py --phase validate --pass-no $PASS_NO $COMMON
  rc=$?
  echo "[validate pass$PASS_NO rc=$rc]"
  if [ $rc -ne 0 ]; then echo "DRIVER_ABORT validate pass$PASS_NO"; exit 1; fi

  echo "=== PASS $PASS_NO verify $(date -u +%H:%M:%S) ==="
  $PY scripts/final_3m_validation.py --phase verify --pass-no $PASS_NO $COMMON
  rc=$?
  echo "[verify pass$PASS_NO rc=$rc]"
  if [ $rc -ne 0 ]; then echo "DRIVER_ABORT verify pass$PASS_NO"; exit 1; fi
done

echo "=== finalize $(date -u +%H:%M:%S) ==="
$PY scripts/final_3m_validation.py --phase finalize $COMMON
rc=$?
echo "[finalize rc=$rc]"
echo "=== regression driver end $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$rc ==="
exit $rc
