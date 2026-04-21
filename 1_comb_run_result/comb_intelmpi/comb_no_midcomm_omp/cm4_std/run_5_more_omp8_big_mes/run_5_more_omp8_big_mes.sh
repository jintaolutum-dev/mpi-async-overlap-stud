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

export OMP_NUM_THREADS=8
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN

ln -sf ~/comb/build_1_intelmpi_omp/bin/comb .

run_case "more_omp8_bigmes" srun -n 4 --ntasks-per-node=2 -c 8 --cpu-bind=cores bash -lc '
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