#!/usr/bin/env python3
"""Generate a single-condition mockup SVG to validate the chart layout.

Condition used: cm4_inter / run_1_big_mes_inter / case 05 (async1_c4_waitall).
Sections plotted (mock + mpi, seq + omp):
  - Comm mock Mesh seq Host Buffers seq Host seq Host
  - Comm mock Mesh omp Host Buffers omp Host omp Host
  - Comm mpi  Mesh seq Host Buffers seq Host seq Host
  - Comm mpi  Mesh omp Host Buffers omp Host omp Host
"""
import re
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

ROOT = Path("/dss/dsshome1/08/ge63neh2/1_comb_run/comb_intelmpi")
CASE_FILE = "Comb_05_summary.csv"
RUN_SUBPATH = "cm4_inter/run_1_big_mes_inter"

SECTIONS = [
    ("mock seq", "Comm mock Mesh seq Host Buffers seq Host seq Host"),
    ("mock omp", "Comm mock Mesh omp Host Buffers omp Host omp Host"),
    ("mpi  seq", "Comm mpi Mesh seq Host Buffers seq Host seq Host"),
    ("mpi  omp", "Comm mpi Mesh omp Host Buffers omp Host omp Host"),
]

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
    "mid-comm":  "#f97316",  # compute highlighted in orange
    "wait-recv": "#22c55e",
    "wait-send": "#16a34a",
    "post-comm": "#a3a3a3",
}


def parse_sections(path: Path):
    lines = path.read_text(errors="ignore").splitlines()
    out: dict = {}
    current = None
    num_cycles = 1
    metric_regex = re.compile(
        r"^\s*([A-Za-z0-9_-]+)\s*,\s*\d+\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*$"
    )
    cycles_regex = re.compile(r"Num cycles\s+(\d+)")
    for line in lines:
        cm = cycles_regex.search(line)
        if cm:
            num_cycles = int(cm.group(1))
        stripped = line.strip()
        if stripped.startswith("Starting test "):
            current = stripped[len("Starting test "):]
            out[current] = {}
            continue
        if current is None:
            continue
        m = metric_regex.match(line)
        if m:
            out[current][m.group(1)] = float(m.group(2))
    return out, num_cycles


def pick(sections: dict, name: str, scale: float) -> dict:
    data = sections.get(name, {})
    return {phase: data.get(phase, 0.0) * scale for phase in PHASES}


def bench(sections: dict, name: str) -> float:
    return sections.get(name, {}).get("bench-comm", 0.0)


def compute_overlap(
    with_phases: dict,
    with_bench: float,
    without_bench: float,
) -> Optional[float]:
    compute = with_phases.get("mid-comm", 0.0)
    if compute <= 0:
        return None
    # overlap = 1 - (bench_with - bench_no) / compute
    return 1.0 - (with_bench - without_bench) / compute


def render_svg(
    title: str,
    rows: list,
    max_time: float,
    output_path: Path,
) -> None:
    left = 200
    right = 40
    top = 90
    row_height = 46
    row_gap = 18
    label_gap = 4
    plot_width = 900
    height = top + len(rows) * (row_height + row_gap) + 120

    width = left + plot_width + right
    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">')
    svg.append("<style>text { font-family: sans-serif; fill: #111827; }</style>")

    svg.append(
        f'<text x="{width / 2}" y="34" text-anchor="middle" font-size="20" '
        f'font-weight="700">{escape(title)}</text>'
    )
    svg.append(
        f'<text x="{width / 2}" y="58" text-anchor="middle" font-size="13" '
        f'fill="#4b5563">condition: cm4_inter / run_1_big_mes_inter / '
        f'case 05 async1_c4_waitall (big, cutoff=250)</text>'
    )

    # X axis
    axis_y = top + len(rows) * (row_height + row_gap) + 10
    svg.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{left + plot_width}" y2="{axis_y}" '
        f'stroke="#374151" />'
    )
    for tick in range(6):
        value = max_time * tick / 5.0
        x = left + plot_width * tick / 5.0
        svg.append(
            f'<line x1="{x}" y1="{top - 4}" x2="{x}" y2="{axis_y}" '
            f'stroke="#e5e7eb" stroke-dasharray="4 4" />'
        )
        svg.append(
            f'<text x="{x}" y="{axis_y + 18}" text-anchor="middle" '
            f'font-size="12">{value:.3f}s</text>'
        )

    # Legend
    legend_y = axis_y + 42
    legend_x = left
    for phase in PHASES:
        color = PHASE_COLORS[phase]
        svg.append(
            f'<rect x="{legend_x}" y="{legend_y}" width="14" height="14" '
            f'fill="{color}" />'
        )
        svg.append(
            f'<text x="{legend_x + 20}" y="{legend_y + 12}" font-size="12">'
            f'{escape(phase)}</text>'
        )
        legend_x += 105

    # Rows
    for index, row in enumerate(rows):
        y = top + index * (row_height + row_gap)
        label = row["label"]
        svg.append(
            f'<text x="{left - 10}" y="{y + row_height / 2 + 4}" '
            f'text-anchor="end" font-size="13" font-weight="600">'
            f'{escape(label)}</text>'
        )

        cursor_x = left
        for phase in PHASES:
            value = row["phases"].get(phase, 0.0)
            if value <= 0:
                continue
            bar_width = plot_width * value / max_time
            color = PHASE_COLORS[phase]
            svg.append(
                f'<rect x="{cursor_x}" y="{y}" width="{bar_width}" '
                f'height="{row_height}" fill="{color}" stroke="#ffffff" '
                f'stroke-width="0.5" />'
            )
            if bar_width > 34:
                svg.append(
                    f'<text x="{cursor_x + bar_width / 2}" y="{y + row_height / 2 - 2}" '
                    f'text-anchor="middle" font-size="10" fill="#111827">'
                    f'{escape(phase)}</text>'
                )
                svg.append(
                    f'<text x="{cursor_x + bar_width / 2}" y="{y + row_height / 2 + 12}" '
                    f'text-anchor="middle" font-size="10" fill="#111827">'
                    f'{value:.3f}s</text>'
                )
            cursor_x += bar_width

        total = sum(row["phases"].values())
        svg.append(
            f'<text x="{cursor_x + 8}" y="{y + row_height / 2 + 4}" '
            f'font-size="11" fill="#374151">total {total:.3f}s</text>'
        )

        note = row.get("note")
        if note:
            svg.append(
                f'<text x="{left - 10}" y="{y + row_height / 2 + 20}" '
                f'text-anchor="end" font-size="11" fill="#6b7280">'
                f'{escape(note)}</text>'
            )

    svg.append("</svg>")
    output_path.write_text("\n".join(svg), encoding="utf-8")


def main() -> None:
    mid_file = ROOT / "comb_midcomm_omp" / RUN_SUBPATH / CASE_FILE
    no_file = ROOT / "comb_no_midcomm_omp" / RUN_SUBPATH / CASE_FILE

    mid_sections, mid_cycles = parse_sections(mid_file)
    no_sections, no_cycles = parse_sections(no_file)

    rows = []
    max_time = 0.0
    for mode_label, section_name in SECTIONS:
        mid = pick(mid_sections, section_name, mid_cycles)
        no = pick(no_sections, section_name, no_cycles)
        mid_bench = bench(mid_sections, section_name)
        no_bench = bench(no_sections, section_name)
        overlap = compute_overlap(mid, mid_bench, no_bench)
        overlap_text = (
            f"overlap \u2248 {overlap * 100:.1f}% | compute {mid['mid-comm']:.3f}s | "
            f"bench with {mid_bench:.3f}s vs no {no_bench:.3f}s | "
            f"overhead {mid_bench - no_bench:+.3f}s"
            if overlap is not None
            else f"no mid-comm | bench with {mid_bench:.3f}s vs no {no_bench:.3f}s"
        )
        rows.append(
            {
                "label": f"{mode_label}\nwith compute",
                "phases": mid,
                "note": overlap_text,
            }
        )
        rows.append(
            {
                "label": f"{mode_label}\nno midcomm",
                "phases": no,
                "note": None,
            }
        )
        max_time = max(max_time, sum(mid.values()), sum(no.values()))

    render_svg(
        title="Per-phase breakdown with compute vs no_midcomm (mockup)",
        rows=rows,
        max_time=max_time * 1.12,
        output_path=ROOT / "visualization_output" / "mockup_condition_view.svg",
    )


if __name__ == "__main__":
    main()
