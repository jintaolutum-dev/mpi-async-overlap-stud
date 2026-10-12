#!/usr/bin/env python3
"""Calculate paired MPI overlap metrics and render an eight-panel bar chart.

Example:
  ./venv/bin/python analyze_overlap.py \
        --midcomm-dir generated/cm4_inter/intelmpi/1n2r_c24/small_msg/midcomm/run_001 \
        --no-midcomm-dir generated/cm4_inter/intelmpi/1n2r_c24/small_msg/no_midcomm/run_001 \
      --output-dir generated/cm4_inter/intelmpi/1n2r_c24/small_msg/analysis
"""
from __future__ import annotations

import argparse
import csv
import re
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


COMM_HEADER = re.compile(
    r"^Starting test Comm (mpi|mock) Mesh (\w+) Host Buffers (\w+) Host (\w+) Host$"
)
METRIC_ROW = re.compile(
    r"^\s*([^,]+),\s*(\d+),\s*([0-9.eE+-]+),\s*([0-9.eE+-]+),\s*([0-9.eE+-]+)\s*$"
)
CASE_FILE = re.compile(r"^Comb_(\d+)_summary\.csv$")
COMPUTE_TARGET = re.compile(r"-compute_target_us;([0-9.eE+-]+)")
RUN_DIR = re.compile(r"^run_\d+(?:_(?:MPIonly|Mockonly))?$")
SEND_PAYLOAD = re.compile(r"^send:\s+\d+\s+partner\s+(\d+)\s+tag\s+\d+\s+items\s+(\d+)\s+bytes$")
NUM_CYCLES = re.compile(r"^Num cycles\s+(\d+)\s*$", re.MULTILINE)
PAYLOAD_NOTE_BEGIN = "# actual-mpi-send-payloads: begin"
PAYLOAD_NOTE_END = "# actual-mpi-send-payloads: end"

POLICIES = [
    ("seq", "seq", "seq"),
    ("omp", "seq", "seq"),
    ("omp", "omp", "seq"),
    ("omp", "omp", "omp"),
]


def policy_label(policy: tuple[str, str, str]) -> str:
    mesh, large_buffer, small_buffer = policy
    return f"Mesh {mesh} | Buffers {large_buffer}/{small_buffer}"


def parse_summary(path: Path) -> dict[tuple[str, str, str, str], dict[str, dict[str, float]]]:
    """Return MPI and mock timing blocks indexed by backend and buffer policies."""
    blocks: dict[tuple[str, str, str, str], dict[str, dict[str, float]]] = {}
    current_policy: tuple[str, str, str, str] | None = None

    for line in path.read_text(errors="replace").splitlines():
        header = COMM_HEADER.match(line)
        if header:
            current_policy = header.groups()
            blocks[current_policy] = {}
            continue

        if current_policy is None:
            continue

        metric = METRIC_ROW.match(line)
        if not metric:
            continue

        name, count, average, minimum, maximum = metric.groups()
        blocks[current_policy][name.strip()] = {
            "num": int(count),
            "average": float(average),
            "min": float(minimum),
            "max": float(maximum),
        }

    return blocks


def summary_files(directory: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in directory.glob("Comb_*_summary.csv"):
        match = CASE_FILE.match(path.name)
        if match:
            files[match.group(1)] = path
    return files


def compute_target_us(path: Path) -> float | None:
    """Read the configured per-call dummy-compute target from Comb arguments."""
    match = COMPUTE_TARGET.search(path.read_text(errors="replace"))
    return float(match.group(1)) if match else None


def run_cycles(directory: Path) -> int | None:
    """Read the configured cycle count from one generated Comb summary."""
    summaries = sorted(directory.glob("Comb_*_summary.csv"))
    if not summaries:
        return None
    match = NUM_CYCLES.search(summaries[0].read_text(errors="replace"))
    return int(match.group(1)) if match else None


def rank_count(directory: Path) -> int:
    """Return the rank count recorded by the generated job, if available."""
    try:
        return max(1, int(read_job_metadata(directory).get("ntasks", "1")))
    except ValueError:
        return 1


def total_midcomm_time(metric: dict[str, float], ranks: int) -> float:
    """Estimate injected compute time on the benchmark's critical-path rank."""
    # `mid-comm` averages all rank/cycle samples (ranks x configured cycles),
    # while `bench-comm` is one total duration per rank across all cycles.
    # Red bar serial baseline:
    #   bench_no_max + (mid_comm_num / ranks) * mid_comm_avg.
    # Convert the aggregate sample count to the cycle count on one rank.
    return float(metric["average"]) * float(metric["num"]) / ranks


def format_time_pair(no_midcomm: float, midcomm: float) -> str:
    """Format paired no-midcomm/midcomm times compactly for x-axis labels."""
    if max(abs(no_midcomm), abs(midcomm)) < 1:
        return f"{no_midcomm * 1_000:.1f}/{midcomm * 1_000:.1f} ms"
    return f"{no_midcomm:.3f}/{midcomm:.3f} s"


def format_time_difference(seconds: float) -> str:
    """Format a red-bar serial-baseline time saving or added cost."""
    direction = "saved" if seconds >= 0 else "cost"
    magnitude = abs(seconds)
    if magnitude < 1e-3:
        return f"{direction} {magnitude * 1_000_000:.1f} us"
    return f"{direction} {magnitude * 1_000:.3f} ms"


def format_blue_overlap_time(seconds: float) -> str:
    """Format the per-call wait-recv time saved by, or added during, compute."""
    direction = "wait saved" if seconds >= 0 else "wait added"
    magnitude = abs(seconds)
    if magnitude < 1e-3:
        return f"{direction} {magnitude * 1_000_000:.1f} us"
    return f"{direction} {magnitude * 1_000:.3f} ms"


def compute_rows(midcomm_dir: Path, no_midcomm_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
    mid_files = summary_files(midcomm_dir)
    no_files = summary_files(no_midcomm_dir)
    ranks = rank_count(midcomm_dir)
    case_ids = sorted(set(mid_files) & set(no_files), key=int)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    missing_mid = sorted(set(no_files) - set(mid_files), key=int)
    missing_no = sorted(set(mid_files) - set(no_files), key=int)
    if missing_mid:
        warnings.append(f"Missing midcomm summaries for cases: {', '.join(missing_mid)}")
    if missing_no:
        warnings.append(f"Missing no_midcomm summaries for cases: {', '.join(missing_no)}")

    for case_id in case_ids:
        mid_blocks = parse_summary(mid_files[case_id])
        no_blocks = parse_summary(no_files[case_id])
        configured_compute_target_us = compute_target_us(mid_files[case_id])
        if configured_compute_target_us is None:
            warnings.append(f"Case {case_id}: missing -compute_target_us argument in midcomm summary")

        for backend in ("mpi", "mock"):
            for policy in POLICIES:
                key = (backend, *policy)
                mid = mid_blocks.get(key)
                baseline = no_blocks.get(key)
                if mid is None or baseline is None:
                    warnings.append(
                        f"Case {case_id}: missing '{policy_label(policy)}' {backend} block in "
                        f"{'midcomm' if mid is None else 'no_midcomm'} summary"
                    )
                    continue

                required = ("pre-comm", "post-send", "wait-recv", "post-comm", "bench-comm")
                absent = [name for name in required if name not in mid or name not in baseline]
                if absent:
                    warnings.append(f"Case {case_id}, {backend} {policy_label(policy)}: missing {', '.join(absent)}")
                    continue
                if "mid-comm" not in mid:
                    warnings.append(f"Case {case_id}, {backend} {policy_label(policy)}: missing mid-comm timer")
                    continue

                exposed_no = baseline["wait-recv"]["average"]
                exposed_mid = mid["wait-recv"]["average"]
                bench_no = baseline["bench-comm"]["max"]
                bench_mid = mid["bench-comm"]["max"]
                mid_compute_total = total_midcomm_time(mid["mid-comm"], ranks)
                serial_total = bench_no + mid_compute_total
                if mid_compute_total <= 0 or serial_total <= 0:
                    warnings.append(f"Case {case_id}, {backend} {policy_label(policy)}: non-positive baseline metric")
                    continue

                rows.append(
                    {
                        "case": f"{int(case_id):02d}",
                        "comm_backend": backend,
                        "mesh_policy": policy[0],
                        "large_buffer_policy": policy[1],
                        "small_buffer_policy": policy[2],
                        "wait_recv_no_mid_avg_s": exposed_no,
                        "wait_recv_mid_avg_s": exposed_mid,
                        "pre_comm_no_mid_avg_s": baseline["pre-comm"]["average"],
                        "pre_comm_mid_avg_s": mid["pre-comm"]["average"],
                        "post_send_no_mid_avg_s": baseline["post-send"]["average"],
                        "post_send_mid_avg_s": mid["post-send"]["average"],
                        "post_comm_no_mid_avg_s": baseline["post-comm"]["average"],
                        "post_comm_mid_avg_s": mid["post-comm"]["average"],
                        # Blue bar: (wait_recv_no_avg - wait_recv_mid_avg)
                        # / mid_comm_avg. All three values are per-call averages
                        # over the same rank/cycle sample set, so do not multiply
                        # either side by the shared sample count.
                        "overlap_rate": (exposed_no - exposed_mid) / mid["mid-comm"]["average"],
                        # Absolute compute time hidden in wait-recv on one
                        # critical-path rank across all of its cycles.
                        "wait_recv_overlap_total_s": (exposed_no - exposed_mid) * mid["mid-comm"]["num"] / ranks,
                        "midcomm_calls_per_rank": mid["mid-comm"]["num"] / ranks,
                        "bench_no_mid_max_s": bench_no,
                        "bench_mid_max_s": bench_mid,
                        "injected_compute_target_us": configured_compute_target_us,
                        "measured_midcomm_per_call_avg_us": mid["mid-comm"]["average"] * 1_000_000,
                        "midcomm_compute_total_avg_s": mid_compute_total,
                        "serial_work_estimate_s": serial_total,
                        # Red bar: (serial_total - bench_mid_max) / serial_total,
                        # where serial_total is the per-rank serial baseline above.
                        "overall_overlap_gain": (serial_total - bench_mid) / serial_total,
                    }
                )

    return rows, warnings


def write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    fields = [
        "case",
        "comm_backend",
        "mesh_policy",
        "large_buffer_policy",
        "small_buffer_policy",
        "wait_recv_no_mid_avg_s",
        "wait_recv_mid_avg_s",
        "pre_comm_no_mid_avg_s",
        "pre_comm_mid_avg_s",
        "post_send_no_mid_avg_s",
        "post_send_mid_avg_s",
        "post_comm_no_mid_avg_s",
        "post_comm_mid_avg_s",
        "overlap_rate",
        "wait_recv_overlap_total_s",
        "midcomm_calls_per_rank",
        "bench_no_mid_max_s",
        "bench_mid_max_s",
        "injected_compute_target_us",
        "measured_midcomm_per_call_avg_us",
        "midcomm_compute_total_avg_s",
        "serial_work_estimate_s",
        "overall_overlap_gain",
    ]
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_configuration_signature(midcomm_dir: Path, no_midcomm_dir: Path) -> tuple[tuple[str, str], ...]:
    """Return the run settings that must match before timing rows are averaged."""
    keys = (
        "mpi_family", "topology", "nodes", "ntasks", "ntasks_per_node",
        "runtime_cpus_per_rank", "grid_size", "divide", "periodic", "ghost",
        "vars", "comm_cutoff", "compute_args", "comm_mode_hint",
    )
    signature: dict[str, str] = {}
    for mode, directory in (("midcomm", midcomm_dir), ("no_midcomm", no_midcomm_dir)):
        metadata = read_job_metadata(directory)
        for key in keys:
            signature[f"{mode}.{key}"] = metadata.get(key, "")
    return tuple(sorted(signature.items()))


def average_rows(run_dirs: list[Path]) -> tuple[list[dict[str, object]], list[str], str, Path]:
    """Average paired runs after rejecting incompatible experiment configurations."""
    if len(run_dirs) < 2:
        raise ValueError("At least two --average-midcomm-dir values are required.")

    reference_signature: tuple[tuple[str, str], ...] | None = None
    all_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    labels: list[str] = []
    reference_no_midcomm: Path | None = None
    for midcomm_dir in run_dirs:
        if midcomm_dir.parent.name != "midcomm" or not RUN_DIR.match(midcomm_dir.name):
            raise ValueError(f"Expected a midcomm/run_### directory: {midcomm_dir}")
        no_midcomm_dir = midcomm_dir.parent.parent / "no_midcomm" / midcomm_dir.name
        if not no_midcomm_dir.is_dir():
            raise ValueError(f"Missing paired no_midcomm run: {no_midcomm_dir}")
        signature = run_configuration_signature(midcomm_dir, no_midcomm_dir)
        if reference_signature is None:
            reference_signature = signature
            reference_no_midcomm = no_midcomm_dir
        elif signature != reference_signature:
            differing = [key for (key, value), (_, reference) in zip(signature, reference_signature) if value != reference]
            raise ValueError(
                f"Incompatible experiment configuration for {midcomm_dir.name}: {', '.join(differing)}"
            )
        rows, run_warnings = compute_rows(midcomm_dir, no_midcomm_dir)
        if not rows:
            raise ValueError(f"No complete timing rows for {midcomm_dir}")
        all_rows.extend(rows)
        warnings.extend(f"{midcomm_dir.name}: {warning}" for warning in run_warnings)
        labels.append(midcomm_dir.name)

    key_fields = ("case", "comm_backend", "mesh_policy", "large_buffer_policy", "small_buffer_policy")
    groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in all_rows:
        groups.setdefault(tuple(row[field] for field in key_fields), []).append(row)
    expected_count = len(run_dirs)
    incomplete = [key for key, values in groups.items() if len(values) != expected_count]
    if incomplete:
        raise ValueError("Runs do not contain the same complete case/backend/policy rows.")

    averaged: list[dict[str, object]] = []
    for key in sorted(groups, key=lambda item: (int(str(item[0])), str(item[1:]))):
        values = groups[key]
        average = dict(values[0])
        for field, value in average.items():
            if isinstance(value, float):
                average[field] = sum(float(row[field]) for row in values) / expected_count
        averaged.append(average)
    assert reference_no_midcomm is not None
    return averaged, warnings, "_".join(labels), reference_no_midcomm


def write_average_note(output_dir: Path, run_dirs: list[Path], run_label: str) -> list[str]:
    """Record the selected source runs in the note colocated with an average chart."""
    average_label = f"average_{run_label}"
    source_runs = [directory.name for directory in run_dirs]
    source_line = f"Average source runs ({len(source_runs)}): {', '.join(source_runs)}"
    cycles_by_run = {directory.name: run_cycles(directory) for directory in run_dirs}
    unique_cycles = {cycles for cycles in cycles_by_run.values() if cycles is not None}
    if len(unique_cycles) == 1 and len(cycles_by_run) == len(run_dirs):
        cycles_line = f"cycles={unique_cycles.pop()}"
    else:
        cycles_line = "cycles=" + ", ".join(
            f"{run}: {cycles if cycles is not None else 'unavailable'}"
            for run, cycles in cycles_by_run.items()
        )
    payloads_by_run = {directory.name: actual_send_payloads(directory) for directory in run_dirs}
    unique_payloads = {repr(payloads) for payloads in payloads_by_run.values() if payloads}
    payload_lines: list[str] = []
    if len(unique_payloads) == 1 and len(payloads_by_run) == len(run_dirs):
        payload_lines.append("Actual MPI_Isend payloads (identical across all source runs):")
        for rank, sends in sorted(next(iter(payloads_by_run.values())).items()):
            details = "; ".join(
                f"partner {partner}: {bytes_sent} B ({bytes_sent / 1024:.2f} KiB)"
                for partner, bytes_sent in sends
            )
            payload_lines.append(f"rank {rank}: {details}")
    else:
        payload_lines.append("Actual MPI_Isend payloads differ or are unavailable across source runs:")
        for source_run, payloads in payloads_by_run.items():
            payload_lines.append(f"{source_run}: {payloads or 'unavailable'}")
    note_path = output_dir / "notes" / average_label / "experiment_notes.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"# Average analysis notes: {average_label}\n"
        f"{source_line}\n"
        f"{cycles_line}\n"
        + "\n".join(payload_lines)
        + "\n"
    )
    return [source_line, cycles_line, *payload_lines]


def describe_case(case_id: str, no_midcomm_dir: Path) -> str:
    """Read the generated case label once, for the chart's shared legend table."""
    log_files = sorted(no_midcomm_dir.glob(f"{case_id}_*.log"))
    if not log_files:
        return "configuration not found"

    label = log_files[0].stem
    match = re.fullmatch(r"\d+_async(\d+)(?:_at(\d+))?_c(\d+)_(wait_all|test_all)", label)
    if not match:
        return label

    async_enabled, async_threads, omp_threads, wait_mode = match.groups()
    if async_enabled == "0":
        progress = "off"
    else:
        progress = f"on ({async_threads or '1'} thread)"
    return f"OMP {omp_threads}; progress {progress}; {wait_mode}"


def has_async_progress(case_id: str, no_midcomm_dir: Path) -> bool:
    """Classify a case from its generated log filename."""
    return bool(list(no_midcomm_dir.glob(f"{case_id}_async1_*.log")))


def read_job_metadata(directory: Path) -> dict[str, str]:
    """Read the stable key-value fields recorded for a generated job."""
    path = directory / "job_metadata.log"
    if not path.is_file():
        return {}

    content = path.read_text(errors="replace")
    metadata: dict[str, str] = {}
    for line in content.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_]+", key):
            metadata[key] = value

    module_match = re.search(r"^intel-mpi/([^\s]+)$", content, re.MULTILINE)
    if module_match:
        metadata["mpi_version"] = module_match.group(1)
    openmpi_match = re.search(r"^Open MPI v([^\s]+)$", content, re.MULTILINE)
    if openmpi_match:
        metadata["mpi_version"] = openmpi_match.group(1)
    return metadata


def openmpi_transport_label(directory: Path, nodes: str) -> str:
    """Describe the OpenMPI BTL transport recorded by the generated job."""
    metadata_path = directory / "job_metadata.log"
    if not metadata_path.is_file():
        return "Open MPI transport unavailable"

    components = list(
        dict.fromkeys(
            re.findall(r"^mca:btl:([^:]+):version:", metadata_path.read_text(errors="replace"), re.MULTILINE)
        )
    )
    if nodes == "1" and "vader" in components:
        return "Open MPI BTL vader (intra-node shared memory)"
    if "tcp" in components and nodes not in {"", "1", "?"}:
        return "Open MPI BTL tcp (inter-node; NIC automatic)"
    if components:
        return f"Open MPI BTL {'/'.join(components)}"
    return "Open MPI transport unavailable"


def intelmpi_transport_label(metadata: dict[str, str], nodes: str) -> str:
    """Describe Intel MPI's fabric selection and OFI provider."""
    fabrics = metadata.get("I_MPI_FABRICS", "?")
    provider = metadata.get("I_MPI_OFI_PROVIDER", "?")
    if "ofi" not in fabrics.split(":"):
        return f"Intel MPI fabrics {fabrics}"
    if nodes not in {"", "1", "?"}:
        return f"Intel MPI shm (intra-node) + OFI {provider} (inter-node)"
    return f"Intel MPI OFI {provider}"


def metadata_summary(directory: Path) -> tuple[str, str]:
    """Format the run-level context that is shared by every plotted case."""
    metadata = read_job_metadata(directory)
    mpi_family = metadata.get("mpi_family", "unknown MPI")
    mpi = {"intelmpi": "Intel MPI", "openmpi": "Open MPI"}.get(mpi_family, mpi_family)
    if metadata.get("mpi_version"):
        mpi = f"{mpi} {metadata['mpi_version']}"
    nodes = metadata.get("nodes", "?")
    ranks = metadata.get("ntasks", "?")
    runtime_cpus = metadata.get("runtime_cpus_per_rank", "?")
    cluster = metadata.get("clusters", "unknown")
    partition = metadata.get("partition", "unknown")
    topology = metadata.get("topology", "unknown")

    first_line = (
        f"MPI: {mpi} | "
        f"Topology: {topology} ({nodes} node x {ranks} ranks; {runtime_cpus} runtime CPUs/rank) | "
        f"Cluster: {cluster} ({partition})"
    )
    grid_size = metadata.get("grid_size", "?")
    grid_label = f"{grid_size.split('_')[0]}^3" if len(grid_size.split("_")) == 3 and len(set(grid_size.split("_"))) == 1 else grid_size.replace("_", "x")
    second_line = (
        f"Grid: {grid_label} "
        f"| Divide: {metadata.get('divide', '?').replace('_', 'x')} "
        f"| Periodic: {metadata.get('periodic', '?').replace('_', ' ')} "
        f"| Ghost: {metadata.get('ghost', '?').replace('_', ' ')} | Variables: {metadata.get('vars', '?')} "
        f"| Comm cutoff: {metadata.get('comm_cutoff', '?')} | Mode: {metadata.get('comm_mode_hint', '?')} "
    )
    if mpi_family == "intelmpi":
        second_line += f"| Transport: {intelmpi_transport_label(metadata, nodes)}"
    elif mpi_family == "openmpi":
        second_line += f"| Transport: {openmpi_transport_label(directory, nodes)}"
    return first_line, second_line


def actual_send_payloads(directory: Path) -> dict[int, list[tuple[int, int]]]:
    """Read Comb's partner-aggregated send payloads from case 00 process output."""
    payloads: dict[int, list[tuple[int, int]]] = {}
    for path in sorted(directory.glob("Comb_00_proc*")):
        rank_match = re.fullmatch(r"Comb_00_proc(\d+)", path.name)
        if not rank_match:
            continue
        sends = [
            (int(match.group(1)), int(match.group(2)))
            for line in path.read_text(errors="replace").splitlines()
            if (match := SEND_PAYLOAD.match(line))
        ]
        if sends:
            payloads[int(rank_match.group(1))] = sends
    return payloads


def write_actual_payload_note(directory: Path, output_dir: Path) -> None:
    """Update only the generated payload block in the analysis note file."""
    payloads = actual_send_payloads(directory)
    if not payloads:
        return

    run_label = directory.name if RUN_DIR.match(directory.name) else "run"
    note_path = output_dir / "notes" / run_label / "experiment_notes.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    existing = note_path.read_text(errors="replace") if note_path.is_file() else f"# Experiment notes: {run_label}\n"
    if not re.search(r"^cycles=", existing, re.MULTILINE):
        cycles = run_cycles(directory)
        if cycles is not None:
            header = f"# Experiment notes: {run_label}"
            if existing.startswith(header):
                existing = existing.replace(header, f"{header}\ncycles={cycles}", 1)
            else:
                existing = f"cycles={cycles}\n" + existing
    for begin, end in (
        (PAYLOAD_NOTE_BEGIN, PAYLOAD_NOTE_END),
        ("<!-- actual-mpi-send-payloads: begin -->", "<!-- actual-mpi-send-payloads: end -->"),
    ):
        existing = re.sub(
            rf"\n?{re.escape(begin)}.*?{re.escape(end)}\n?",
            "\n",
            existing,
            flags=re.DOTALL,
        )
    existing = existing.rstrip()

    lines = [PAYLOAD_NOTE_BEGIN]
    for rank, sends in sorted(payloads.items()):
        details = "; ".join(
            f"partner {partner}: {bytes_sent} B ({bytes_sent / 1024:.2f} KiB)"
            for partner, bytes_sent in sends
        )
        lines.append(f"Actual MPI_Isend payloads, rank {rank}: {details}")
    lines.append(PAYLOAD_NOTE_END)
    note_path.write_text(existing + "\n\n" + "\n".join(lines) + "\n")


def read_run_notes(directory: Path) -> list[str]:
    """Read concise user notes for a paired midcomm/no_midcomm run."""
    if not RUN_DIR.match(directory.name) or directory.parent.name not in {"midcomm", "no_midcomm"}:
        return []

    grid_dir = directory.parent.parent
    note_path = grid_dir / "analysis" / "notes" / directory.name / "experiment_notes.md"
    legacy_note_path = grid_dir / "notes" / directory.name / "experiment_notes.md"
    if not note_path.is_file() and legacy_note_path.is_file():
        note_path = legacy_note_path
    if not note_path.is_file():
        return []

    notes: list[str] = []
    for raw_line in note_path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        notes.extend(textwrap.wrap(line, width=150, break_long_words=False, break_on_hyphens=False) or [line])
        if len(notes) >= 3:
            return notes[:3]
    return notes


def plot(
    rows: list[dict[str, object]],
    output_path: Path,
    no_midcomm_dir: Path,
    run_label: str | None = None,
    run_notes_override: list[str] | None = None,
) -> None:
    fig = plt.figure(figsize=(48, 94))
    grid = fig.add_gridspec(7, 2, height_ratios=(0.70, 1, 1, 1, 1, 1.45, 7.50), hspace=0.32)
    axes = [fig.add_subplot(grid[1 + index // 2, index % 2]) for index in range(8)]
    case_order = sorted({str(row["case"]) for row in rows}, key=int)
    x = np.arange(len(case_order))
    width = 0.28
    bar_offset = width / 2 + 0.025
    progress_off_count = sum(not has_async_progress(case_id, no_midcomm_dir) for case_id in case_order)

    panel_specs = [("mpi", policy) for policy in POLICIES] + [("mock", policy) for policy in POLICIES]
    policy_y_limits: dict[tuple[str, str, str], tuple[float, float]] = {}
    for policy in POLICIES:
        values = [
            100 * float(row[metric])
            for row in rows
            if (row["mesh_policy"], row["large_buffer_policy"], row["small_buffer_policy"]) == policy
            for metric in ("overlap_rate", "overall_overlap_gain")
        ]
        lower = min(values)
        upper = max(values)
        padding = max((upper - lower) * 0.10, 1.0)
        policy_y_limits[policy] = (lower - padding, upper + padding)

    for axis, (backend, policy) in zip(axes, panel_specs):
        policy_rows = {
            str(row["case"]): row
            for row in rows
            if row["comm_backend"] == backend
            and (row["mesh_policy"], row["large_buffer_policy"], row["small_buffer_policy"]) == policy
        }
        overlap = [100 * float(policy_rows[case]["overlap_rate"]) if case in policy_rows else np.nan for case in case_order]
        overall_gain = [100 * float(policy_rows[case]["overall_overlap_gain"]) if case in policy_rows else np.nan for case in case_order]
        case_labels = [f"Case {case}" if case in policy_rows else f"Case {case}\nmissing" for case in case_order]

        for case_index in range(len(case_order)):
            if case_index % 2 == 0:
                axis.axvspan(case_index - 0.5, case_index + 0.5, color="#f7fbff", zorder=0)
            if case_index:
                axis.axvline(case_index - 0.5, color="#d1d5db", linewidth=0.8, zorder=1)
        if 0 < progress_off_count < len(case_order):
            axis.axvline(
                progress_off_count - 0.5,
                color="#1f2937",
                linestyle="--",
                linewidth=2.4,
                zorder=3,
            )

        axis.bar(x - bar_offset, overlap, width, label="Compute overlap rate", color="#2a6fbb", zorder=2)
        axis.bar(x + bar_offset, overall_gain, width, label="Overall overlap gain", color="#c9574d", zorder=2)
        for case_index, case in enumerate(case_order):
            if case not in policy_rows:
                continue
            row = policy_rows[case]
            blue_time = float(row["wait_recv_no_mid_avg_s"]) - float(row["wait_recv_mid_avg_s"])
            red_time = float(row["serial_work_estimate_s"]) - float(row["bench_mid_max_s"])
            axis.annotate(
                f"{format_blue_overlap_time(blue_time)}\n(per call)",
                (case_index, -0.17),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="top",
                color="#2a6fbb",
                fontsize=14,
                clip_on=False,
            )
            axis.annotate(
                format_time_difference(red_time),
                (case_index, -0.29),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="top",
                color="#c9574d",
                fontsize=14,
                clip_on=False,
            )
        axis.axhline(0, color="#4b5563", linewidth=0.8)
        axis.set_xlim(-0.5, len(case_order) - 0.5)
        axis.set_ylim(*policy_y_limits[policy])
        axis.set_title(f"{backend.upper()} | {policy_label(policy)}", fontsize=36, pad=21)
        axis.set_xticks(
            x,
            case_labels,
            rotation=0,
            ha="center",
            fontsize=24,
        )
        axis.tick_params(axis="x", pad=4)
        axis.tick_params(axis="y", labelsize=24)
        axis.grid(axis="y", alpha=0.25)

    for axis in (axes[0], axes[2], axes[4], axes[6]):
        axis.set_ylabel("Improvement (%)", fontsize=30)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.975),
        ncols=2,
        frameon=False,
        fontsize=33,
    )
    run_label = run_label or (no_midcomm_dir.name if RUN_DIR.match(no_midcomm_dir.name) else None)
    title = "MPI and Mock Compute Overlap Rate and Overall Gain by Case"
    if run_label:
        title = f"{title} ({run_label})"
    fig.suptitle(title, y=0.995, fontsize=45)
    summary_line_1, summary_line_2 = metadata_summary(no_midcomm_dir)
    run_notes = run_notes_override if run_notes_override is not None else read_run_notes(no_midcomm_dir)
    configured_target_us = float(rows[0]["injected_compute_target_us"])
    fig.text(0.5, 0.940, summary_line_1, ha="center", va="center", fontsize=36)
    fig.text(0.5, 0.922, summary_line_2, ha="center", va="center", fontsize=36)
    fig.text(
        0.5,
        0.902,
        f"Injected compute target: {configured_target_us:g} us per mid-comm call",
        ha="center",
        va="center",
        fontsize=36,
    )
    fig.text(
        0.5,
        0.884,
        "Blue: (wait-recv no-compute avg - wait-recv with-compute avg) / mid-comm avg "
        "[same per-call sample average; no sample multiplier]",
        ha="center",
        va="center",
        fontsize=19,
    )
    fig.text(
        0.5,
        0.868,
        "Red: [bench no-compute max + (mid-comm num / ranks) x mid-comm avg - bench with-compute max] "
        "/ [bench no-compute max + (mid-comm num / ranks) x mid-comm avg]",
        ha="center",
        va="center",
        fontsize=18,
    )
    if run_notes:
        fig.text(
            0.5,
            0.850,
            "Run notes: " + "\n".join(run_notes),
            ha="center",
            va="top",
            fontsize=36,
        )
    table_axis = fig.add_subplot(grid[0, :])
    table_axis.axis("off")
    progress_off_cases = [case_id for case_id in case_order if not has_async_progress(case_id, no_midcomm_dir)]
    progress_on_cases = [case_id for case_id in case_order if has_async_progress(case_id, no_midcomm_dir)]
    table_rows = []
    for index in range(max(len(progress_off_cases), len(progress_on_cases))):
        row = []
        for cases in (progress_off_cases, progress_on_cases):
            if index < len(cases):
                case_id = cases[index]
                row.extend((f"Case {case_id}", describe_case(case_id, no_midcomm_dir)))
            else:
                row.extend(("", ""))
        table_rows.append(row)
    table = table_axis.table(
        cellText=table_rows,
        colLabels=("Progress off", "Configuration", "Progress on", "Configuration"),
        cellLoc="left",
        colLoc="left",
        colWidths=(0.08, 0.42, 0.08, 0.42),
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(45)
    table.scale(1, 3.75)
    for column in range(4):
        table[(0, column)].set_facecolor("#dbeafe")
        table[(0, column)].set_text_props(weight="bold")

    timing_table_axis = fig.add_subplot(grid[6, :])
    timing_table_axis.axis("off")
    rows_by_key = {
        (
            str(row["case"]),
            str(row["comm_backend"]),
            str(row["mesh_policy"]),
            str(row["large_buffer_policy"]),
            str(row["small_buffer_policy"]),
        ): row
        for row in rows
    }
    timing_table_rows = []
    phase_policy = ("seq", "seq", "seq")
    phase_metrics = (
        ("pre-comm", "pre-comm"),
        ("post-send", "post-send"),
        ("mid-comm", None),
        ("wait-recv", "wait-recv"),
        ("post-comm", "post-comm"),
        ("bench-comm", "bench-comm"),
    )
    case_start_rows: list[int] = []
    for case_id in case_order:
        row = rows_by_key[(case_id, "mpi", *phase_policy)]
        case_start_rows.append(len(timing_table_rows) + 1)
        for phase_index, (phase_name, row_key) in enumerate(phase_metrics):
            if row_key is None:
                no_value = 0.0
                mid_value = float(row["measured_midcomm_per_call_avg_us"]) / 1_000
            elif row_key == "bench-comm":
                no_value = float(row["bench_no_mid_max_s"]) * 1_000
                mid_value = float(row["bench_mid_max_s"]) * 1_000
            else:
                no_value = float(row[f"{row_key.replace('-', '_')}_no_mid_avg_s"]) * 1_000
                mid_value = float(row[f"{row_key.replace('-', '_')}_mid_avg_s"]) * 1_000
            timing_table_rows.append((
                f"Case {case_id}" if phase_index == 0 else "",
                phase_name,
                f"{no_value:.3f} ms",
                f"{mid_value:.3f} ms",
                f"{mid_value - no_value:+.3f} ms",
            ))
    timing_table = timing_table_axis.table(
        cellText=timing_table_rows,
        colLabels=(
            "Case",
            "Phase",
            "No compute",
            "With compute",
            "Change",
        ),
        cellLoc="center",
        colLoc="center",
        colWidths=(0.14, 0.20, 0.22, 0.22, 0.22),
        loc="center",
    )
    timing_table.auto_set_font_size(False)
    timing_table.set_fontsize(30)
    timing_table.scale(1, 2.50)
    for column in range(5):
        timing_table[(0, column)].set_facecolor("#dbeafe")
        timing_table[(0, column)].set_text_props(weight="bold")
    for row_index in case_start_rows:
        for column in range(5):
            cell = timing_table[(row_index, column)]
            cell.set_facecolor("#f7fbff")
            cell.set_linewidth(2.2 if row_index > 1 else 0.8)
            if column == 0:
                cell.set_text_props(weight="bold")
        wait_recv_row = row_index + 3
        for column in range(5):
            timing_table[(wait_recv_row, column)].set_facecolor("#eaf4ff")
    timing_table_axis.set_title(
        "MPI Phase Timing Comparison | Mesh seq | Buffers seq/seq",
        fontsize=38,
        pad=16,
    )

    difference_table_axis = fig.add_subplot(grid[5, :])
    difference_table_axis.axis("off")
    difference_table_rows = []
    difference_policy_order = (
        ("omp", "omp", "omp"),
        ("omp", "omp", "seq"),
        ("omp", "seq", "seq"),
        ("seq", "seq", "seq"),
    )
    for case_id in case_order:
        values = []
        for policy in difference_policy_order:
            mpi_row = rows_by_key[(case_id, "mpi", *policy)]
            mock_row = rows_by_key[(case_id, "mock", *policy)]
            difference_ms = (
                float(mpi_row["wait_recv_no_mid_avg_s"])
                - float(mock_row["wait_recv_no_mid_avg_s"])
            ) * 1_000
            values.append(f"{difference_ms:.6f}")
        difference_table_rows.append((case_id, *values))
    difference_table = difference_table_axis.table(
        cellText=difference_table_rows,
        colLabels=(
            "Case",
            "omp / omp-omp (ms)",
            "omp / omp-seq (ms)",
            "omp / seq-seq (ms)",
            "seq / seq-seq (ms)",
        ),
        cellLoc="center",
        colLoc="center",
        colWidths=(0.10, 0.225, 0.225, 0.225, 0.225),
        loc="center",
    )
    difference_table.auto_set_font_size(False)
    difference_table.set_fontsize(42)
    difference_table.scale(1, 3.00)
    for column in range(5):
        difference_table[(0, column)].set_facecolor("#dbeafe")
        difference_table[(0, column)].set_text_props(weight="bold")
    difference_table_axis.set_title("MPI - Mock Communication-Time Difference", fontsize=42, pad=12)

    fig.subplots_adjust(top=0.790 if run_notes else 0.855, bottom=0.03, left=0.06, right=0.985)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--midcomm-dir", type=Path)
    parser.add_argument("--no-midcomm-dir", type=Path)
    parser.add_argument(
        "--average-midcomm-dir",
        type=Path,
        action="append",
        help="Repeat for two or more midcomm/run_### directories to average after configuration validation.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("analysis"))
    args = parser.parse_args()

    average_dirs = args.average_midcomm_dir or []
    if average_dirs:
        if args.midcomm_dir or args.no_midcomm_dir:
            parser.error("--average-midcomm-dir cannot be combined with --midcomm-dir or --no-midcomm-dir")
        try:
            rows, warnings, run_label, plot_directory = average_rows(average_dirs)
        except ValueError as exc:
            parser.error(str(exc))
        filename_stem = f"overlap_metrics_average_{run_label}"
        average_notes = write_average_note(args.output_dir, average_dirs, run_label)
    else:
        if args.midcomm_dir is None or args.no_midcomm_dir is None:
            parser.error("--midcomm-dir and --no-midcomm-dir are required for single-run analysis")
        for directory in (args.midcomm_dir, args.no_midcomm_dir):
            if not directory.is_dir():
                parser.error(f"Not a directory: {directory}")
        rows, warnings = compute_rows(args.midcomm_dir, args.no_midcomm_dir)
        run_label = args.no_midcomm_dir.name if RUN_DIR.match(args.no_midcomm_dir.name) else None
        plot_directory = args.no_midcomm_dir
        filename_stem = f"overlap_metrics_{run_label}" if run_label else "overlap_metrics"
        average_notes = None
    if not rows:
        raise RuntimeError("No complete paired MPI or mock timing blocks were found.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / f"{filename_stem}.csv"
    png_path = args.output_dir / f"{filename_stem}.png"
    write_csv(rows, csv_path)
    if not average_dirs:
        write_actual_payload_note(args.midcomm_dir, args.output_dir)
    plot(
        rows,
        png_path,
        plot_directory,
        f"average {run_label}" if average_dirs else run_label,
        average_notes,
    )

    print(f"Wrote {len(rows)} policy/case rows to {csv_path}")
    print(f"Wrote eight-panel chart to {png_path}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())