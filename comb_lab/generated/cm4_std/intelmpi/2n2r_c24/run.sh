#!/bin/bash
#SBATCH -J comb_bundle_intelmpi_2n2r_c24
#SBATCH -D /dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_std/intelmpi/2n2r_c24
#SBATCH -o ./bundle.%j.txt
#SBATCH --get-user-env
#SBATCH --export=NONE
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_std
#SBATCH --qos=cm4_std
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --time=08:00:00

# Bundle parameter summary:
# MPI: intelmpi; protocol: I_MPI_FABRICS=shm:ofi, I_MPI_OFI_PROVIDER=verbs, I_MPI_HYDRA_IFACE=ib0.8001, I_MPI_DEBUG=5
# Topology: 2n2r_c24; nodes=2; ranks/node=1; CPUs/rank=56
# Payloads: scan_g8_v1(size=8_8_8,ghost=1_1_1,vars=1,cycles=100,target_us=14,measured median); scan_g8_v2(size=8_8_8,ghost=1_1_1,vars=2,cycles=100,target_us=13,measured median); scan_g8_v3(size=8_8_8,ghost=1_1_1,vars=3,cycles=100,target_us=22,measured median); scan_g8_v4(size=8_8_8,ghost=1_1_1,vars=4,cycles=100,target_us=16,measured median); scan_g8_v6(size=8_8_8,ghost=1_1_1,vars=6,cycles=100,target_us=27,measured median); scan_g8_v8(size=8_8_8,ghost=1_1_1,vars=8,cycles=100,target_us=23,measured median); scan_g8_v10(size=8_8_8,ghost=1_1_1,vars=10,cycles=100,target_us=40,measured median); scan_g8_v12(size=8_8_8,ghost=1_1_1,vars=12,cycles=100,target_us=62,measured median); scan_g32_v1(size=32_32_32,ghost=1_1_1,vars=1,cycles=100,target_us=33,measured median); scan_g32_v2(size=32_32_32,ghost=1_1_1,vars=2,cycles=100,target_us=56,measured median); scan_g32_v4(size=32_32_32,ghost=1_1_1,vars=4,cycles=100,target_us=30,measured median); scan_g32_v8(size=32_32_32,ghost=1_1_1,vars=8,cycles=100,target_us=125,measured median); scan_g32_v16(size=32_32_32,ghost=1_1_1,vars=16,cycles=100,target_us=203,measured median); scan_g32_v32(size=32_32_32,ghost=1_1_1,vars=32,cycles=100,target_us=202,interpolated); scan_g32_v64(size=32_32_32,ghost=1_1_1,vars=64,cycles=100,target_us=199,interpolated); scan_g32_v128(size=32_32_32,ghost=1_1_1,vars=128,cycles=100,target_us=195,interpolated); scan_g32_v192(size=32_32_32,ghost=1_1_1,vars=192,cycles=100,target_us=190,measured median); scan_g32_v256(size=32_32_32,ghost=1_1_1,vars=256,cycles=100,target_us=185,extrapolated); scan_g32_v336(size=32_32_32,ghost=1_1_1,vars=336,cycles=100,target_us=179,extrapolated)
# Compute modes: midcomm, no_midcomm; repetitions: run_001, run_002, run_003
# Child scripts: 114 total, 10 cases per child, executed serially in listed order.
# Results stay in each child's payload/compute/run_### directory; bundle_status.tsv records PASS/FAIL.

set -uo pipefail

if [[ -n "${SLURM_JOB_ID:-}" ]]; then
    SCRIPT_DIR="${PWD}"
else
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fi
STATUS_FILE="${SCRIPT_DIR}/bundle_status.tsv"
CHILD_SCRIPTS=(
    "msg_x512B_y256B_z256B/midcomm/run_001/run.sh"
    "msg_x512B_y256B_z256B/no_midcomm/run_001/run.sh"
    "msg_x1KiB_y512B_z512B/midcomm/run_001/run.sh"
    "msg_x1KiB_y512B_z512B/no_midcomm/run_001/run.sh"
    "msg_x1KiB_y768B_z768B/midcomm/run_001/run.sh"
    "msg_x1KiB_y768B_z768B/no_midcomm/run_001/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/midcomm/run_001/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/no_midcomm/run_001/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/midcomm/run_001/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/no_midcomm/run_001/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/midcomm/run_001/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/no_midcomm/run_001/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/midcomm/run_001/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/no_midcomm/run_001/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/midcomm/run_001/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/no_midcomm/run_001/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/midcomm/run_001/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/no_midcomm/run_001/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/midcomm/run_001/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/no_midcomm/run_001/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/midcomm/run_001/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/no_midcomm/run_001/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/midcomm/run_001/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/no_midcomm/run_001/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/midcomm/run_001/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/no_midcomm/run_001/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/midcomm/run_001/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/no_midcomm/run_001/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/midcomm/run_001/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/no_midcomm/run_001/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/midcomm/run_001/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/no_midcomm/run_001/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/midcomm/run_001/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/no_midcomm/run_001/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/midcomm/run_001/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/no_midcomm/run_001/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/midcomm/run_001/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/no_midcomm/run_001/run.sh"
    "msg_x512B_y256B_z256B/midcomm/run_002/run.sh"
    "msg_x512B_y256B_z256B/no_midcomm/run_002/run.sh"
    "msg_x1KiB_y512B_z512B/midcomm/run_002/run.sh"
    "msg_x1KiB_y512B_z512B/no_midcomm/run_002/run.sh"
    "msg_x1KiB_y768B_z768B/midcomm/run_002/run.sh"
    "msg_x1KiB_y768B_z768B/no_midcomm/run_002/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/midcomm/run_002/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/no_midcomm/run_002/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/midcomm/run_002/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/no_midcomm/run_002/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/midcomm/run_002/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/no_midcomm/run_002/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/midcomm/run_002/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/no_midcomm/run_002/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/midcomm/run_002/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/no_midcomm/run_002/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/midcomm/run_002/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/no_midcomm/run_002/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/midcomm/run_002/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/no_midcomm/run_002/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/midcomm/run_002/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/no_midcomm/run_002/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/midcomm/run_002/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/no_midcomm/run_002/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/midcomm/run_002/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/no_midcomm/run_002/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/midcomm/run_002/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/no_midcomm/run_002/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/midcomm/run_002/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/no_midcomm/run_002/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/midcomm/run_002/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/no_midcomm/run_002/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/midcomm/run_002/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/no_midcomm/run_002/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/midcomm/run_002/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/no_midcomm/run_002/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/midcomm/run_002/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/no_midcomm/run_002/run.sh"
    "msg_x512B_y256B_z256B/midcomm/run_003/run.sh"
    "msg_x512B_y256B_z256B/no_midcomm/run_003/run.sh"
    "msg_x1KiB_y512B_z512B/midcomm/run_003/run.sh"
    "msg_x1KiB_y512B_z512B/no_midcomm/run_003/run.sh"
    "msg_x1KiB_y768B_z768B/midcomm/run_003/run.sh"
    "msg_x1KiB_y768B_z768B/no_midcomm/run_003/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/midcomm/run_003/run.sh"
    "msg_x2KiB_y1KiB_z1KiB/no_midcomm/run_003/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/midcomm/run_003/run.sh"
    "msg_x3KiB_y1KiB_z1KiB/no_midcomm/run_003/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/midcomm/run_003/run.sh"
    "msg_x4KiB_y2KiB_z2KiB/no_midcomm/run_003/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/midcomm/run_003/run.sh"
    "msg_x5KiB_y2KiB_z2KiB/no_midcomm/run_003/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/midcomm/run_003/run.sh"
    "msg_x6KiB_y3KiB_z3KiB/no_midcomm/run_003/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/midcomm/run_003/run.sh"
    "msg_x8KiB_y4KiB_z4KiB/no_midcomm/run_003/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/midcomm/run_003/run.sh"
    "msg_x16KiB_y8KiB_z8KiB/no_midcomm/run_003/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/midcomm/run_003/run.sh"
    "msg_x32KiB_y16KiB_z16KiB/no_midcomm/run_003/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/midcomm/run_003/run.sh"
    "msg_x64KiB_y32KiB_z32KiB/no_midcomm/run_003/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/midcomm/run_003/run.sh"
    "msg_x128KiB_y64KiB_z64KiB/no_midcomm/run_003/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/midcomm/run_003/run.sh"
    "msg_x256KiB_y128KiB_z128KiB/no_midcomm/run_003/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/midcomm/run_003/run.sh"
    "msg_x512KiB_y256KiB_z256KiB/no_midcomm/run_003/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/midcomm/run_003/run.sh"
    "msg_x1.00MiB_y512KiB_z512KiB/no_midcomm/run_003/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/midcomm/run_003/run.sh"
    "msg_x1.50MiB_y768KiB_z768KiB/no_midcomm/run_003/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/midcomm/run_003/run.sh"
    "msg_x2.00MiB_y1.00MiB_z1.00MiB/no_midcomm/run_003/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/midcomm/run_003/run.sh"
    "msg_x2.62MiB_y1.31MiB_z1.31MiB/no_midcomm/run_003/run.sh"
)

printf 'timestamp_utc\tchild\tstatus\texit_code\n' > "${STATUS_FILE}"
failures=0
for relative in "${CHILD_SCRIPTS[@]}"; do
    child="${SCRIPT_DIR}/${relative}"
    if [[ ! -f "${child}" ]]; then
        printf '%s\t%s\tMISSING\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${relative}" 2 >> "${STATUS_FILE}"
        failures=$((failures + 1))
        continue
    fi
    echo "===== START ${relative} $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    child_job_name=$(sed -n -e 's/^# BUNDLE_JOB_NAME=//p' -e 's/^#SBATCH -J //p' "${child}" | head -n 1)
    child_stdout="$(dirname "${child}")/${child_job_name}.${SLURM_JOB_ID:-manual}.$(hostname -s).out"
    if (cd "$(dirname "${child}")" && bash "$(basename "${child}")") > "${child_stdout}" 2>&1; then
        rc=0; status=PASS
    else
        rc=$?; status=FAIL; failures=$((failures + 1))
    fi
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${relative}" "${status}" "${rc}" >> "${STATUS_FILE}"
    echo "===== END ${relative} status=${status} rc=${rc} output=${child_stdout} ====="
done

echo "Bundle complete: total=${#CHILD_SCRIPTS[@]} failures=${failures} status_file=${STATUS_FILE}"
(( failures == 0 ))
