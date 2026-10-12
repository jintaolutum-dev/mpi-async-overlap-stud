#!/usr/bin/env python3
"""Summarize selected 2n2r message-size overlap results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re
from statistics import fmean

from analyze_overlap import parse_summary


MPI_NAMES = ("openmpi", "intelmpi", "intelmpi_tcp", "mpich")
CASE_GROUPS = (("01", "06"), ("00", "05"))
CASES = tuple(case for group in CASE_GROUPS for case in group)
POLICY = ("mpi", "seq", "seq", "seq")
SECTION_BEGIN = "<!-- message-overlap-summary: begin -->"
SECTION_END = "<!-- message-overlap-summary: end -->"
SPREAD_WARNING_PCT = 30.0

CONFIGURATIONS = [
    ("512 B / 256 B / 256 B", "1,600 B (1.56 KiB)", "msg_x512B_y256B_z256B", {}),
    ("1 KiB / 512 B / 512 B", "3,200 B (3.12 KiB)", "msg_x1KiB_y512B_z512B", {}),
    ("2 KiB / 768 B / 768 B", "4,800 B (4.69 KiB)", "msg_x1KiB_y768B_z768B", {"openmpi": (7, 8, 9)}),
    ("2 KiB / 1 KiB / 1 KiB", "6,400 B (6.25 KiB)", "msg_x2KiB_y1KiB_z1KiB", {"intelmpi": (5, 6, 7)}),
    ("3 KiB / 2 KiB / 2 KiB", "9,600 B (9.38 KiB)", "msg_x3KiB_y1KiB_z1KiB", {"intelmpi": (4, 5, 6)}),
    ("4 KiB / 2 KiB / 2 KiB", "12,800 B (12.50 KiB)", "msg_x4KiB_y2KiB_z2KiB", {}),
    ("5 KiB / 2 KiB / 2 KiB", "16,000 B (15.62 KiB)", "msg_x5KiB_y2KiB_z2KiB", {"intelmpi": (4, 5, 6), "mpich": (4, 5, 6)}),
    ("6 KiB / 3 KiB / 3 KiB", "19,200 B (18.75 KiB)", "msg_x6KiB_y3KiB_z3KiB", {"intelmpi": (5, 6, 7), "mpich": (5, 6, 7)}),
    ("8 KiB / 4 KiB / 4 KiB", "18,496 B (18.06 KiB)", "msg_x8KiB_y4KiB_z4KiB", {"openmpi": (11, 12), "intelmpi": (4,), "intelmpi_tcp": (4, 5, 6), "mpich": (4, 5, 6)}),
    ("16 KiB / 8 KiB / 8 KiB", "36,992 B (36.12 KiB)", "msg_x16KiB_y8KiB_z8KiB", {"openmpi": (6, 7, 8), "mpich": (2, 3, 4)}),
    ("32 KiB / 16 KiB / 16 KiB", "73,984 B (72.25 KiB)", "msg_x32KiB_y16KiB_z16KiB", {"openmpi": (11, 12, 13), "intelmpi": (7, 8, 9)}),
    ("64 KiB / 32 KiB / 32 KiB", "147,968 B (144.50 KiB)", "msg_x64KiB_y32KiB_z32KiB", {"openmpi": (2, 3, 4), "intelmpi": (4, 5, 6), "intelmpi_tcp": (2, 3, 4), "mpich": (10, 11, 12)}),
    ("128 KiB / 64 KiB / 64 KiB", "295,936 B (289.00 KiB)", "msg_x128KiB_y64KiB_z64KiB", {**{name: (2, 3, 4) for name in MPI_NAMES}, "mpich": (9, 10, 11)}),
    ("256 KiB / 128 KiB / 128 KiB", "591,872 B (578.00 KiB)", "msg_x256KiB_y128KiB_z128KiB", {"openmpi": (2, 3, 4), "intelmpi": (3, 4, 5), "intelmpi_tcp": (3, 4, 5), "mpich": (6, 7, 8)}),
    ("512 KiB / 256 KiB / 256 KiB", "1,183,744 B (1.13 MiB)", "msg_x512KiB_y256KiB_z256KiB", {**{name: (2, 3, 4) for name in MPI_NAMES}, "openmpi": (20, 21, 22)}),
    ("1.00 MiB / 512 KiB / 512 KiB", "2,367,488 B (2.26 MiB)", "msg_x1.00MiB_y512KiB_z512KiB", {name: (3, 4, 5) for name in MPI_NAMES}),
    ("1.50 MiB / 768 KiB / 768 KiB", "3,551,232 B (3.39 MiB)", "msg_x1.50MiB_y768KiB_z768KiB", {"openmpi": (5, 6, 7), "intelmpi": (5, 6, 7), "intelmpi_tcp": (3, 6, 7), "mpich": (5, 6, 7)}),
    ("2.00 MiB / 1.00 MiB / 1.00 MiB", "4,734,976 B (4.52 MiB)", "msg_x2.00MiB_y1.00MiB_z1.00MiB", {**{name: (2, 3, 4) for name in MPI_NAMES}, "openmpi": (6, 7, 8), "intelmpi": (6, 7, 8)}),
    ("2.62 MiB / 1.31 MiB / 1.31 MiB", "6,214,656 B (5.93 MiB)", "msg_x2.62MiB_y1.31MiB_z1.31MiB", {name: (2, 3, 4) for name in MPI_NAMES}),
]


def selected_runs(overrides: dict[str, tuple[int, ...]], mpi_name: str) -> tuple[int, ...]:
    return overrides.get(mpi_name, (1, 2, 3))


def resolve_run_name(root: Path, run: int) -> str:
    run_name = f"run_{run:03d}"
    if (root / "midcomm" / run_name).is_dir() and (root / "no_midcomm" / run_name).is_dir():
        return run_name

    candidates = sorted(
        path.name
        for path in (root / "midcomm").glob(f"{run_name}_*")
        if (root / "no_midcomm" / path.name).is_dir()
    )
    if len(candidates) != 1:
        raise FileNotFoundError(f"Expected one paired directory for {root}/{run_name}, found {candidates}")
    return candidates[0]


def run_overlap(base: Path, mpi_name: str, directory: str, run: int, case: str) -> float:
    root = base / mpi_name / "2n2r_c24" / directory
    run_name = resolve_run_name(root, run)
    mid_path = root / "midcomm" / run_name / f"Comb_{case}_summary.csv"
    no_path = root / "no_midcomm" / run_name / f"Comb_{case}_summary.csv"
    if not mid_path.is_file() or not no_path.is_file():
        raise FileNotFoundError(f"Missing paired summaries: {mid_path} / {no_path}")

    mid = parse_summary(mid_path).get(POLICY)
    no_mid = parse_summary(no_path).get(POLICY)
    if mid is None or no_mid is None:
        raise ValueError(f"Missing MPI seq/seq/seq block: {mpi_name}/{directory}/{run_name}/case {case}")

    compute_time = mid["mid-comm"]["average"]
    if compute_time <= 0:
        raise ValueError(f"Non-positive mid-comm time: {mid_path}")
    return (
        (no_mid["wait-recv"]["average"] - mid["wait-recv"]["average"])
        / compute_time
        * 100.0
    )


def configured_value(path: Path, option: str) -> float | None:
    match = re.search(rf"{re.escape(option)}[; ]+([^;\s]+)", path.read_text(errors="replace"))
    return float(match.group(1)) if match else None


def run_signature(base: Path, mpi_name: str, directory: str, run: int) -> tuple[float | None, ...]:
    root = base / mpi_name / "2n2r_c24" / directory
    run_name = resolve_run_name(root, run)
    mid_path = root / "midcomm" / run_name / "Comb_01_summary.csv"
    no_path = root / "no_midcomm" / run_name / "Comb_01_summary.csv"
    return (
        configured_value(mid_path, "-compute_target_us"),
        configured_value(mid_path, "-comm;cutoff"),
        configured_value(no_path, "-comm;cutoff"),
    )


def calculate(base: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for xyz, payload, directory, overrides in CONFIGURATIONS:
        for mpi_name in MPI_NAMES:
            runs = selected_runs(overrides, mpi_name)
            for case in CASES:
                values = [run_overlap(base, mpi_name, directory, run, case) for run in runs]
                reasons = []
                if max(values) - min(values) > SPREAD_WARNING_PCT:
                    reasons.append(f"run 间极差 > {SPREAD_WARNING_PCT:.0f} pp")
                if min(values) < 0.0 or max(values) > 100.0:
                    reasons.append("出现 < 0% 或 > 100%")
                if len(runs) < 3:
                    reasons.append("有效 run 少于 3 次")
                if len({run_signature(base, mpi_name, directory, run) for run in runs}) > 1:
                    reasons.append("实验参数不一致")
                rows.append(
                    {
                        "xyz": xyz,
                        "payload": payload,
                        "mpi": mpi_name,
                        "case": case,
                        "runs": ", ".join(str(run) for run in runs),
                        "min_overlap_pct": min(values),
                        "mean_overlap_pct": fmean(values),
                        "max_overlap_pct": max(values),
                        "anomaly": "yes" if reasons else "no",
                        "anomaly_reasons": "; ".join(reasons),
                    }
                )
    return rows


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def markdown_section(rows: list[dict[str, object]]) -> str:
    lookup = {(str(row["xyz"]), str(row["mpi"]), str(row["case"])): row for row in rows}
    lines = [
        SECTION_BEGIN,
        "## Case 01/06 overlap 统计",
        "",
        "统计范围为 MPI backend 的 `seq/seq/seq`。对每个 run 分别按",
        "$O_r=(T^{no}_{wait,avg}-T^{mid}_{wait,avg})/T^{mid}_{compute,avg}$ 计算 mean overlap。",
        "表中每格依次为多个独立 run 的 `min / mean / max`，单位为 `%`；",
        "因此三者反映 run 间波动，并始终满足 min <= mean <= max。",
        "`⚠` 表示该格需要复核：run 间极差大于 30 个百分点、出现 <0% 或 >100%、",
        "实验参数不一致，或有效 run 少于 3 次。标记不代表自动删除该数据。",
    ]
    for group_index, case_group in enumerate(CASE_GROUPS):
        if group_index:
            lines.extend(["", f"## Case {'/'.join(case_group)} overlap 统计"])
        for case in case_group:
            lines.extend(
                [
                    "",
                    f"### Case {case}",
                    "",
                    "| X / Y / Z 消息大小 | Payload | openmpi | intelmpi | intelmpi_tcp | mpich |",
                    "|:---|---:|---:|---:|---:|---:|",
                ]
            )
            for xyz, payload, _, _ in CONFIGURATIONS:
                cells = []
                for mpi_name in MPI_NAMES:
                    row = lookup[(xyz, mpi_name, case)]
                    warning = "⚠ " if row["anomaly"] == "yes" else ""
                    cells.append(
                        f'{warning}{row["min_overlap_pct"]:.2f} / {row["mean_overlap_pct"]:.2f} / '
                        f'{row["max_overlap_pct"]:.2f}'
                    )
                lines.append(f"| {xyz} | {payload} | " + " | ".join(cells) + " |")
    lines.extend(["", SECTION_END])
    return "\n".join(lines)


def update_markdown(path: Path, section: str) -> None:
    text = path.read_text()
    if SECTION_BEGIN in text and SECTION_END in text:
        prefix, remainder = text.split(SECTION_BEGIN, 1)
        _, suffix = remainder.split(SECTION_END, 1)
        text = prefix.rstrip() + "\n\n" + section + suffix
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    parser.add_argument("--base", type=Path, default=root / "generated" / "cm4_inter")
    parser.add_argument("--csv", type=Path, default=root / "message_size_overlap_summary.csv")
    parser.add_argument("--markdown", type=Path, default=root / "消息大小影响.md")
    args = parser.parse_args()

    rows = calculate(args.base)
    write_csv(rows, args.csv)
    update_markdown(args.markdown, markdown_section(rows))
    print(f"Wrote {len(rows)} rows to {args.csv}")
    print(f"Updated {args.markdown}")


if __name__ == "__main__":
    main()