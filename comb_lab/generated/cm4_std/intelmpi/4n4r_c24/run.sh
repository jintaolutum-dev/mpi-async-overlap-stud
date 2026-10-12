#!/bin/bash
#SBATCH -J comb_bundle_intelmpi_4n4r_c24
#SBATCH -D /dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_std/intelmpi/4n4r_c24
#SBATCH -o ./bundle.%j.txt
#SBATCH --get-user-env
#SBATCH --export=NONE
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_std
#SBATCH --qos=cm4_std
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=28
#SBATCH --time=08:00:00

# Bundle parameter summary:
# MPI: intelmpi; protocol: I_MPI_FABRICS=shm:ofi, I_MPI_OFI_PROVIDER=verbs, I_MPI_HYDRA_IFACE=ib0.8001, I_MPI_DEBUG=5
# Topology: 4n4r_c24; nodes=4; ranks/node=1; CPUs/rank=28
# Payloads: scan_g8_v2(size=8_8_8,ghost=1_1_1,vars=2,cycles=100,target_us=9,configured target); scan_g8_v3(size=8_8_8,ghost=1_1_1,vars=3,cycles=100,target_us=12,configured target); scan_g8_v5(size=8_8_8,ghost=1_1_1,vars=5,cycles=100,target_us=24,configured target); scan_g8_v7(size=8_8_8,ghost=1_1_1,vars=7,cycles=100,target_us=14,configured target); scan_g8_v10(size=8_8_8,ghost=1_1_1,vars=10,cycles=100,target_us=20,configured target); scan_g8_v13(size=8_8_8,ghost=1_1_1,vars=13,cycles=100,target_us=23,configured target); scan_g8_v17(size=8_8_8,ghost=1_1_1,vars=17,cycles=100,target_us=27,configured target); scan_g8_v20(size=8_8_8,ghost=1_1_1,vars=20,cycles=100,target_us=32,configured target); scan_g32_v2(size=32_32_32,ghost=1_1_1,vars=2,cycles=100,target_us=32,configured target); scan_g32_v4(size=32_32_32,ghost=1_1_1,vars=4,cycles=100,target_us=52,configured target); scan_g32_v8(size=32_32_32,ghost=1_1_1,vars=8,cycles=100,target_us=93,configured target); scan_g32_v15(size=32_32_32,ghost=1_1_1,vars=15,cycles=100,target_us=176,configured target); scan_g32_v30(size=32_32_32,ghost=1_1_1,vars=30,cycles=100,target_us=343,configured target); scan_g32_v60(size=32_32_32,ghost=1_1_1,vars=60,cycles=100,target_us=676,configured target); scan_g32_v121(size=32_32_32,ghost=1_1_1,vars=121,cycles=100,target_us=1342,configured target); scan_g32_v242(size=32_32_32,ghost=1_1_1,vars=242,cycles=100,target_us=2674,configured target); scan_g32_v363(size=32_32_32,ghost=1_1_1,vars=363,cycles=100,target_us=4006,configured target); scan_g32_v484(size=32_32_32,ghost=1_1_1,vars=484,cycles=100,target_us=5338,configured target); scan_g32_v635(size=32_32_32,ghost=1_1_1,vars=635,cycles=100,target_us=7002,configured target)
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
    "msg_x512B_y512B_z256B/midcomm/run_001/run.sh"
    "msg_x512B_y512B_z256B/no_midcomm/run_001/run.sh"
    "msg_x768B_y768B_z384B/midcomm/run_001/run.sh"
    "msg_x768B_y768B_z384B/no_midcomm/run_001/run.sh"
    "msg_x1KiB_y1KiB_z640B/midcomm/run_001/run.sh"
    "msg_x1KiB_y1KiB_z640B/no_midcomm/run_001/run.sh"
    "msg_x1KiB_y1KiB_z896B/midcomm/run_001/run.sh"
    "msg_x1KiB_y1KiB_z896B/no_midcomm/run_001/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/midcomm/run_001/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/no_midcomm/run_001/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/midcomm/run_001/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/no_midcomm/run_001/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/midcomm/run_001/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/no_midcomm/run_001/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/midcomm/run_001/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/no_midcomm/run_001/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/midcomm/run_001/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/no_midcomm/run_001/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/midcomm/run_001/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/no_midcomm/run_001/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/midcomm/run_001/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/no_midcomm/run_001/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/midcomm/run_001/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/no_midcomm/run_001/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/midcomm/run_001/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/no_midcomm/run_001/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/midcomm/run_001/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/no_midcomm/run_001/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/midcomm/run_001/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/no_midcomm/run_001/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/midcomm/run_001/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/no_midcomm/run_001/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/midcomm/run_001/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/no_midcomm/run_001/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/midcomm/run_001/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/no_midcomm/run_001/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/midcomm/run_001/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/no_midcomm/run_001/run.sh"
    "msg_x512B_y512B_z256B/midcomm/run_002/run.sh"
    "msg_x512B_y512B_z256B/no_midcomm/run_002/run.sh"
    "msg_x768B_y768B_z384B/midcomm/run_002/run.sh"
    "msg_x768B_y768B_z384B/no_midcomm/run_002/run.sh"
    "msg_x1KiB_y1KiB_z640B/midcomm/run_002/run.sh"
    "msg_x1KiB_y1KiB_z640B/no_midcomm/run_002/run.sh"
    "msg_x1KiB_y1KiB_z896B/midcomm/run_002/run.sh"
    "msg_x1KiB_y1KiB_z896B/no_midcomm/run_002/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/midcomm/run_002/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/no_midcomm/run_002/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/midcomm/run_002/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/no_midcomm/run_002/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/midcomm/run_002/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/no_midcomm/run_002/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/midcomm/run_002/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/no_midcomm/run_002/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/midcomm/run_002/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/no_midcomm/run_002/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/midcomm/run_002/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/no_midcomm/run_002/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/midcomm/run_002/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/no_midcomm/run_002/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/midcomm/run_002/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/no_midcomm/run_002/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/midcomm/run_002/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/no_midcomm/run_002/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/midcomm/run_002/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/no_midcomm/run_002/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/midcomm/run_002/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/no_midcomm/run_002/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/midcomm/run_002/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/no_midcomm/run_002/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/midcomm/run_002/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/no_midcomm/run_002/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/midcomm/run_002/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/no_midcomm/run_002/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/midcomm/run_002/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/no_midcomm/run_002/run.sh"
    "msg_x512B_y512B_z256B/midcomm/run_003/run.sh"
    "msg_x512B_y512B_z256B/no_midcomm/run_003/run.sh"
    "msg_x768B_y768B_z384B/midcomm/run_003/run.sh"
    "msg_x768B_y768B_z384B/no_midcomm/run_003/run.sh"
    "msg_x1KiB_y1KiB_z640B/midcomm/run_003/run.sh"
    "msg_x1KiB_y1KiB_z640B/no_midcomm/run_003/run.sh"
    "msg_x1KiB_y1KiB_z896B/midcomm/run_003/run.sh"
    "msg_x1KiB_y1KiB_z896B/no_midcomm/run_003/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/midcomm/run_003/run.sh"
    "msg_x2KiB_y2KiB_z1KiB/no_midcomm/run_003/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/midcomm/run_003/run.sh"
    "msg_x3KiB_y3KiB_z1KiB/no_midcomm/run_003/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/midcomm/run_003/run.sh"
    "msg_x4KiB_y4KiB_z2KiB/no_midcomm/run_003/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/midcomm/run_003/run.sh"
    "msg_x5KiB_y5KiB_z2KiB/no_midcomm/run_003/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/midcomm/run_003/run.sh"
    "msg_x8KiB_y8KiB_z4KiB/no_midcomm/run_003/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/midcomm/run_003/run.sh"
    "msg_x16KiB_y16KiB_z8KiB/no_midcomm/run_003/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/midcomm/run_003/run.sh"
    "msg_x32KiB_y32KiB_z16KiB/no_midcomm/run_003/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/midcomm/run_003/run.sh"
    "msg_x60KiB_y60KiB_z30KiB/no_midcomm/run_003/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/midcomm/run_003/run.sh"
    "msg_x120KiB_y120KiB_z60KiB/no_midcomm/run_003/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/midcomm/run_003/run.sh"
    "msg_x240KiB_y240KiB_z120KiB/no_midcomm/run_003/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/midcomm/run_003/run.sh"
    "msg_x484KiB_y484KiB_z242KiB/no_midcomm/run_003/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/midcomm/run_003/run.sh"
    "msg_x968KiB_y968KiB_z484KiB/no_midcomm/run_003/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/midcomm/run_003/run.sh"
    "msg_x1.42MiB_y1.42MiB_z726KiB/no_midcomm/run_003/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/midcomm/run_003/run.sh"
    "msg_x1.89MiB_y1.89MiB_z968KiB/no_midcomm/run_003/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/midcomm/run_003/run.sh"
    "msg_x2.48MiB_y2.48MiB_z1.24MiB/no_midcomm/run_003/run.sh"
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
