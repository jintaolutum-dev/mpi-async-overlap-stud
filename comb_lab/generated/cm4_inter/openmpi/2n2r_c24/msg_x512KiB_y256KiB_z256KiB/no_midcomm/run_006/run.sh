#!/bin/bash
#SBATCH -J comb_async_scan_openmpi_2n2r_c24_msg_x512KiB_y256KiB_z256KiB_no_midcomm
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

module load slurm_setup
module unload openmpi/4.1.8-gcc13
module load stack/24.4.0
module load openmpi/4.1.8-intel24
export OMPI_MCA_pml="ob1"
export OMPI_MCA_btl="self,vader,tcp"
export OMPI_MCA_btl_base_verbose="100"
export OMPI_MCA_bml_base_verbose="100"

ln -sf /dss/dsshome1/02/ge63neh3/comb_with_compute/build_2_openmpi_dummy_OMP/bin/comb ./comb

NTASKS=2
NTASKS_PER_NODE=1
GRID_SIZE="32_32_32"
DIVIDE="2_1_1"
PERIODIC="1_1_1"
GHOST="1_1_1"
VARS=64
COMM_CUTOFF=250

COMPUTE_ARGS="-compute_target_us 0"
CYCLE_ARGS="-cycles 50"

CPU_TOPOLOGY_MAP="$(lscpu -p=CPU,SOCKET,NODE 2>/dev/null | grep -v '^#' || true)"
export CPU_TOPOLOGY_MAP

OPENMPI_HOSTFILE="$(mktemp -p "${PWD}" openmpi_hosts.XXXXXX)"
trap 'rm -f "${OPENMPI_HOSTFILE}"' EXIT
scontrol show hostnames "${SLURM_JOB_NODELIST}" | while read -r host; do
    [[ -n "${host}" ]] || continue
    printf '%s slots=%s\n' "${host}" "${NTASKS_PER_NODE}" >> "${OPENMPI_HOSTFILE}"
done
export OPENMPI_HOSTFILE

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
        echo "job_name=comb_async_scan_openmpi_2n2r_c24_msg_x512KiB_y256KiB_z256KiB_no_midcomm"
        echo "experiment_name=comb_async_scan"
        echo "mpi_family=openmpi"
        echo "topology=2n2r_c24"
        echo "grid=custom"
        echo "compute_mode=no_midcomm"
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
        echo "comm_cutoff=${COMM_CUTOFF:-}"
        echo "compute_args=${COMPUTE_ARGS}"
        echo "slurm_job_id=${SLURM_JOB_ID:-}"
        echo "slurm_job_nodelist=${SLURM_JOB_NODELIST:-}"
        echo "openmpi_hostfile=${OPENMPI_HOSTFILE}"
        echo "comb_binary_realpath=${binary_realpath}"
        echo "comm_mode_hint=${comm_mode_hint}"
        echo
        echo ">>> module_list"
        module -t list 2>&1 || true
        echo
    } >> "${JOB_METADATA_FILE}"

    dump_env_matches "selected_env" '^(OMPI_MCA_|PMIX_MCA_|UCX_|FI_|OMP_|GOMP_CPU_AFFINITY=|SLURM_(JOB_ID|JOB_NODELIST|CPUS_PER_TASK|NTASKS|NTASKS_PER_NODE|CPUS_ON_NODE)=)'

    if command -v mpirun >/dev/null 2>&1; then
        {
            echo ">>> mpirun_version"
            mpirun --version 2>&1 | sed -n '1,20p' || true
            echo
        } >> "${JOB_METADATA_FILE}"
    fi

    if command -v ompi_info >/dev/null 2>&1; then
        {
            echo ">>> ompi_info_version"
            ompi_info --version 2>&1 || true
            echo
            echo ">>> ompi_info_transport_summary"
            ompi_info --parsable --all 2>/dev/null | grep -E 'mca:(pml|btl|mtl|oob|osc):' | sed -n '1,120p' || true
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

    if command -v fi_info >/dev/null 2>&1; then
        {
            echo ">>> fi_info_provider_list"
            fi_info -l 2>&1 | sed -n '1,80p' || true
            echo
        } >> "${JOB_METADATA_FILE}"
    fi

    {
        echo "===== end job_metadata ====="
        echo
    } >> "${JOB_METADATA_FILE}"
}

write_job_metadata

run_case() {
    local label="$1"; shift
    : > "${label}.log"
    echo "===== ${label} =====" | tee -a "${label}.log"
    [[ -n "${CASE_LAUNCHER:-}"     ]] && echo "launcher=${CASE_LAUNCHER}"     | tee -a "${label}.log"
    [[ -n "${CASE_COMB_CMD:-}"     ]] && echo "comb_cmd=${CASE_COMB_CMD}"     | tee -a "${label}.log"
    [[ -n "${CASE_BINDING_MODE:-}" ]] && echo "binding_mode=${CASE_BINDING_MODE}" | tee -a "${label}.log"
    [[ -n "${JOB_METADATA_FILE:-}" ]] && echo "job_metadata_file=${JOB_METADATA_FILE}" | tee -a "${label}.log"
    "$@" 2>&1 | tee -a "${label}.log"
    local rc=${PIPESTATUS[0]}
    echo "===== ${label} exit code: ${rc} =====" | tee -a "${label}.log"
    return ${rc}
}

dump_rank_runtime_state() {
    local rank_id="${OMPI_COMM_WORLD_RANK:-unknown}"
    local process_status
    local affinity
    local thread_count

    process_status="$(grep -E '^(Cpus_allowed_list|Mems_allowed_list):' /proc/self/status | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    affinity="$(taskset -pc $$ 2>&1 | tr '\n' ' ')"
    thread_count="$(ps -o nlwp= -p $$ 2>/dev/null | tr -d '[:space:]')"
    echo "runtime_state rank=${rank_id} host=$(hostname) pid=$$ threads=${thread_count:-unknown} ${process_status} taskset=${affinity}"
}

export -f dump_rank_runtime_state

_comb_args() {
    local wait_mode="$1"
    echo "${GRID_SIZE} \
-divide ${DIVIDE} -periodic ${PERIODIC} -ghost ${GHOST} \
-vars ${VARS} \
-comm cutoff ${COMM_CUTOFF} \
-comm disable all \
-comm enable mpi \
-comm enable mock \
-comm post_recv wait_all \
-comm post_send wait_all \
-comm wait_recv ${wait_mode} -comm wait_send ${wait_mode} \
-exec enable omp ${COMPUTE_ARGS} ${CYCLE_ARGS} \
-print_message_sizes -print_packing_sizes"
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

    CASE_LAUNCHER="mpirun --mca plm slurm --hostfile ${OPENMPI_HOSTFILE} -np ${NTASKS} --map-by ppr:${NTASKS_PER_NODE}:node:PE=${cpus_per_task} --bind-to core --report-bindings"
    CASE_COMB_CMD="./comb $(_comb_args_flat ${wait_mode})"
    CASE_BINDING_MODE="${binding_mode}"
}

run_regular_case() {
    local label="$1" cpus_per_task="$2" wait_mode="$3"

    set_case_metadata "${cpus_per_task}" cores "${wait_mode}" "mpirun --bind-to core"

    run_case "${label}" \
        mpirun --mca plm slurm --hostfile "${OPENMPI_HOSTFILE}" -np ${NTASKS} --map-by ppr:${NTASKS_PER_NODE}:node:PE=${cpus_per_task} --bind-to core --report-bindings \
        bash -lc "
            rank_id=\${OMPI_COMM_WORLD_RANK:-unknown}
            export OMP_PROC_BIND=close
            export OMP_PLACES=cores
            allowed=\$(awk '/Cpus_allowed_list/ {print \$2}' /proc/self/status)
            main_topology=\$(cpu_list_topology_sets "\${allowed}")
            IFS='|' read -r main_socket_set main_numa_set <<< "\${main_topology}"
            echo \"rank=\${rank_id} host=\$(hostname) bind_mode=mpirun allowed=\${allowed} main_cpu_list=\${allowed} progress_cpu_list= main_socket_set=\${main_socket_set} progress_socket_set=none main_numa_set=\${main_numa_set} progress_numa_set=none binding_relation=no_progress_threads\"
            dump_rank_runtime_state
            exec ./comb $(_comb_args_flat ${wait_mode})
        "
}

# OpenMPI async via MCA parameters
run_async_case() {
    local label="$1" cpus_per_task="$2" wait_mode="$3" async_threads="$4"

    if (( async_threads < 1 )); then
        echo "run_async_case requires at least 1 reserved async CPU per rank" >&2
        return 1
    fi

    set_case_metadata "${cpus_per_task}" cores "${wait_mode}" "omp places + reserved async CPUs"

    run_case "${label}" \
        mpirun --mca plm slurm --hostfile "${OPENMPI_HOSTFILE}" -np ${NTASKS} --map-by ppr:${NTASKS_PER_NODE}:node:PE=${cpus_per_task} --bind-to core --report-bindings \
        bash -lc "
            rank_id=\${OMPI_COMM_WORLD_RANK:-unknown}
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
            total_cpus_per_task=${cpus_per_task}
            omp_threads=\${OMP_NUM_THREADS:-1}
            if (( async_threads >= total_cpus_per_task )); then
                echo \"rank=\${rank_id} host=\$(hostname) invalid async_threads=\${async_threads} for total_cpus_per_task=\${total_cpus_per_task}\" >&2
                exit 1
            fi
            main_cpus_per_task=\$((total_cpus_per_task - async_threads))
            if (( omp_threads > main_cpus_per_task )); then
                echo \"rank=\${rank_id} host=\$(hostname) OMP_NUM_THREADS=\${omp_threads} exceeds main_cpus_per_rank=\${main_cpus_per_task}\" >&2
                exit 1
            fi
            if [[ \${#cpu_array[@]} -lt \${total_cpus_per_task} ]]; then
                echo \"rank=\${rank_id} host=\$(hostname) insufficient allowed CPUs: allowed=\${allowed}\" >&2
                exit 1
            fi

            main_end=\$((main_cpus_per_task - 1))
            async_start=\${main_cpus_per_task}
            async_end=\$((total_cpus_per_task - 1))

            cpu_list=\"\${cpu_array[0]}\"
            omp_places=\"{\${cpu_array[0]}}\"
            for ((idx=1; idx<=main_end; ++idx)); do
                cpu_list+=\",\${cpu_array[\${idx}]}\"
                omp_places+=\",{\${cpu_array[\${idx}]}}\"
            done

            reserved_async_cpu_list=\"\${cpu_array[\${async_start}]}\"
            for ((idx=async_start+1; idx<=async_end; ++idx)); do
                reserved_async_cpu_list+=\",\${cpu_array[\${idx}]}\"
            done

            export OMP_PROC_BIND=close
            export OMP_PLACES=\"\${omp_places}\"
            unset GOMP_CPU_AFFINITY

            main_topology=\$(cpu_list_topology_sets "\${cpu_list}")
            IFS='|' read -r main_socket_set main_numa_set <<< "\${main_topology}"
            progress_topology=\$(cpu_list_topology_sets "\${reserved_async_cpu_list}")
            IFS='|' read -r progress_socket_set progress_numa_set <<< "\${progress_topology}"
            binding_relation=\$(classify_binding_relation "\${cpu_list}" "\${reserved_async_cpu_list}" "\${main_socket_set}" "\${progress_socket_set}" "\${main_numa_set}" "\${progress_numa_set}")

            echo \"rank=\${rank_id} host=\$(hostname) bind_mode=omp_places allowed=\${allowed} total_cpus_per_rank=\${total_cpus_per_task} omp_threads=\${omp_threads} async_threads=\${async_threads} main_cpus_per_rank=\${main_cpus_per_task} main_cpu_list=\${cpu_list} progress_cpu_list=\${reserved_async_cpu_list} reserved_async_cpu_list=\${reserved_async_cpu_list} main_socket_set=\${main_socket_set} progress_socket_set=\${progress_socket_set} main_numa_set=\${main_numa_set} progress_numa_set=\${progress_numa_set} binding_relation=\${binding_relation}\"
            echo \"rank=\${rank_id} host=\$(hostname)\"
            dump_rank_runtime_state
            exec ./comb $(_comb_args_flat ${wait_mode})
        "
}

#======== 00 
export OMP_NUM_THREADS=1
unset OMPI_MCA_mpi_yield_when_idle
unset OMPI_MCA_btl_tcp_progress_thread
run_regular_case \
    "00_async0_c1_wait_all" \
    24 \
    wait_all
#======== 01 
export OMP_NUM_THREADS=24
unset OMPI_MCA_mpi_yield_when_idle
unset OMPI_MCA_btl_tcp_progress_thread
run_regular_case \
    "01_async0_c24_wait_all" \
    24 \
    wait_all
#======== 02 
export OMP_NUM_THREADS=1
unset OMPI_MCA_mpi_yield_when_idle
unset OMPI_MCA_btl_tcp_progress_thread
run_regular_case \
    "02_async0_c1_test_all" \
    24 \
    test_all
#======== 03 
export OMP_NUM_THREADS=24
unset OMPI_MCA_mpi_yield_when_idle
unset OMPI_MCA_btl_tcp_progress_thread
run_regular_case \
    "03_async0_c24_test_all" \
    24 \
    test_all
#======== 04 
export OMP_NUM_THREADS=1
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "04_async1_at1_c1_wait_all" \
    24 \
    wait_all \
    1
#======== 05 
export OMP_NUM_THREADS=12
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "05_async1_at12_c12_wait_all" \
    24 \
    wait_all \
    12
#======== 06 
export OMP_NUM_THREADS=23
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "06_async1_at1_c23_wait_all" \
    24 \
    wait_all \
    1
#======== 07 
export OMP_NUM_THREADS=1
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "07_async1_at1_c1_test_all" \
    24 \
    test_all \
    1
#======== 08 
export OMP_NUM_THREADS=12
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "08_async1_at12_c12_test_all" \
    24 \
    test_all \
    12
#======== 09 
export OMP_NUM_THREADS=23
export OMPI_MCA_mpi_yield_when_idle=0
export OMPI_MCA_btl_tcp_progress_thread=1
export OMPI_MCA_opal_progress_sched_yield=0
export OMPI_MCA_mpi_add_procs_cutoff=0
run_async_case \
    "09_async1_at1_c23_test_all" \
    24 \
    test_all \
    1

echo "All cases done."
