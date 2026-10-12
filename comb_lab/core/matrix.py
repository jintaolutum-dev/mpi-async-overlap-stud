"""Parameter matrix expansion.

Reads the YAML experiment config and expands the outer product of
(mpi_impl × topology × grid × compute_mode), yielding one job spec per
combination. Each job spec also carries the list of inner cases
(async × omp_threads × wait_mode) that run inside a single SLURM script.
"""
from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any, Dict, Iterator, List

import yaml


def _load_yaml(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _matches_exclude(combo: dict, rule: dict) -> bool:
    return all(str(combo.get(k)) == str(v) for k, v in rule.items())


def _message_size_dirname(grid: dict, topology: dict) -> str:
    """Return a filesystem-safe X/Y/Z halo payload label for a job."""
    try:
        size = tuple(int(value) for value in str(grid["size"]).split("_"))
        divide = tuple(int(value) for value in str(topology["divide"]).split("_"))
        ghost = tuple(int(value) for value in str(grid["ghost"]).split("_"))
        variables = int(grid["vars"])
        if len(size) != 3 or len(divide) != 3 or len(ghost) != 3:
            raise ValueError
    except (KeyError, ValueError):
        return str(grid.get("name", "unknown"))

    local = tuple(global_size // parts for global_size, parts in zip(size, divide))
    face_bytes = (
        local[1] * local[2] * ghost[0] * 8 * variables,
        local[0] * local[2] * ghost[1] * 8 * variables,
        local[0] * local[1] * ghost[2] * 8 * variables,
    )

    def format_bytes(value: int) -> str:
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.2f}MiB"
        if value >= 1024:
            return f"{value // 1024}KiB"
        return f"{value}B"

    return "msg_" + "_".join(
        f"{axis}{format_bytes(value)}" for axis, value in zip("xyz", face_bytes)
    )


def expand_matrix(config: dict) -> List[Dict[str, Any]]:
    """Return list of job specs from the outer matrix axes."""
    matrix = config.get("matrix", {})

    # Outer axes: each axis is a list of named entries
    axes: Dict[str, list] = {}

    for mpi_name, mpi_cfg in config.get("mpi_impl", {}).items():
        axes.setdefault("mpi_impl", []).append({"name": mpi_name, **mpi_cfg})

    for topo in config.get("topology", []):
        axes.setdefault("topology", []).append(topo)

    grids_by_topology = config.get("grid_by_topology", {})
    if grids_by_topology:
        for topology_name, topology_grids in grids_by_topology.items():
            for grid_name, grid_cfg in topology_grids.items():
                axes.setdefault("grid", []).append(
                    {"name": grid_name, "topology_name": topology_name, **grid_cfg}
                )
    else:
        for grid_name, grid_cfg in config.get("grid", {}).items():
            axes.setdefault("grid", []).append({"name": grid_name, **grid_cfg})

    for compute_name, compute_cfg in config.get("compute_mode", {}).items():
        compute_entry = {"name": compute_name, **compute_cfg}
        backend_mode = compute_entry.get("backend_mode")
        if backend_mode is None:
            backend_mode = "both" if compute_entry.get("enable_mock", True) else "mpi_only"
        if backend_mode not in {"both", "mpi_only", "mock_only"}:
            raise ValueError(
                f"Compute mode '{compute_name}' has invalid backend_mode "
                f"'{backend_mode}'; expected both, mpi_only, or mock_only"
            )
        compute_entry["backend_mode"] = backend_mode
        axes.setdefault("compute_mode", []).append(compute_entry)

    exclude_rules = config.get("exclude", [])
    slurm_cfg = config.get("slurm", {})
    cases = config.get("cases", [])
    exp_name = config.get("name", "experiment")
    output_base = Path(config.get("output_base", "generated"))
    comm_cfg = config.get("comm", {})

    jobs: List[Dict[str, Any]] = []
    axis_lists = list(axes.values())
    axis_keys = list(axes.keys())

    for combo_values in itertools.product(*axis_lists):
        combo = dict(zip(axis_keys, combo_values))

        # Apply exclude rules
        flat = {k: v.get("name", v) if isinstance(v, dict) else v
                for k, v in combo.items()}
        if any(_matches_exclude(flat, rule) for rule in exclude_rules):
            continue

        mpi = combo.get("mpi_impl", {})
        topo = combo.get("topology", {})
        grid = combo.get("grid", {})
        compute = combo.get("compute_mode", {})
        job_slurm = copy.deepcopy(slurm_cfg)

        job_mpi = copy.deepcopy(mpi)
        job_cases = job_mpi.get("cases", cases)

        mpi_name = mpi.get("name", "unknown")
        topo_name = topo.get("name", "unknown")
        grid_name = grid.get("name", "unknown")
        if grid.get("topology_name") not in (None, topo_name):
            continue
        message_size_name = _message_size_dirname(grid, topo)
        compute_name = compute.get("name", "")
        total_tasks = int(topo.get("nodes", 0)) * int(topo.get("ntasks_per_node", 0))

        total_cpus_per_job = job_slurm.get("total_cpus_per_job")
        if total_cpus_per_job is not None:
            total_cpus_per_job = int(total_cpus_per_job)
            if total_tasks <= 0:
                raise ValueError(
                    f"Topology '{topo_name}' must define a positive total task count"
                )
            if total_cpus_per_job % total_tasks != 0:
                raise ValueError(
                    f"slurm.total_cpus_per_job={total_cpus_per_job} is not divisible by "
                    f"total tasks {total_tasks} for topology '{topo_name}'"
                )
            job_slurm["cpus_per_task"] = total_cpus_per_job // total_tasks
        else:
            job_slurm.setdefault("cpus_per_task", topo.get("cpus_per_task"))

        binary_overrides = compute.get("binary_overrides", {})
        if isinstance(binary_overrides, dict):
            override_binary = binary_overrides.get(mpi_name)
            if override_binary:
                job_mpi["binary"] = override_binary

        parts = [exp_name, mpi_name, topo_name, message_size_name]
        if compute_name:
            parts.append(compute_name)
        job_name = "_".join(parts)

        out_dir = output_base / mpi_name / topo_name / message_size_name
        if compute_name:
            out_dir = out_dir / compute_name

        jobs.append(
            {
                "job_name": job_name,
                "output_dir": str(out_dir),
                "mpi": job_mpi,
                "topology": topo,
                "grid": grid,
                "compute_mode": compute,
                "slurm": job_slurm,
                "cases": job_cases,
                "experiment_name": exp_name,
                    "comm": comm_cfg,
            }
        )

    return jobs


def load_config(path: str | Path) -> dict:
    cfg = _load_yaml(path)
    # Resolve output_base relative to config file
    cfg_dir = Path(path).parent
    if not Path(cfg.get("output_base", "generated")).is_absolute():
        cfg["output_base"] = str(cfg_dir.parent / "generated")
    return cfg
