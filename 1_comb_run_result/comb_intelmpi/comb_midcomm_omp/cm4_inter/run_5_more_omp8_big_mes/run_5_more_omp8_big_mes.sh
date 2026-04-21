#!/bin/bash
#SBATCH -J comb_omp8_bigmes
#SBATCH -D ./
#SBATCH -o ./%x.%j.%N.out
#SBATCH --get-user-env
#SBATCH --export=NONE
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_std
#SBATCH --qos=cm4_std
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=28
#SBATCH --time=00:30:00

module load slurm_setup
module use /lrz/sys/spack/release/24.4.0/modules/MPI-sapphirerapids
module use /lrz/sys/spack/release/24.4.0/modules/sapphirerapids
module unload openmpi/4.1.7-gcc13
module load stack/24.4.0
module load intel-mpi/2021.16.0

run_case() {
     local label="$1"
     shift
     : > "${label}.log"
     echo | tee -a "${label}.log"
     echo "===== ${label} =====" | tee -a "${label}.log"
     "$@" 2>&1 | tee -a "${label}.log"
     local rc=${PIPESTATUS[0]}
     echo "===== ${label} exit code: ${rc} =====" | tee -a "${label}.log"
     return ${rc}
}

  remap_case_outputs() {
    local from_id="$1"
    local to_id="$2"

    for path in Comb_${from_id}_proc???? Comb_${from_id}_summary Comb_${from_id}_summary.csv; do
      if [[ -e "${path}" ]]; then
        mv "${path}" "${path/Comb_${from_id}/Comb_${to_id}}"
      fi
    done
  }

export OMP_NUM_THREADS=8
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN

ln -sf ~/comb_with_compute/build_1_intelmpi_omp/bin/comb .

run_case "01_async0_c8_waitall" srun -n 4 --ntasks-per-node=2 -c 8 --cpu-bind=cores bash -lc '
allowed=$(awk "/Cpus_allowed_list/ {print \$2}" /proc/self/status)
cpu_array=()
IFS="," read -r -a cpu_ranges <<< "$allowed"
for range in "${cpu_ranges[@]}"; do
  if [[ "$range" == *-* ]]; then
    start_cpu=${range%-*}
    end_cpu=${range#*-}
    for ((cpu = start_cpu; cpu <= end_cpu; ++cpu)); do
      cpu_array+=("$cpu")
    done
  else
    cpu_array+=("$range")
  fi
done
cpus_per_task=${SLURM_CPUS_PER_TASK:-8}
offset=0
end=$((cpus_per_task - 1))
if (( offset > end || end >= ${#cpu_array[@]} )); then
  echo "rank=${SLURM_PROCID} local_rank=${SLURM_LOCALID} host=$(hostname) ERROR: cpu_list indices out of range! allowed=$allowed cpu_array=${cpu_array[*]} offset=$offset end=$end"
  exit 1
else
  cpu_list="${cpu_array[$offset]}"
  for ((idx = offset + 1; idx <= end; ++idx)); do
    cpu_list+="\,${cpu_array[$idx]}"
  done
  echo "rank=${SLURM_PROCID} local_rank=${SLURM_LOCALID} host=$(hostname) bind_mode=slurm allowed=$allowed main_cpu_list=$cpu_list"
  exec ./comb 512_512_512 \
    -divide 2_2_1 \
    -periodic 1_1_1 \
    -ghost 8_8_8 \
    -vars 3 \
    -comm cutoff 250 \
    -comm enable mpi \
    -comm post_recv wait_all \
    -comm post_send wait_all \
    -comm wait_recv wait_all \
    -comm wait_send wait_all \
    -exec enable omp \
    -print_message_sizes \
    -print_packing_sizes
fi
'

# 强异步版本（1个线程异步进程，OMP_NUM_THREADS=7）
export OMP_NUM_THREADS=7
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN

run_case "05_async1_c8_waitall" srun -n 4 --ntasks-per-node=2 -c 8 --cpu-bind=none bash -lc '
allowed=$(awk "/Cpus_allowed_list/ {print \$2}" /proc/self/status)
cpu_array=()
IFS="," read -r -a cpu_ranges <<< "$allowed"
for range in "${cpu_ranges[@]}"; do
  if [[ "$range" == *-* ]]; then
    start_cpu=${range%-*}
    end_cpu=${range#*-}
    for ((cpu = start_cpu; cpu <= end_cpu; ++cpu)); do
      cpu_array+=("$cpu")
    done
  else
    cpu_array+=("$range")
  fi
done
async_threads=${I_MPI_ASYNC_PROGRESS_THREADS:-1}
total_cpus_per_task=${SLURM_CPUS_PER_TASK:-8}
main_cpus_per_task=$((total_cpus_per_task - async_threads))
if (( main_cpus_per_task < 1 )); then
  main_cpus_per_task=1
fi
local_tasks=${SLURM_NTASKS_PER_NODE:-2}
offset=$((SLURM_LOCALID * total_cpus_per_task))
main_end=$((offset + main_cpus_per_task - 1))
async_idx=$((offset + total_cpus_per_task - 1))
if (( ${#cpu_array[@]} <= async_idx )); then
  echo "rank=${SLURM_PROCID} local_rank=${SLURM_LOCALID} host=$(hostname) has insufficient CPUs: allowed=$allowed" >&2
  exit 1
fi
cpu_list="${cpu_array[$offset]}"
for ((idx = offset + 1; idx <= main_end; ++idx)); do
  cpu_list+="\,${cpu_array[$idx]}"
done
rank_async_cpu="${cpu_array[$async_idx]}"

async_pin_list=""
for ((lrank = 0; lrank < local_tasks; ++lrank)); do
  async_idx=$((lrank * total_cpus_per_task + total_cpus_per_task - 1))
  if (( ${#cpu_array[@]} <= async_idx )); then
    echo "rank=${SLURM_PROCID} local_rank=${SLURM_LOCALID} host=$(hostname) cannot build async pin list: allowed=$allowed" >&2
    exit 1
  fi
  if [[ -n "$async_pin_list" ]]; then
    async_pin_list+=","
  fi
  async_pin_list+="${cpu_array[$async_idx]}"
done
export I_MPI_ASYNC_PROGRESS_PIN=$async_pin_list

echo "rank=${SLURM_PROCID} local_rank=${SLURM_LOCALID} host=$(hostname) bind_mode=manual allowed=$allowed total_cpus_per_rank=$total_cpus_per_task main_cpus_per_rank=$main_cpus_per_task main_cpu_list=$cpu_list rank_async_cpu=$rank_async_cpu async_cpu_list=$async_pin_list"
exec taskset -c "$cpu_list" ./comb 512_512_512 \
  -divide 2_2_1 \
  -periodic 1_1_1 \
  -ghost 8_8_8 \
  -vars 3 \
  -comm cutoff 250 \
  -comm enable mpi \
  -comm post_recv wait_all \
  -comm post_send wait_all \
  -comm wait_recv wait_all \
  -comm wait_send wait_all \
  -exec enable omp \
  -print_message_sizes \
  -print_packing_sizes
'

rm -f Comb_05_proc???? Comb_05_summary Comb_05_summary.csv
remap_case_outputs 01 05
remap_case_outputs 00 01
