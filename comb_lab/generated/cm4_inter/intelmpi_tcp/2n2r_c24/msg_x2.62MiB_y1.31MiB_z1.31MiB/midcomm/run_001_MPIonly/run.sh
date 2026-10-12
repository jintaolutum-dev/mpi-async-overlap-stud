#!/bin/bash
#SBATCH -J comb_async_scan_intelmpi_tcp_2n2r_c24_msg_x2.62MiB_y1.31MiB_z1.31MiB_midcomm
#SBATCH -D ./
#SBATCH -o ./%x.%j.%N.out
#SBATCH --get-user-env
#SBATCH --export=NONE
#SBATCH --clusters=inter
#SBATCH --partition=cm4_inter
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --time=00:30:00

# ── Module setup ─────────────────────────────────────────────────────────────
module load slurm_setup
module use /lrz/sys/spack/release/24.4.0/modules/MPI-sapphirerapids
module use /lrz/sys/spack/release/24.4.0/modules/sapphirerapids
module unload openmpi/4.1.7-gcc13
module load stack/24.4.0
module load intel-mpi/2021.16.0
export I_MPI_FABRICS="shm:ofi"
export I_MPI_OFI_PROVIDER="tcp"
export I_MPI_DEBUG="5"

# ── Paths ────────────────────────────────────────────────────────────────────
ln -sf /dss/dsshome1/02/ge63neh3/comb_with_compute/build_1_intel_dummy_com_OMP/bin/comb ./comb

NTASKS=2
NTASKS_PER_NODE=1
GRID_SIZE="32_32_32"
DIVIDE="2_1_1"
PERIODIC="1_1_1"
GHOST="1_1_1"
VARS=336
COMM_CUTOFF=250

COMPUTE_ARGS="-compute_target_us 90.0"
CYCLE_ARGS="-cycles 50"

CPU_TOPOLOGY_MAP="$(lscpu -p=CPU,SOCKET,NODE 2>/dev/null | grep -v '^#' || true)"
export CPU_TOPOLOGY_MAP

append_csv_unique() {
    local current="$1"
    local value="$2"

    [[ -z "${value}" ]] && {
        printf '%s' "${current}"
        return
    }

    case ",${current}," in
        *,${value},*) printf '%s' "${current}" ;;
        *)
            if [[ -n "${current}" ]]; then
                printf '%s,%s' "${current}" "${value}"
            else
                printf '%s' "${value}"
            fi
            ;;
    esac
}

csv_sets_intersect() {
    local left="$1"
    local right="$2"
    local item

    [[ -z "${left}" || -z "${right}" ]] && return 1

    IFS=',' read -r -a _left_items <<< "${left}"
    for item in "${_left_items[@]}"; do
        [[ -z "${item}" ]] && continue
        case ",${right}," in
            *,${item},*) return 0 ;;
        esac
    done
    return 1
}

cpu_list_topology_sets() {
    local cpu_list="$1"
    local socket_set=""
    local numa_set=""
    local cpu cpu_socket cpu_numa

    IFS=',' read -r -a _cpus <<< "${cpu_list}"
    for cpu in "${_cpus[@]}"; do
        [[ -z "${cpu}" ]] && continue
        cpu_socket=$(awk -F, -v target="${cpu}" '$1 == target {print $2; exit}' <<< "${CPU_TOPOLOGY_MAP}")
        cpu_numa=$(awk -F, -v target="${cpu}" '$1 == target {print $3; exit}' <<< "${CPU_TOPOLOGY_MAP}")
        socket_set=$(append_csv_unique "${socket_set}" "${cpu_socket}")
        numa_set=$(append_csv_unique "${numa_set}" "${cpu_numa}")
    done

    printf '%s|%s' "${socket_set:-unknown}" "${numa_set:-unknown}"
}

classify_binding_relation() {
    local main_cpu_list="$1"
    local progress_cpu_list="$2"
    local main_socket_set="$3"
    local progress_socket_set="$4"
    local main_numa_set="$5"
    local progress_numa_set="$6"

    if [[ -z "${progress_cpu_list}" ]]; then
        printf '%s' "no_progress_threads"
        return
    fi
    if csv_sets_intersect "${main_cpu_list}" "${progress_cpu_list}"; then
        printf '%s' "shared_cores"
        return
    fi
    if csv_sets_intersect "${main_numa_set}" "${progress_numa_set}"; then
        printf '%s' "same_numa"
        return
    fi
    if csv_sets_intersect "${main_socket_set}" "${progress_socket_set}"; then
        printf '%s' "same_socket"
        return
    fi
    printf '%s' "cross_socket_or_numa"
}

export -f append_csv_unique csv_sets_intersect cpu_list_topology_sets classify_binding_relation

JOB_METADATA_FILE="job_metadata.log"

detect_comm_mode_hint() {
    local value
    value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"

    if [[ "${value}" == *persistent* ]]; then
        printf '%s' "persistent"
    elif [[ "${value}" == *rma* ]]; then
        printf '%s' "rma"
    else
        printf '%s' "standard_p2p"
    fi
}

dump_env_matches() {
    local title="$1"
    local regex="$2"

    {
        echo ">>> ${title}"
        env | sort | grep -E "${regex}" || true
        echo
    } >> "${JOB_METADATA_FILE}"
}

write_job_metadata() {
    local binary_realpath
    local comm_mode_hint

    binary_realpath="$(readlink -f ./comb 2>/dev/null || printf '%s' './comb')"
    comm_mode_hint="$(detect_comm_mode_hint "${binary_realpath}")"

    : > "${JOB_METADATA_FILE}"
    {
        echo "===== job_metadata ====="
        echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "cwd=${PWD}"
        echo "submit_host=$(hostname)"
        echo "job_name=comb_async_scan_intelmpi_tcp_2n2r_c24_msg_x2.62MiB_y1.31MiB_z1.31MiB_midcomm"
        echo "experiment_name=comb_async_scan"
        echo "mpi_family=intelmpi_tcp"
        echo "topology=2n2r_c24"
        echo "grid=custom"
        echo "compute_mode=midcomm"
        echo "clusters=inter"
        echo "partition=cm4_inter"
        echo "qos=normal"
        echo "nodes=2"
        echo "ntasks=${NTASKS}"
        echo "ntasks_per_node=${NTASKS_PER_NODE}"
        echo "cpus_per_task_request=56"
        echo "runtime_cpus_per_rank=24"
        echo "grid_size=${GRID_SIZE}"
        echo "divide=${DIVIDE}"
        echo "periodic=${PERIODIC}"
        echo "ghost=${GHOST}"
        echo "vars=${VARS}"
        echo "comm_cutoff=${COMM_CUTOFF}"
        echo "compute_args=${COMPUTE_ARGS}"
        echo "slurm_job_id=${SLURM_JOB_ID:-}"
        echo "slurm_job_nodelist=${SLURM_JOB_NODELIST:-}"
        echo "comb_binary_realpath=${binary_realpath}"
        echo "comm_mode_hint=${comm_mode_hint}"
        echo
        echo ">>> module_list"
        module -t list 2>&1 || true
        echo
    } >> "${JOB_METADATA_FILE}"

    dump_env_matches "selected_env" '^(I_MPI_|FI_|UCX_|PSM2_|PSM3_|HFI_|OMP_|GOMP_CPU_AFFINITY=|SLURM_(JOB_ID|JOB_NODELIST|CPUS_PER_TASK|NTASKS|NTASKS_PER_NODE|CPUS_ON_NODE)=)'

    if command -v mpirun >/dev/null 2>&1; then
        {
            echo ">>> mpirun_version"
            mpirun --version 2>&1 | sed -n '1,20p' || true
            echo
        } >> "${JOB_METADATA_FILE}"
    fi

    if command -v fi_info >/dev/null 2>&1; then
        {
            echo ">>> fi_info_provider_list"
            fi_info -l 2>&1 | sed -n '1,80p' || true
            echo
        } >> "${JOB_METADATA_FILE}"
    fi

    if command -v ucx_info >/dev/null 2>&1; then
        {
            echo ">>> ucx_info"
            ucx_info -v 2>&1 || true
            ucx_info -c 2>/dev/null | grep -E '^(UCX_(TLS|NET_DEVICES|SOCKADDR_TLS_PRIORITY|IB_|RC_|UD_|TCP_|RNDV_))' | sed -n '1,80p' || true
            echo
        } >> "${JOB_METADATA_FILE}"
    fi

    {
        echo "===== end job_metadata ====="
        echo
    } >> "${JOB_METADATA_FILE}"
}

write_job_metadata

# ── Helper functions ─────────────────────────────────────────────────────────
run_case() {
    local label="$1"
    shift
    : > "${label}.log"
    echo | tee -a "${label}.log"
    echo "===== ${label} =====" | tee -a "${label}.log"
    [[ -n "${CASE_LAUNCHER:-}"      ]] && echo "launcher=${CASE_LAUNCHER}"      | tee -a "${label}.log"
    [[ -n "${CASE_COMB_CMD:-}"      ]] && echo "comb_cmd=${CASE_COMB_CMD}"      | tee -a "${label}.log"
    [[ -n "${CASE_BINDING_MODE:-}"  ]] && echo "binding_mode=${CASE_BINDING_MODE}" | tee -a "${label}.log"
    [[ -n "${JOB_METADATA_FILE:-}"  ]] && echo "job_metadata_file=${JOB_METADATA_FILE}" | tee -a "${label}.log"
    "$@" 2>&1 | tee -a "${label}.log"
    local rc=${PIPESTATUS[0]}
    echo "===== ${label} exit code: ${rc} =====" | tee -a "${label}.log"
    if [[ "${I_MPI_DEBUG:-0}" != "0" ]] && ! grep -q '^>>> intel_mpi_runtime_transport' "${JOB_METADATA_FILE}"; then
        {
            echo ">>> intel_mpi_runtime_transport (${label})"
            grep -Ei 'MPI startup\(\):.*(fabric|provider|network|ofi|shm)' "${label}.log" || \
                echo "No Intel MPI runtime transport lines matched; inspect ${label}.log."
            echo
        } >> "${JOB_METADATA_FILE}"
    fi
    return ${rc}
}

_comb_args() {
    local wait_mode="$1"
    echo "${GRID_SIZE} \
-divide ${DIVIDE} \
-periodic ${PERIODIC} \
-ghost ${GHOST} \
-vars ${VARS} \
-comm cutoff ${COMM_CUTOFF} \
-comm disable all \
-comm enable mpi \

-comm post_recv wait_all \
-comm post_send wait_all \
-comm wait_recv ${wait_mode} \
-comm wait_send ${wait_mode} \
-exec enable omp \
${COMPUTE_ARGS} \
${CYCLE_ARGS} \
-print_message_sizes \
-print_packing_sizes"
}

_comb_args_flat() {
    local wait_mode="$1"
    _comb_args "${wait_mode}" | tr '\n' ' '
}

set_case_metadata() {
    local cpus_per_task="$1"
    local cpu_bind="$2"
    local wait_mode="$3"
    local binding_mode="$4"

    CASE_LAUNCHER="srun -n ${NTASKS} --ntasks-per-node=${NTASKS_PER_NODE} -c ${cpus_per_task} --cpu-bind=${cpu_bind}"
    CASE_COMB_CMD="./comb $(_comb_args_flat ${wait_mode})"
    CASE_BINDING_MODE="${binding_mode}"
}

run_regular_case() {
    local label="$1" cpus_per_task="$2" wait_mode="$3"

    set_case_metadata "${cpus_per_task}" cores "${wait_mode}" "slurm --cpu-bind=cores"

    run_case "${label}" \
        srun -n ${NTASKS} --ntasks-per-node=${NTASKS_PER_NODE} \
             -c "${cpus_per_task}" --cpu-bind=cores \
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
            offset=0
            cpus_per_task=\${SLURM_CPUS_PER_TASK:-${cpus_per_task}}
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
            main_topology=\$(cpu_list_topology_sets "\${cpu_list}")
            IFS='|' read -r main_socket_set main_numa_set <<< \"\${main_topology}\"
            echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) bind_mode=slurm allowed=\${allowed} main_cpu_list=\${cpu_list} progress_cpu_list= main_socket_set=\${main_socket_set} progress_socket_set=none main_numa_set=\${main_numa_set} progress_numa_set=none binding_relation=no_progress_threads\"
            exec ./comb $(_comb_args_flat ${wait_mode})
        "
}

run_async_case() {
    local label="$1" cpus_per_task="$2" wait_mode="$3"
    local async_threads="${I_MPI_ASYNC_PROGRESS_THREADS:-1}"

    if (( async_threads < 1 )); then
        echo "run_async_case requires at least 1 async progress thread per rank" >&2
        return 1
    fi

    set_case_metadata "${cpus_per_task}" none "${wait_mode}" "manual taskset + split main/async CPUs"

    run_case "${label}" \
        srun -n ${NTASKS} --ntasks-per-node=${NTASKS_PER_NODE} \
             -c "${cpus_per_task}" --cpu-bind=none \
        bash -lc "
            allowed=\$(awk '/Cpus_allowed_list/ {print \$2}' /proc/self/status)
            cpu_array=()
            IFS=',' read -r -a cpu_ranges <<< \"\${allowed}\"
            for range in \"\${cpu_ranges[@]}\"; do
                if [[ \"\${range}\" == *-* ]]; then
                    for ((cpu=\${range%-*}; cpu<=\${range#*-}; ++cpu)); do
                        cpu_array+=(\"\${cpu}\")
                    done
                else
                    cpu_array+=(\"\${range}\")
                fi
            done
            async_threads=${async_threads}
            total_cpus_per_task=\${SLURM_CPUS_PER_TASK:-${cpus_per_task}}
            omp_threads=\${OMP_NUM_THREADS:-1}
            if (( async_threads >= total_cpus_per_task )); then
                echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) invalid async_threads=\${async_threads} for total_cpus_per_task=\${total_cpus_per_task}\" >&2
                exit 1
            fi
            main_cpus_per_task=\$((total_cpus_per_task - async_threads))
            if (( main_cpus_per_task < 1 )); then
                main_cpus_per_task=1
            fi
            if (( omp_threads > main_cpus_per_task )); then
                echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) OMP_NUM_THREADS=\${omp_threads} exceeds main_cpus_per_rank=\${main_cpus_per_task}\" >&2
                exit 1
            fi
            local_tasks=\${SLURM_NTASKS_PER_NODE:-${NTASKS_PER_NODE}}
            offset=\$((SLURM_LOCALID * total_cpus_per_task))
            main_end=\$((offset + main_cpus_per_task - 1))
            async_start=\$((offset + main_cpus_per_task))
            async_end=\$((offset + total_cpus_per_task - 1))

            if [[ \${#cpu_array[@]} -le \${async_end} ]]; then
                echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) has insufficient CPUs: allowed=\${allowed}\" >&2
                exit 1
            fi

            cpu_list=\"\${cpu_array[\${offset}]}\"
            for ((idx=offset+1; idx<=main_end; ++idx)); do
                cpu_list+=\",\${cpu_array[\${idx}]}\"
            done

            rank_async_cpu_list=\"\${cpu_array[\${async_start}]}\"
            for ((idx=async_start+1; idx<=async_end; ++idx)); do
                rank_async_cpu_list+=\",\${cpu_array[\${idx}]}\"
            done

            async_pin_list=\"\"
            for ((lrank=0; lrank<local_tasks; ++lrank)); do
                local_async_start=\$((lrank * total_cpus_per_task + main_cpus_per_task))
                local_async_end=\$((lrank * total_cpus_per_task + total_cpus_per_task - 1))
                if [[ \${#cpu_array[@]} -le \${local_async_end} ]]; then
                    echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) cannot build async pin list: allowed=\${allowed}\" >&2
                    exit 1
                fi
                for ((idx=local_async_start; idx<=local_async_end; ++idx)); do
                    if [[ -n \"\${async_pin_list}\" ]]; then
                        async_pin_list+=\",\"
                    fi
                    async_pin_list+=\"\${cpu_array[\${idx}]}\"
                done
            done

            export I_MPI_ASYNC_PROGRESS_PIN=\${async_pin_list}

            main_topology=\$(cpu_list_topology_sets \"\${cpu_list}\")
            IFS='|' read -r main_socket_set main_numa_set <<< \"\${main_topology}\"
            progress_topology=\$(cpu_list_topology_sets \"\${rank_async_cpu_list}\")
            IFS='|' read -r progress_socket_set progress_numa_set <<< \"\${progress_topology}\"
            binding_relation=\$(classify_binding_relation \"\${cpu_list}\" \"\${rank_async_cpu_list}\" \"\${main_socket_set}\" \"\${progress_socket_set}\" \"\${main_numa_set}\" \"\${progress_numa_set}\")

            echo \"rank=\${SLURM_PROCID} local_rank=\${SLURM_LOCALID} host=\$(hostname) bind_mode=manual allowed=\${allowed} total_cpus_per_rank=\${total_cpus_per_task} omp_threads=\${omp_threads} async_threads=\${async_threads} main_cpus_per_rank=\${main_cpus_per_task} main_cpu_list=\${cpu_list} progress_cpu_list=\${rank_async_cpu_list} rank_async_cpu_list=\${rank_async_cpu_list} async_cpu_list=\${async_pin_list} main_socket_set=\${main_socket_set} progress_socket_set=\${progress_socket_set} main_numa_set=\${main_numa_set} progress_numa_set=\${progress_numa_set} binding_relation=\${binding_relation}\"
            exec taskset -c \"\${cpu_list}\" ./comb $(_comb_args_flat ${wait_mode})
        "
}

# ── Cases ────────────────────────────────────────────────────────────────────
#======== 00 case_0
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case \
    "00_async0_c1_wait_all" \
    24 \
    wait_all
#======== 01 case_1
export OMP_NUM_THREADS=24
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case \
    "01_async0_c24_wait_all" \
    24 \
    wait_all
#======== 02 case_2
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case \
    "02_async0_c1_test_all" \
    24 \
    test_all
#======== 03 case_3
export OMP_NUM_THREADS=24
export I_MPI_ASYNC_PROGRESS=0
unset I_MPI_ASYNC_PROGRESS_THREADS
unset I_MPI_ASYNC_PROGRESS_PIN
run_regular_case \
    "03_async0_c24_test_all" \
    24 \
    test_all
#======== 04 case_4
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "04_async1_at1_c1_wait_all" \
    24 \
    wait_all
#======== 05 case_5
export OMP_NUM_THREADS=12
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=12
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "05_async1_at12_c12_wait_all" \
    24 \
    wait_all
#======== 06 case_6
export OMP_NUM_THREADS=23
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "06_async1_at1_c23_wait_all" \
    24 \
    wait_all
#======== 07 case_7
export OMP_NUM_THREADS=1
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "07_async1_at1_c1_test_all" \
    24 \
    test_all
#======== 08 case_8
export OMP_NUM_THREADS=12
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=12
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "08_async1_at12_c12_test_all" \
    24 \
    test_all
#======== 09 case_9
export OMP_NUM_THREADS=23
export I_MPI_ASYNC_PROGRESS=1
export I_MPI_ASYNC_PROGRESS_THREADS=1
unset I_MPI_ASYNC_PROGRESS_PIN
run_async_case \
    "09_async1_at1_c23_test_all" \
    24 \
    test_all

echo "All cases done."
