#!/usr/bin/env python3
"""COMB benchmark visualisation.

For every (queue, run_name, case_id) condition we pair the `comb_midcomm_omp`
run against the matching `comb_no_midcomm_omp` run and draw a horizontal
stacked-bar chart with four communication sections:

    - mock seq  -> Comm mock Mesh seq Host Buffers seq Host seq Host
    - mock omp  -> Comm mock Mesh omp Host Buffers omp Host omp Host
    - mpi  seq  -> Comm mpi  Mesh seq Host Buffers seq Host seq Host
    - mpi  omp  -> Comm mpi  Mesh omp Host Buffers omp Host omp Host

Each section produces two rows: one for the run *with* compute injected into
`mid-comm`, one for the pure-communication baseline (*no midcomm*). Phase
durations are scaled by `Num cycles` so the total bar length matches the
`bench-comm` wall clock reported by COMB.

Overlap (per section) is defined as::

    compute = mid_comm_with_compute * num_cycles
    overlap = 1 - (bench_with - bench_no) / compute

See `visualization_output/README.md` for details.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

SCRIPT_DIR = Path(__file__).resolve().parent

VARIANT_DIRS = {
    "with_compute": "comb_midcomm_omp",
    "no_midcomm": "comb_no_midcomm_omp",
}

QUEUES = ["cm4_inter", "cm4_std"]

SECTIONS: List[Tuple[str, str]] = [
    ("mock seq", "Comm mock Mesh seq Host Buffers seq Host seq Host"),
    ("mock omp", "Comm mock Mesh omp Host Buffers omp Host omp Host"),
    ("mpi  seq", "Comm mpi Mesh seq Host Buffers seq Host seq Host"),
    ("mpi  omp", "Comm mpi Mesh omp Host Buffers omp Host omp Host"),
]

WINDOW_BASELINES = {
    "mock seq": None,
    "mock omp": None,
    "mpi  seq": "Comm mock Mesh seq Host Buffers seq Host seq Host",
    "mpi  omp": "Comm mock Mesh omp Host Buffers omp Host omp Host",
}

PHASES = [
    "pre-comm",
    "post-recv",
    "post-send",
    "mid-comm",
    "wait-recv",
    "wait-send",
    "post-comm",
]

PHASE_COLORS = {
    "pre-comm":  "#94a3b8",
    "post-recv": "#38bdf8",
    "post-send": "#0ea5e9",
    "mid-comm":  "#f97316",
    "wait-recv": "#22c55e",
    "wait-send": "#16a34a",
    "post-comm": "#a3a3a3",
}

CASE_LABELS = {
    "00": "async0_c1_waitall",
    "01": "async0_c4_waitall",
    "02": "async0_c1_testall",
    "03": "async0_c4_testall",
    "04": "async1_c1_waitall",
    "05": "async1_c4_waitall",
    "06": "async1_c1_testall",
    "07": "async1_c4_testall",
}

RUN_CASE_LABELS = {
    "run_5_more_omp8_big_mes": {
        "01": "async0_c8_waitall",
        "05": "async1_c8_waitall",
    },
}


def get_case_label(run_name: str, case_id: str) -> str:
    labels = RUN_CASE_LABELS.get(run_name)
    if labels and case_id in labels:
        return labels[case_id]
    return CASE_LABELS.get(case_id, f"case_{case_id}")


@dataclass
class Summary:
    path: Path
    num_cycles: int = 1
    sections: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def phase(self, section: str, phase: str) -> float:
        return self.sections.get(section, {}).get(phase, 0.0)

    def bench(self, section: str) -> float:
        return self.phase(section, "bench-comm")


@dataclass
class SectionRow:
    label: str
    phases_with: Dict[str, float]
    phases_no: Dict[str, float]
    bench_with: float
    bench_no: float
    compute: float
    fixed_window_with: float
    fixed_window_no: float
    comm_window: float
    measured_window: float
    overhead_ratio: Optional[float]
    has_with: bool
    has_no: bool


@dataclass
class ConditionChart:
    queue: str
    run_name: str
    case_id: str
    case_label: str
    rows: List[SectionRow]
    max_time: float
    svg_path: Path


# --------------------------------------------------------------------------- #
# Parsing                                                                     #
# --------------------------------------------------------------------------- #

METRIC_RE = re.compile(
    r"^\s*([A-Za-z0-9_-]+)\s*,\s*\d+\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*$"
)
CYCLES_RE = re.compile(r"Num cycles\s+(\d+)")


def parse_summary(path: Path) -> Summary:
    summary = Summary(path=path)
    current: Optional[str] = None
    for line in path.read_text(errors="ignore").splitlines():
        cm = CYCLES_RE.search(line)
        if cm:
            summary.num_cycles = int(cm.group(1))
        stripped = line.strip()
        if stripped.startswith("Starting test "):
            current = stripped[len("Starting test "):]
            summary.sections.setdefault(current, {})
            continue
        if current is None:
            continue
        m = METRIC_RE.match(line)
        if m:
            summary.sections[current][m.group(1)] = float(m.group(2))
    return summary


def discover_conditions(root: Path) -> List[Tuple[str, str, str]]:
    """Return sorted unique (queue, run_name, case_id) available in any variant."""
    found = set()
    for variant_dir in VARIANT_DIRS.values():
        base = root / variant_dir
        if not base.is_dir():
            continue
        for queue in QUEUES:
            qdir = base / queue
            if not qdir.is_dir():
                continue
            for run_dir in sorted(qdir.iterdir()):
                if not run_dir.is_dir():
                    continue
                for summary_file in sorted(run_dir.glob("Comb_*_summary.csv")):
                    m = re.search(r"Comb_(\d+)_summary\.csv", summary_file.name)
                    if m:
                        found.add((queue, run_dir.name, m.group(1)))
    return sorted(found)


def locate_summary(
    root: Path, variant_key: str, queue: str, run_name: str, case_id: str
) -> Optional[Path]:
    path = (
        root
        / VARIANT_DIRS[variant_key]
        / queue
        / run_name
        / f"Comb_{case_id}_summary.csv"
    )
    return path if path.is_file() else None


# --------------------------------------------------------------------------- #
# Analysis                                                                    #
# --------------------------------------------------------------------------- #


def scale_phases(summary: Optional[Summary], section: str) -> Dict[str, float]:
    if summary is None:
        return {phase: 0.0 for phase in PHASES}
    cycles = summary.num_cycles or 1
    return {phase: summary.phase(section, phase) * cycles for phase in PHASES}


def overlap_window(summary: Optional[Summary], section: str, phase: str) -> float:
    if summary is None:
        return 0.0
    cycles = summary.num_cycles or 1
    return summary.phase(section, phase) * cycles


def effective_wait_window(
    summary: Optional[Summary],
    section: str,
    baseline_section: Optional[str],
) -> Tuple[float, float]:
    raw = overlap_window(summary, section, "wait-recv")
    fixed = overlap_window(summary, baseline_section, "wait-recv") if baseline_section else 0.0
    return max(0.0, raw - fixed), fixed


def compute_overhead_ratio(
    compute: float, measured_window: float, comm_window: float
) -> Optional[float]:
    # Paper metric: extra measured overhead relative to the serialized case.
    #   ideal           = max(compute, comm)
    #   serialized      = compute + comm
    #   overhead_ratio  = (measured - ideal) / (serialized - ideal)
    #                   = (measured - max(compute, comm)) / min(compute, comm)
    comm = comm_window
    denom = min(compute, comm)
    if denom <= 0:
        return None
    ideal = max(compute, comm)
    return (measured_window - ideal) / denom


def build_condition_rows(
    summary_with: Optional[Summary], summary_no: Optional[Summary]
) -> Tuple[List[SectionRow], float]:
    rows: List[SectionRow] = []
    max_time = 0.0
    for label, section in SECTIONS:
        phases_with = scale_phases(summary_with, section)
        phases_no = scale_phases(summary_no, section)
        bench_with = summary_with.bench(section) if summary_with else 0.0
        bench_no = summary_no.bench(section) if summary_no else 0.0
        compute = phases_with.get("mid-comm", 0.0)
        baseline_section = WINDOW_BASELINES[label]
        comm_window, fixed_window_no = effective_wait_window(summary_no, section, baseline_section)
        residual_wait_with, fixed_window_with = effective_wait_window(summary_with, section, baseline_section)
        measured_window = compute + residual_wait_with
        overhead_ratio = compute_overhead_ratio(compute, measured_window, comm_window)
        has_with = bool(summary_with and summary_with.sections.get(section))
        has_no = bool(summary_no and summary_no.sections.get(section))
        rows.append(
            SectionRow(
                label=label,
                phases_with=phases_with,
                phases_no=phases_no,
                bench_with=bench_with,
                bench_no=bench_no,
                compute=compute,
                fixed_window_with=fixed_window_with,
                fixed_window_no=fixed_window_no,
                comm_window=comm_window,
                measured_window=measured_window,
                overhead_ratio=overhead_ratio,
                has_with=has_with,
                has_no=has_no,
            )
        )
        max_time = max(max_time, sum(phases_with.values()), sum(phases_no.values()))
    return rows, max_time


# --------------------------------------------------------------------------- #
# SVG rendering                                                               #
# --------------------------------------------------------------------------- #


def _bar(cursor_x: float, y: float, width: float, height: float, color: str) -> str:
    return (
        f'<rect x="{cursor_x:.2f}" y="{y:.2f}" width="{width:.2f}" '
        f'height="{height:.2f}" fill="{color}" stroke="#ffffff" stroke-width="0.5"/>'
    )


def render_condition_svg(chart: ConditionChart, subtitle: str) -> str:
    left = 220
    right = 60
    top = 100
    row_height = 36
    inner_gap = 6      # between with/no pair
    group_gap = 22     # between sections
    plot_width = 960
    rows = chart.rows

    total_rows = len(rows) * 2
    height = (
        top
        + total_rows * row_height
        + (len(rows) - 1) * group_gap
        + (len(rows)) * inner_gap
        + 160
    )
    width = left + plot_width + right
    max_time = chart.max_time * 1.12 if chart.max_time > 0 else 1.0

    out: List[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
    )
    out.append(
        "<style>text{font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "fill:#111827;}</style>"
    )

    title = (
        f"{chart.queue} / {chart.run_name} / case {chart.case_id} "
        f"({chart.case_label})"
    )
    out.append(
        f'<text x="{width/2}" y="36" text-anchor="middle" font-size="20" '
        f'font-weight="700">{escape(title)}</text>'
    )
    out.append(
        f'<text x="{width/2}" y="62" text-anchor="middle" font-size="13" '
        f'fill="#4b5563">{escape(subtitle)}</text>'
    )

    # Y positions for each row
    positions: List[Tuple[float, float]] = []  # (y_with, y_no) per section
    y = top
    for _ in rows:
        y_with = y
        y_no = y + row_height + inner_gap
        positions.append((y_with, y_no))
        y = y_no + row_height + group_gap

    axis_y = y - group_gap + 10
    # Gridlines + x ticks
    for tick in range(6):
        value = max_time * tick / 5.0
        x = left + plot_width * tick / 5.0
        out.append(
            f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{axis_y}" '
            f'stroke="#e5e7eb" stroke-dasharray="4 4"/>'
        )
        out.append(
            f'<text x="{x}" y="{axis_y + 18}" text-anchor="middle" '
            f'font-size="12">{value:.3f}s</text>'
        )
    out.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{left + plot_width}" y2="{axis_y}" '
        f'stroke="#374151"/>'
    )

    for row, (y_with, y_no) in zip(rows, positions):
        # Section label (centered vertically on the pair)
        label_y = (y_with + y_no + row_height) / 2 + 4
        out.append(
            f'<text x="{left - 12}" y="{label_y - 14}" text-anchor="end" '
            f'font-size="14" font-weight="700">{escape(row.label)}</text>'
        )
        overhead_text = (
            f"ratio {row.overhead_ratio:.3f}x"
            if row.overhead_ratio is not None
            else "no compute"
        )
        ideal = max(row.compute, row.comm_window)
        serial = row.compute + row.comm_window
        delta_measured = row.measured_window - ideal
        delta_serialized = min(row.compute, row.comm_window)
        out.append(
            f'<text x="{left - 12}" y="{label_y + 4}" text-anchor="end" '
            f'font-size="11" fill="#374151">'
            f'compute {row.compute:.3f}s  |  comm-window {row.comm_window:.3f}s  |  fixed mock {row.fixed_window_no:.3f}s'
            f'</text>'
        )
        out.append(
            f'<text x="{left - 12}" y="{label_y + 20}" text-anchor="end" '
            f'font-size="11" fill="#6b7280">'
            f'measured-window {row.measured_window:.3f}s | ideal {ideal:.3f}s / serial {serial:.3f}s '
            f'| serialized Δ {delta_serialized:.3f}s → {escape(overhead_text)}'
            f'</text>'
        )

        # with-compute bar
        _draw_row(
            out,
            y=y_with,
            row_height=row_height,
            left=left,
            plot_width=plot_width,
            max_time=max_time,
            phases=row.phases_with,
            total_label=f"with compute  {row.bench_with:.3f}s",
            has_data=row.has_with,
        )
        # no-midcomm bar
        _draw_row(
            out,
            y=y_no,
            row_height=row_height,
            left=left,
            plot_width=plot_width,
            max_time=max_time,
            phases=row.phases_no,
            total_label=f"no midcomm    {row.bench_no:.3f}s",
            has_data=row.has_no,
        )

    # Legend
    legend_y = axis_y + 46
    legend_x = left
    for phase in PHASES:
        out.append(_bar(legend_x, legend_y, 14, 14, PHASE_COLORS[phase]))
        out.append(
            f'<text x="{legend_x + 20}" y="{legend_y + 12}" font-size="12">'
            f'{escape(phase)}</text>'
        )
        legend_x += 115

    out.append(
        f'<text x="{left}" y="{legend_y + 40}" font-size="11" fill="#6b7280">'
        f'paper overhead ratio on overlap window: for mpi rows, comm-window = wait-recv(mpi) − wait-recv(mock), '
        f'measured-window = mid-comm(with) + residual wait-recv(with). 0 = perfect overlap, 1 = serialized.'
        f'</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def _draw_row(
    out: List[str],
    y: float,
    row_height: float,
    left: float,
    plot_width: float,
    max_time: float,
    phases: Dict[str, float],
    total_label: str,
    has_data: bool,
) -> None:
    if not has_data:
        out.append(
            f'<rect x="{left}" y="{y}" width="{plot_width}" height="{row_height}" '
            f'fill="#f3f4f6" stroke="#e5e7eb"/>'
        )
        out.append(
            f'<text x="{left + plot_width/2}" y="{y + row_height/2 + 4}" '
            f'text-anchor="middle" font-size="12" fill="#9ca3af">'
            f'(not available)</text>'
        )
        return

    cursor = left
    total = sum(phases.values())
    for phase in PHASES:
        value = phases.get(phase, 0.0)
        if value <= 0:
            continue
        w = plot_width * value / max_time
        out.append(_bar(cursor, y, w, row_height, PHASE_COLORS[phase]))
        if w > 40:
            out.append(
                f'<text x="{cursor + w/2}" y="{y + row_height/2 - 2}" '
                f'text-anchor="middle" font-size="10" fill="#0f172a">'
                f'{escape(phase)}</text>'
            )
            out.append(
                f'<text x="{cursor + w/2}" y="{y + row_height/2 + 11}" '
                f'text-anchor="middle" font-size="10" fill="#0f172a">'
                f'{value:.3f}s</text>'
            )
        cursor += w
    out.append(
        f'<text x="{cursor + 8}" y="{y + row_height/2 + 4}" '
        f'font-size="11" fill="#374151">{escape(total_label)}</text>'
    )
    # total check line
    _ = total


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #


def extract_args_subtitle(summary: Optional[Summary]) -> str:
    if summary is None:
        return ""
    # First line after header is 'Args  ./comb;...'
    try:
        for line in summary.path.read_text(errors="ignore").splitlines()[:5]:
            if line.startswith("Args"):
                tokens = line.split(";")
                size = tokens[1] if len(tokens) > 1 else ""
                cutoff = ""
                for i, tok in enumerate(tokens):
                    if tok.strip() == "cutoff" and i + 1 < len(tokens):
                        cutoff = tokens[i + 1].strip()
                omp = ""
                for i, tok in enumerate(tokens):
                    if "omp_num_threads" in tok.lower():
                        pass
                extra = f"size {size}"
                if cutoff:
                    extra += f"  |  cutoff {cutoff}"
                extra += f"  |  num_cycles {summary.num_cycles}"
                return extra
    except Exception:
        pass
    return f"num_cycles {summary.num_cycles}"


def build_chart(
    root: Path, out_dir: Path, queue: str, run_name: str, case_id: str
) -> Optional[ConditionChart]:
    path_with = locate_summary(root, "with_compute", queue, run_name, case_id)
    path_no = locate_summary(root, "no_midcomm", queue, run_name, case_id)
    if path_with is None and path_no is None:
        return None
    summary_with = parse_summary(path_with) if path_with else None
    summary_no = parse_summary(path_no) if path_no else None

    rows, max_time = build_condition_rows(summary_with, summary_no)
    case_label = get_case_label(run_name, case_id)

    svg_path = out_dir / f"{queue}__{run_name}__case_{case_id}.svg"
    subtitle = extract_args_subtitle(summary_with or summary_no)

    chart = ConditionChart(
        queue=queue,
        run_name=run_name,
        case_id=case_id,
        case_label=case_label,
        rows=rows,
        max_time=max_time,
        svg_path=svg_path,
    )
    svg = render_condition_svg(chart, subtitle)
    svg_path.write_text(svg, encoding="utf-8")
    return chart


def write_summary_csv(out_dir: Path, charts: List[ConditionChart]) -> Path:
    csv_path = out_dir / "overlap_summary.csv"
    header = [
        "queue",
        "run_name",
        "case_id",
        "case_label",
        "section",
        "bench_with_compute_s",
        "bench_no_midcomm_s",
        "compute_s",
        "fixed_mock_window_no_s",
        "fixed_mock_window_with_s",
        "comm_window_s",
        "measured_window_s",
        "ideal_s",
        "serial_s",
        "overhead_ratio",
        "overlap_ratio",
    ]
    lines = [",".join(header)]
    for chart in charts:
        for row in chart.rows:
            overhead_ratio = (
                f"{row.overhead_ratio:.6f}" if row.overhead_ratio is not None else ""
            )
            overlap_ratio = (
                f"{1.0 - row.overhead_ratio:.6f}"
                if row.overhead_ratio is not None
                else ""
            )
            ideal = max(row.compute, row.comm_window)
            serial = row.compute + row.comm_window
            lines.append(
                ",".join(
                    [
                        chart.queue,
                        chart.run_name,
                        chart.case_id,
                        chart.case_label,
                        row.label.replace(",", " "),
                        f"{row.bench_with:.6f}",
                        f"{row.bench_no:.6f}",
                        f"{row.compute:.6f}",
                        f"{row.fixed_window_no:.6f}",
                        f"{row.fixed_window_with:.6f}",
                        f"{row.comm_window:.6f}",
                        f"{row.measured_window:.6f}",
                        f"{ideal:.6f}",
                        f"{serial:.6f}",
                        overhead_ratio,
                        overlap_ratio,
                    ]
                )
            )
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path


def write_index_html(out_dir: Path, charts: List[ConditionChart]) -> Path:
    grouped: Dict[Tuple[str, str], List[ConditionChart]] = {}
    for chart in charts:
        grouped.setdefault((chart.queue, chart.run_name), []).append(chart)

    parts: List[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>COMB overhead charts</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#111827;}",
        "h1{margin-top:0;}",
        "h2{margin-top:28px;border-bottom:1px solid #e5e7eb;padding-bottom:4px;}",
        "details{margin:8px 0;}",
        "summary{cursor:pointer;font-weight:600;}",
        "img{max-width:100%;border:1px solid #e5e7eb;border-radius:6px;margin-top:6px;}",
        ".meta{color:#6b7280;font-size:13px;}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;}",
        ".card{border:1px solid #e5e7eb;border-radius:6px;padding:8px;}",
        ".card a{display:block;font-weight:600;margin-bottom:4px;}",
        "</style></head><body>",
        "<h1>COMB overhead charts</h1>",
        "<p class='meta'>paper metric: overhead ratio = "
        "(measured_window − max(comm_window, compute)) / min(comm_window, compute), "
        "with comm_window = wait-recv(no) and measured_window = mid-comm(with)+wait-recv(with). "
        "0 = perfect overlap, 1 = serialized. See <a href='README.md'>README</a>.</p>",
        f"<p><a href='overlap_summary.csv'>overlap_summary.csv</a></p>",
    ]
    for (queue, run_name), group in sorted(grouped.items()):
        parts.append(f"<h2>{escape(queue)} / {escape(run_name)}</h2>")
        parts.append("<div class='grid'>")
        for chart in sorted(group, key=lambda c: c.case_id):
            rel = chart.svg_path.name
            ratios = [
                f"{row.label.strip()}: {row.overhead_ratio:.3f}x"
                for row in chart.rows
                if row.overhead_ratio is not None
            ]
            summary = "; ".join(ratios) if ratios else "n/a"
            parts.append("<div class='card'>")
            parts.append(
                f"<a href='{rel}'>case {chart.case_id} — {escape(chart.case_label)}</a>"
            )
            parts.append(f"<img src='{rel}' alt='{escape(rel)}'/>")
            parts.append(f"<div class='meta'>{escape(summary)}</div>")
            parts.append("</div>")
        parts.append("</div>")
    parts.append("</body></html>")
    index_path = out_dir / "index.html"
    index_path.write_text("\n".join(parts), encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=SCRIPT_DIR,
        help="directory containing comb_midcomm_omp / comb_no_midcomm_omp",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPT_DIR / "visualization_output",
        help="output directory for SVG / CSV / HTML",
    )
    args = parser.parse_args()

    root: Path = args.root
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    conditions = discover_conditions(root)
    if not conditions:
        print(f"[warn] no Comb_*_summary.csv files found under {root}")
        return 1

    charts: List[ConditionChart] = []
    for queue, run_name, case_id in conditions:
        chart = build_chart(root, out_dir, queue, run_name, case_id)
        if chart is not None:
            charts.append(chart)
            print(f"[ok] {queue}/{run_name}/case_{case_id} -> {chart.svg_path.name}")

    csv_path = write_summary_csv(out_dir, charts)
    index_path = write_index_html(out_dir, charts)

    print()
    print(f"Wrote {len(charts)} chart(s) under {out_dir}")
    print(f"  CSV:   {csv_path}")
    print(f"  HTML:  {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
