"""SLURM script generator.

Renders Jinja2 templates into SLURM job scripts and writes them into the
output directory tree.  Also generates a top-level submit_all.sh that calls
sbatch on every generated script.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Maps mpi family name → template filename
TEMPLATE_MAP: Dict[str, str] = {
    "intelmpi":     "comb_intelmpi.slurm.j2",
    "intelmpi_tcp": "comb_intelmpi_tcp.slurm.j2",
    "intel":        "comb_intelmpi.slurm.j2",
    "openmpi":      "comb_openmpi.slurm.j2",
    "mpich":        "comb_mpich.slurm.j2",
    "exampi":       "comb_mpich.slurm.j2",   # ExaMPI uses MPICH-style vars
}


def _jinja_env(templates_dir: Path = TEMPLATES_DIR) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # Allow dict.get() inside templates
    env.globals["dict"] = dict
    return env


def _run_id(job_spec: dict) -> str:
    """Deterministic short ID based on job parameters."""
    key = json.dumps(
        {k: job_spec[k] for k in ("job_name", "output_dir")},
        sort_keys=True,
    )
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def generate_job(
    job_spec: dict,
    templates_dir: Path = TEMPLATES_DIR,
    dry_run: bool = False,
    include_slurm_directives: bool = True,
) -> Path:
    """Render one SLURM script and write it to disk.

    Returns the path to the generated script.
    """
    mpi_name: str = job_spec["mpi"]["name"].lower()
    binary = Path(job_spec["mpi"]["binary"])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"COMB binary is missing or not executable: {binary}")

    template_file = TEMPLATE_MAP.get(mpi_name)
    if template_file is None:
        raise ValueError(
            f"No template for MPI implementation '{mpi_name}'. "
            f"Available: {list(TEMPLATE_MAP.keys())}"
        )

    env = _jinja_env(templates_dir)
    template = env.get_template(template_file)

    # Provide compute_mode.get() in templates via a small helper wrapper
    class AttrDict(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    ctx = dict(job_spec)
    ctx["compute_mode"] = AttrDict(job_spec.get("compute_mode", {}))

    rendered = template.render(**ctx)
    if not include_slurm_directives:
        rendered_lines = rendered.splitlines()
        payload_lines = [
            rendered_lines[0],
            "# Payload script: runs as a job step inside a topology-level bundle.",
            f"# BUNDLE_JOB_NAME={job_spec['job_name']}",
        ]
        payload_lines.extend(
            line for line in rendered_lines[1:] if not line.startswith("#SBATCH")
        )
        rendered = "\n".join(payload_lines) + "\n"

    out_dir = Path(job_spec["output_dir"])
    script_path = out_dir / "run.sh"

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(rendered)
        script_path.chmod(0o755)

    return script_path


def generate_all(
    jobs: List[dict],
    templates_dir: Path = TEMPLATES_DIR,
    dry_run: bool = False,
) -> List[Path]:
    """Generate scripts for all jobs; also write submit_all.sh per MPI group."""
    generated: List[Path] = []
    mpi_groups: Dict[str, List[Path]] = {}

    for job in jobs:
        path = generate_job(job, templates_dir=templates_dir, dry_run=dry_run)
        generated.append(path)
        mpi_name = job["mpi"]["name"]
        mpi_groups.setdefault(mpi_name, []).append(path)

    if not dry_run:
        write_submit_all(generated)

    return generated


def generate_bundle(
    jobs: List[dict],
    scripts: List[Path],
    dry_run: bool = False,
) -> Path:
    """Write one topology-level Slurm bundle for a single MPI/resource shape."""
    if not jobs or len(jobs) != len(scripts):
        raise ValueError("Bundle jobs and scripts must be non-empty and have equal length")

    mpi_names = {job["mpi"]["name"] for job in jobs}
    topology_names = {job["topology"]["name"] for job in jobs}
    resources = {
        (
            int(job["topology"]["nodes"]),
            int(job["topology"]["ntasks_per_node"]),
            int(job["slurm"]["cpus_per_task"]),
            str(job["slurm"].get("clusters", "cm4")),
            str(job["slurm"].get("partition", "cm4_std")),
            str(job["slurm"].get("qos", "cm4_std")),
        )
        for job in jobs
    }
    if len(mpi_names) != 1 or len(topology_names) != 1 or len(resources) != 1:
        raise ValueError("A bundle must contain one MPI, one topology, and one resource shape")

    mpi_name = next(iter(mpi_names))
    topology_name = next(iter(topology_names))
    nodes, ntasks_per_node, cpus_per_task, clusters, partition, qos = next(iter(resources))
    topology_dir = Path(jobs[0]["output_dir"]).parents[2]
    bundle_path = topology_dir / "run.sh"
    bundle_time = str(jobs[0]["slurm"].get("bundle_time", "08:00:00"))
    relative_scripts = [os.path.relpath(script, topology_dir) for script in scripts]

    grids = []
    compute_modes = []
    run_dirs = []
    for job in jobs:
        grid = job["grid"]
        grid_name = str(grid["name"])
        mpi_targets = job["mpi"].get("compute_target_us", {})
        topology_targets = job["topology"].get("compute_target_us", {})
        compute_target = mpi_targets.get(job["topology"]["name"], {}).get(
            grid_name,
            topology_targets.get(grid_name, grid.get("compute_target_us", 0)),
        )
        target_source = str(grid.get("target_source", "configured target"))
        grid_summary = (
            f"{grid_name}(size={grid.get('size', '')},ghost={grid.get('ghost', '')},"
            f"vars={grid.get('vars', '')},cycles={grid.get('cycles', 'default')},"
            f"target_us={compute_target},{target_source})"
        )
        if grid_summary not in grids:
            grids.append(grid_summary)
        compute_name = str(job.get("compute_mode", {}).get("name", "default"))
        if compute_name not in compute_modes:
            compute_modes.append(compute_name)
        run_dir = Path(job["output_dir"]).name
        if run_dir not in run_dirs:
            run_dirs.append(run_dir)

    protocol_env = jobs[0]["mpi"].get("protocol_env", {})
    protocol_summary = ", ".join(f"{key}={value}" for key, value in protocol_env.items()) or "module defaults"
    case_counts = sorted({len(job.get("cases", [])) for job in jobs})
    cases_summary = "/".join(str(count) for count in case_counts)

    lines = [
        "#!/bin/bash",
        f"#SBATCH -J comb_bundle_{mpi_name}_{topology_name}",
        f"#SBATCH -D {topology_dir.resolve()}",
        "#SBATCH -o ./bundle.%j.txt",
        "#SBATCH --get-user-env",
        "#SBATCH --export=NONE",
        f"#SBATCH --clusters={clusters}",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --qos={qos}",
        f"#SBATCH --nodes={nodes}",
        f"#SBATCH --ntasks-per-node={ntasks_per_node}",
        f"#SBATCH --cpus-per-task={cpus_per_task}",
        f"#SBATCH --time={bundle_time}",
        "",
        "# Bundle parameter summary:",
        f"# MPI: {mpi_name}; protocol: {protocol_summary}",
        f"# Topology: {topology_name}; nodes={nodes}; ranks/node={ntasks_per_node}; CPUs/rank={cpus_per_task}",
        f"# Payloads: {'; '.join(grids)}",
        f"# Compute modes: {', '.join(compute_modes)}; repetitions: {', '.join(run_dirs)}",
        f"# Child scripts: {len(scripts)} total, {cases_summary} cases per child, executed serially in listed order.",
        "# Results stay in each child's payload/compute/run_### directory; bundle_status.tsv records PASS/FAIL.",
        "",
        "set -uo pipefail",
        "",
        'if [[ -n "${SLURM_JOB_ID:-}" ]]; then',
        '    SCRIPT_DIR="${PWD}"',
        "else",
        '    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)',
        "fi",
        'STATUS_FILE="${SCRIPT_DIR}/bundle_status.tsv"',
        "CHILD_SCRIPTS=(",
    ]
    lines.extend(f'    "{relative}"' for relative in relative_scripts)
    lines += [
        ")",
        "",
        "printf 'timestamp_utc\\tchild\\tstatus\\texit_code\\n' > \"${STATUS_FILE}\"",
        "failures=0",
        "for relative in \"${CHILD_SCRIPTS[@]}\"; do",
        '    child="${SCRIPT_DIR}/${relative}"',
        '    if [[ ! -f "${child}" ]]; then',
        '        printf \'%s\\t%s\\tMISSING\\t%s\\n\' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${relative}" 2 >> "${STATUS_FILE}"',
        "        failures=$((failures + 1))",
        "        continue",
        "    fi",
        '    echo "===== START ${relative} $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="',
        '    child_job_name=$(sed -n -e \'s/^# BUNDLE_JOB_NAME=//p\' -e \'s/^#SBATCH -J //p\' "${child}" | head -n 1)',
        '    child_stdout="$(dirname "${child}")/${child_job_name}.${SLURM_JOB_ID:-manual}.$(hostname -s).out"',
        '    if (cd "$(dirname "${child}")" && bash "$(basename "${child}")") > "${child_stdout}" 2>&1; then',
        "        rc=0; status=PASS",
        "    else",
        "        rc=$?; status=FAIL; failures=$((failures + 1))",
        "    fi",
        '    printf \'%s\\t%s\\t%s\\t%s\\n\' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${relative}" "${status}" "${rc}" >> "${STATUS_FILE}"',
        '    echo "===== END ${relative} status=${status} rc=${rc} output=${child_stdout} ====="',
        "done",
        "",
        'echo "Bundle complete: total=${#CHILD_SCRIPTS[@]} failures=${failures} status_file=${STATUS_FILE}"',
        "(( failures == 0 ))",
    ]

    if not dry_run:
        topology_dir.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("\n".join(lines) + "\n")
        bundle_path.chmod(0o755)
    return bundle_path


def write_submit_all(scripts: List[Path]) -> Path | None:
    """Write one submit manifest covering every supplied script."""
    if not scripts:
        return None
    common = Path(os.path.commonpath([str(path.parent) for path in scripts]))
    return _write_submit_all(common, scripts)


def _write_submit_all(base_dir: Path, scripts: List[Path]) -> Path:
    lines = [
        "#!/bin/bash",
        "# Auto-generated by mpi_lab generator – submit all jobs",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)",
        "submitted=0",
        "",
    ]
    for script in scripts:
        rel = os.path.relpath(script, base_dir)
        lines += [
            f'job_dir=$(dirname "${{SCRIPT_DIR}}/{rel}")',
            f'echo "Submitting {rel}"',
            f'output=$(cd "$job_dir" && sbatch "$(basename "{script}")")',
            f'echo "  $output"',
            "submitted=$((submitted + 1))",
            "",
        ]
    lines += [
        'echo "Submitted ${submitted} jobs."',
    ]
    submit_path = base_dir / "submit_all.sh"
    submit_path.write_text("\n".join(lines) + "\n")
    submit_path.chmod(0o755)
    return submit_path
