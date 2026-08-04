#!/usr/bin/env python3
"""Calculate paired MPI overlap metrics and render an eight-panel bar chart.

Example:
  ./venv/bin/python analyze_overlap.py \
    --midcomm-dir generated/cm4_inter/intelmpi/1n2r_c24/small/midcomm \
    --no-midcomm-dir generated/cm4_inter/intelmpi/1n2r_c24/small/no_midcomm
"""
from __future__ import annotations

import argparse
import csv
import re
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


def rank_count(directory: Path) -> int:
    """Return the rank count recorded by the generated job, if available."""
    try:
        return max(1, int(read_job_metadata(directory).get("ntasks", "1")))
    except ValueError:
        return 1


def total_midcomm_time(metric: dict[str, float], ranks: int) -> float:
    """Estimate per-rank injected compute time over the whole benchmark.

    The `mid-comm` timer records once per cycle on every rank. Its summary
    average is per invocation, so scale it by samples per rank before adding
    it to the whole-benchmark `bench-comm` time.
    """
    return float(metric["average"]) * float(metric["num"]) / ranks


def format_time_pair(no_midcomm: float, midcomm: float) -> str:
    """Format paired no-midcomm/midcomm times compactly for x-axis labels."""
    if max(abs(no_midcomm), abs(midcomm)) < 1:
        return f"{no_midcomm * 1_000:.1f}/{midcomm * 1_000:.1f} ms"
    return f"{no_midcomm:.3f}/{midcomm:.3f} s"


def compute_rows(midcomm_dir: Path, no_midcomm_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
    mid_files = summary_files(midcomm_dir)
    no_files = summary_files(no_midcomm_dir)
    case_ids = sorted(set(mid_files) & set(no_files), key=int)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    ranks = rank_count(midcomm_dir)

    missing_mid = sorted(set(no_files) - set(mid_files), key=int)
    missing_no = sorted(set(mid_files) - set(no_files), key=int)
    if missing_mid:
        warnings.append(f"Missing midcomm summaries for cases: {', '.join(missing_mid)}")
    if missing_no:
        warnings.append(f"Missing no_midcomm summaries for cases: {', '.join(missing_no)}")

    for case_id in case_ids:
        mid_blocks = parse_summary(mid_files[case_id])
        no_blocks = parse_summary(no_files[case_id])

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

                required = ("post-send", "wait-recv", "bench-comm")
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
                if exposed_no <= 0 or serial_total <= 0:
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
                        "post_send_no_mid_avg_s": baseline["post-send"]["average"],
                        "post_send_mid_avg_s": mid["post-send"]["average"],
                        "overlap_rate": (exposed_no - exposed_mid) / exposed_no,
                        "bench_no_mid_max_s": bench_no,
                        "bench_mid_max_s": bench_mid,
                        "midcomm_compute_total_avg_s": mid_compute_total,
                        "serial_work_estimate_s": serial_total,
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
        "post_send_no_mid_avg_s",
        "post_send_mid_avg_s",
        "overlap_rate",
        "bench_no_mid_max_s",
        "bench_mid_max_s",
        "midcomm_compute_total_avg_s",
        "serial_work_estimate_s",
        "overall_overlap_gain",
    ]
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


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
    grid = metadata.get("grid", "unknown")
    nodes = metadata.get("nodes", "?")
    ranks = metadata.get("ntasks", "?")
    runtime_cpus = metadata.get("runtime_cpus_per_rank", "?")
    cluster = metadata.get("clusters", "unknown")
    partition = metadata.get("partition", "unknown")
    topology = metadata.get("topology", "unknown")

    first_line = (
        f"MPI: {mpi} | Message scale: {grid} | "
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


def plot(rows: list[dict[str, object]], output_path: Path, no_midcomm_dir: Path) -> None:
    fig = plt.figure(figsize=(36, 44))
    grid = fig.add_gridspec(5, 2, height_ratios=(0.90, 1, 1, 1, 1), hspace=0.46)
    axes = [fig.add_subplot(grid[1 + index // 2, index % 2]) for index in range(8)]
    case_order = sorted({str(row["case"]) for row in rows}, key=int)
    x = np.arange(len(case_order))
    width = 0.28
    bar_offset = width / 2 + 0.025
    progress_off_count = sum(not has_async_progress(case_id, no_midcomm_dir) for case_id in case_order)

    panel_specs = [("mpi", policy) for policy in POLICIES] + [("mock", policy) for policy in POLICIES]
    for axis, (backend, policy) in zip(axes, panel_specs):
        policy_rows = {
            str(row["case"]): row
            for row in rows
            if row["comm_backend"] == backend
            and (row["mesh_policy"], row["large_buffer_policy"], row["small_buffer_policy"]) == policy
        }
        overlap = [100 * float(policy_rows[case]["overlap_rate"]) if case in policy_rows else np.nan for case in case_order]
        overall_gain = [100 * float(policy_rows[case]["overall_overlap_gain"]) if case in policy_rows else np.nan for case in case_order]
        case_labels = []
        for case in case_order:
            if case not in policy_rows:
                case_labels.append(f"Case {case}\nmissing")
                continue
            row = policy_rows[case]
            case_labels.append(
                f"Case {case}\n"
                f"Post: {format_time_pair(float(row['post_send_no_mid_avg_s']), float(row['post_send_mid_avg_s']))}\n"
                f"Wrecv: {format_time_pair(float(row['wait_recv_no_mid_avg_s']), float(row['wait_recv_mid_avg_s']))}\n"
                f"Tmax: {format_time_pair(float(row['bench_no_mid_max_s']), float(row['bench_mid_max_s']))}"
            )

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

        axis.bar(x - bar_offset, overlap, width, label="Wait-recv reduction", color="#2a6fbb", zorder=2)
        axis.bar(x + bar_offset, overall_gain, width, label="Overall overlap gain", color="#c9574d", zorder=2)
        axis.axhline(0, color="#4b5563", linewidth=0.8)
        axis.set_xlim(-0.5, len(case_order) - 0.5)
        axis.set_title(f"{backend.upper()} | {policy_label(policy)}", fontsize=24, pad=14)
        axis.set_xticks(
            x,
            case_labels,
            rotation=0,
            ha="center",
            fontsize=12,
        )
        axis.tick_params(axis="y", labelsize=20)
        axis.grid(axis="y", alpha=0.25)

    for axis in (axes[0], axes[2], axes[4], axes[6]):
        axis.set_ylabel("Improvement (%)", fontsize=20)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncols=2,
        frameon=False,
        fontsize=24,
    )
    fig.suptitle("MPI and Mock Wait-recv Reduction and Overall Gain by Case", y=0.955, fontsize=24)
    summary_line_1, summary_line_2 = metadata_summary(no_midcomm_dir)
    fig.text(0.5, 0.920, summary_line_1, ha="center", va="center", fontsize=28)
    fig.text(0.5, 0.902, summary_line_2, ha="center", va="center", fontsize=28)
    fig.text(
        0.5,
        0.888,
        "Blue = wait-recv reduction | Case labels: left/right = no_midcomm/midcomm | "
        "Post = post-send average | Wrecv = wait-recv average | Tmax = bench-comm max",
        ha="center",
        va="center",
        fontsize=16,
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
    table.set_fontsize(24)
    table.scale(1, 2.40)
    for column in range(4):
        table[(0, column)].set_facecolor("#dbeafe")
        table[(0, column)].set_text_props(weight="bold")

    fig.subplots_adjust(top=0.882, bottom=0.035, left=0.065, right=0.985)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--midcomm-dir", type=Path, required=True)
    parser.add_argument("--no-midcomm-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("analysis"))
    args = parser.parse_args()

    for directory in (args.midcomm_dir, args.no_midcomm_dir):
        if not directory.is_dir():
            parser.error(f"Not a directory: {directory}")

    rows, warnings = compute_rows(args.midcomm_dir, args.no_midcomm_dir)
    if not rows:
        raise RuntimeError("No complete paired MPI or mock timing blocks were found.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "overlap_metrics.csv"
    png_path = args.output_dir / "overlap_metrics.png"
    write_csv(rows, csv_path)
    plot(rows, png_path, args.no_midcomm_dir)

    print(f"Wrote {len(rows)} policy/case rows to {csv_path}")
    print(f"Wrote eight-panel chart to {png_path}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())