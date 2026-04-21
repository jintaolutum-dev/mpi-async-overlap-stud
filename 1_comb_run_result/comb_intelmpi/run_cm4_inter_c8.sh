#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

job_scripts=(
  "comb_midcomm_omp/cm4_inter/run_5_more_omp8_big_mes/run_5_more_omp8_big_mes.sh"
  "comb_no_midcomm_omp/cm4_inter/run_5_more_omp8_big_mes/run_5_more_omp8_big_mes.sh"
)

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "ERROR: no active Slurm allocation detected."
  echo "Run this script inside an interactive cm4_inter allocation, for example:"
  echo "  salloc -M inter -p cm4_inter -N 2 -n 4 --ntasks-per-node=2 -c 8 -t 01:30:00"
  exit 1
fi

if [[ "${SLURM_JOB_PARTITION:-}" != "cm4_inter" ]]; then
  echo "WARNING: current allocation partition is '${SLURM_JOB_PARTITION:-unknown}', not cm4_inter."
fi

if [[ "${SLURM_NTASKS:-0}" -lt 4 ]]; then
  echo "ERROR: this launcher requires at least 4 tasks, current SLURM_NTASKS=${SLURM_NTASKS:-unset}."
  exit 1
fi

if [[ "${SLURM_CPUS_PER_TASK:-0}" -lt 8 ]]; then
  echo "ERROR: this launcher requires at least 8 CPUs per task, current SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-unset}."
  exit 1
fi

executed_count=0

for relative_path in "${job_scripts[@]}"; do
  job_script="${SCRIPT_DIR}/${relative_path}"
  job_dir=$(dirname "${job_script}")

  if [[ ! -f "${job_script}" ]]; then
    echo "ERROR: missing job script: ${job_script}"
    exit 1
  fi

  echo "Running ${relative_path}"
  (
    cd "${job_dir}"
    bash "$(basename "${job_script}")"
  )
  executed_count=$((executed_count + 1))
done

echo "Executed ${executed_count} cm4_inter c8 jobs."