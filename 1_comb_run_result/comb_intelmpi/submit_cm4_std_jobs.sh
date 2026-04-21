#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

job_scripts=(
  "comb_midcomm_omp/cm4_std/run_3_big_mes_std/run_3_big_mes.sh"
  "comb_midcomm_omp/cm4_std/run_4_samll_mess_std/run_4_small_mess.sh"
  "comb_midcomm_omp/cm4_std/run_5_more_omp8_big_mes/run_5_more_omp8_big_mes.sh"
  "comb_no_midcomm_omp/cm4_std/run_3_big_mes_std/run_3_big_mes.sh"
  "comb_no_midcomm_omp/cm4_std/run_4_samll_mess_std/run_4_small_mess.sh"
  "comb_no_midcomm_omp/cm4_std/run_5_more_omp8_big_mes/run_5_more_omp8_big_mes.sh"
)

if ! command -v sbatch >/dev/null 2>&1; then
  echo "ERROR: sbatch not found in PATH"
  exit 1
fi

submitted_count=0

for relative_path in "${job_scripts[@]}"; do
  job_script="${SCRIPT_DIR}/${relative_path}"
  job_dir=$(dirname "${job_script}")

  if [[ ! -f "${job_script}" ]]; then
    echo "ERROR: missing job script: ${job_script}"
    exit 1
  fi

  echo "Submitting ${relative_path}"
  submit_output=$(cd "${job_dir}" && sbatch "$(basename "${job_script}")")
  echo "  ${submit_output}"
  submitted_count=$((submitted_count + 1))
done

echo "Submitted ${submitted_count} cm4_std jobs."