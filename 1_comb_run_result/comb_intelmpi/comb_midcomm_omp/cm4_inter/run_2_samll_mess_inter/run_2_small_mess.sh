#!/bin/bash
#SBATCH -J comb_test_4rank
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

SMALL_MESSAGE_CUTOFF=500000

run_case() {
     local label="$1"
     shift

     : > "${label}.log"
     echo | tee -a "${label}.log"
     echo "===== ${label} =====" | tee -a "${label}.log"
     if [[ -n "${CASE_LAUNCHER:-}" ]]; then
          echo "launcher=${CASE_LAUNCHER}" | tee -a "${label}.log"
     fi
     if [[ -n "${CASE_COMB_CMD:-}" ]]; then
          echo "comb_cmd=${CASE_COMB_CMD}" | tee -a "${label}.log"
     fi
     if [[ -n "${CASE_BINDING_MODE:-}" ]]; then
          echo "binding_mode=${CASE_BINDING_MODE}" | tee -a "${label}.log"
     fi

     "$@" 2>&1 | tee -a "${label}.log"
     local rc=${PIPESTATUS[0]}

     echo "===== ${label} exit code: ${rc} =====" | tee -a "${label}.log"
     return ${rc}
}

set_case_metadata() {
     local cpus_per_task="$1"
     local cpu_bind="$2"
     local wait_mode="$3"
     local binding_mode="$4"

     CASE_LAUNCHER="srun -n 4 --ntasks-per-node=2 -c ${cpus_per_task} --cpu-bind=${cpu_bind}"
     CASE_COMB_CMD="./comb 512_512_512 -divide 2_2_1 -periodic 1_1_1 -ghost 8_8_8 -vars 3 -comm cutoff ${SMALL_MESSAGE_CUTOFF} -comm enable mpi -comm post_recv wait_all -comm post_send wait_all -comm wait_recv ${wait_mode} -comm wait_send ${wait_mode} -exec enable omp -print_message_sizes -print_packing_sizes"
     CASE_BINDING_MODE="${binding_mode}"
}

run_regular_case() {
     local label="$1"
     local cpus_per_task="$2"
     local wait_mode="$3"

     set_case_metadata "${cpus_per_task}" cores "${wait_mode}" "slurm --cpu-bind=cores"

     run_case "${label}" srun -n 4 \
          --ntasks-per-node=2 \
          -c "${cpus_per_task}" \
          --cpu-bind=cores \
          bash -lc "
               allowed=\$(awk '/Cpus_allowed_list/ {print \$2}' /proc/self/status)
               cpu_array=()
               IFS=',' read -r -a cpu_ranges <<< \"\${allowed}\"
               for range in \"\${cpu_ranges[@]}\"; do
                    if [[ \"\${range}\" == *-* ]]; then
                         start_cpu=\${range%-*}
                         end_cpu=\${range#*-}
                         for ((cpu = start_cpu; cpu <= end_cpu; ++cpu)); do
                              cpu_array+=(\"\${cpu}\")
                         done
                    else
                         cpu_array+=(\"\${range}\")
                    fi
               done
               cpus_per_task=\${SLURM_CPUS_PER_TASK:-${cpus_per_task}}
               offset=0
               end=\$((cpus_per_task - 1))
               if (( offset > end || end >= \${#cpu_array[@]} )); then
                    echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) ERROR: cpu_list indices out of range! allowed=\${allowed} cpu_array=\"\${cpu_array[*]}\" offset=\${offset} end=\${end}\"
                    cpu_list=\"\"
               else
                    cpu_list=\"\${cpu_array[\${offset}]}\"
                    for ((idx = offset + 1; idx <= end; ++idx)); do
                         cpu_list+=\",\${cpu_array[\${idx}]}\"
                    done
               fi
               echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) bind_mode=slurm allowed=\${allowed} main_cpu_list=\${cpu_list}\"
               exec ./comb 512_512_512 \
                    -divide 2_2_1 \
                    -periodic 1_1_1 \
                    -ghost 8_8_8 \
                    -vars 3 \
                    -comm cutoff ${SMALL_MESSAGE_CUTOFF} \
                    -comm enable mpi \
                    -comm post_recv wait_all \
                    -comm post_send wait_all \
                    -comm wait_recv ${wait_mode} \
                    -comm wait_send ${wait_mode} \
                    -exec enable omp \
                    -print_message_sizes \
                    -print_packing_sizes
          "
}

run_async_case() {
     local label="$1"
     local cpus_per_task="$2"
     local wait_mode="$3"
     local async_threads="${I_MPI_ASYNC_PROGRESS_THREADS:-1}"

     if [[ "${async_threads}" -ne 1 ]]; then
          echo "run_async_case currently supports exactly 1 async progress thread per rank" >&2
          return 1
     fi

     set_case_metadata "${cpus_per_task}" none "${wait_mode}" "manual taskset + split main/async CPUs"

     run_case "${label}" srun -n 4 \
          --ntasks-per-node=2 \
          -c "${cpus_per_task}" \
          --cpu-bind=none \
          bash -lc "
               allowed=\$(awk '/Cpus_allowed_list/ {print \$2}' /proc/self/status)
               cpu_array=()
               IFS=',' read -r -a cpu_ranges <<< \"\${allowed}\"
               for range in \"\${cpu_ranges[@]}\"; do
                    if [[ \"\${range}\" == *-* ]]; then
                         start_cpu=\${range%-*}
                         end_cpu=\${range#*-}
                         for ((cpu = start_cpu; cpu <= end_cpu; ++cpu)); do
                              cpu_array+=(\"\${cpu}\")
                         done
                    else
                         cpu_array+=(\"\${range}\")
                    fi
               done

               async_threads=${async_threads}
               total_cpus_per_task=\${SLURM_CPUS_PER_TASK:-${cpus_per_task}}
               main_cpus_per_task=\$((total_cpus_per_task - async_threads))
               if (( main_cpus_per_task < 1 )); then
                    main_cpus_per_task=1
               fi
               local_tasks=\${SLURM_NTASKS_PER_NODE:-2}
               offset=\$((SLURM_LOCALID * total_cpus_per_task))
               main_end=\$((offset + main_cpus_per_task - 1))
               async_idx=\$((offset + total_cpus_per_task - 1))

               if [[ \${#cpu_array[@]} -le \${async_idx} ]]; then
                    echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) has insufficient CPUs: allowed=\${allowed}\" >&2
                    exit 1
               fi

               cpu_list=\"\${cpu_array[\${offset}]}\"
               for ((idx = offset + 1; idx <= main_end; ++idx)); do
                    cpu_list+=\",\${cpu_array[\${idx}]}\"
               done

               rank_async_cpu=\"\${cpu_array[\${async_idx}]}\"

               async_pin_list=\"\"
               for ((lrank = 0; lrank < local_tasks; ++lrank)); do
                    async_idx=\$((lrank * total_cpus_per_task + total_cpus_per_task - 1))
                    if [[ \${#cpu_array[@]} -le \${async_idx} ]]; then
                         echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) cannot build async pin list: allowed=\${allowed}\" >&2
                         exit 1
                    fi
                    if [[ -n \"\${async_pin_list}\" ]]; then
                         async_pin_list+=\",\"
                    fi
                    async_pin_list+=\"\${cpu_array[\${async_idx}]}\"
               done
               export I_MPI_ASYNC_PROGRESS_PIN=\${async_pin_list}

               echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) bind_mode=manual allowed=\${allowed} total_cpus_per_rank=\${total_cpus_per_task} main_cpus_per_rank=\${main_cpus_per_task} main_cpu_list=\${cpu_list} rank_async_cpu=\${rank_async_cpu} async_cpu_list=\${async_pin_list}\"

               exec taskset -c \"\${cpu_list}\" ./comb 512_512_512 \
                    -divide 2_2_1 \
                    -periodic 1_1_1 \
                    -ghost 8_8_8 \
                    -vars 3 \
                    -comm cutoff ${SMALL_MESSAGE_CUTOFF} \
                    -comm enable mpi \
                    -comm post_recv wait_all \
                    -comm post_send wait_all \
                    -comm wait_recv ${wait_mode} \
                    -comm wait_send ${wait_mode} \
                    -exec enable omp \
                    -print_message_sizes \
                    -print_packing_sizes
          "
}

ln -sf ~/comb_with_compute/build_1_intelmpi_omp/bin/comb .

#========0
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case "00_async0_c1_waitall" 1 wait_all

#========1
export OMP_NUM_THREADS=4
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case "01_async0_c4_waitall" 4 wait_all

#========2
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case "02_async0_c1_testall" 1 test_all

#========3
export OMP_NUM_THREADS=4
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case "03_async0_c4_testall" 4 test_all

#========4
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case "04_async1_c1_waitall" 1 wait_all

#========5
export OMP_NUM_THREADS=3
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case "05_async1_c4_waitall" 4 wait_all

#========6
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case "06_async1_c1_testall" 1 test_all

#========7
export OMP_NUM_THREADS=3
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case "07_async1_c4_testall" 4 test_all

#salloc -M inter -p cm4_inter -N 2 -n 4 --ntasks-per-node=2 -c 10 -t 01:30:00
#bash run_1.sh