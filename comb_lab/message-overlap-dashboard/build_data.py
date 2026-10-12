#!/usr/bin/env python3
"""Build dashboard data from the original run table and overriding retest sections."""
import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from analyze_overlap import parse_summary
from summarize_message_overlap import CONFIGURATIONS, MPI_NAMES, resolve_run_name

CASES = {"01": ("wait_all", 24), "03": ("test_all", 24),
         "06": ("wait_all", 23), "09": ("test_all", 23)}
PAIRS = {"COMPARISON0106_DATA": ("01", "06"), "COMPARISON_DATA": ("06", "09"), "COMPARISON03_DATA": ("03", "06"),
         "COMPARISON01_DATA": ("01", "03"), "COMPARISON0309_DATA": ("03", "09")}
BASE = ROOT.parent / "generated/cm4_inter"

# User-requested sensitivity exclusion, limited to this seq-policy case.
CASE_EXCLUSIONS = {("mpich", "msg_x1KiB_y512B_z512B", "06"): {"run_006", "run_014"}}


def selections(text):
    configs = {xyz: (payload, directory) for xyz, payload, directory, _ in CONFIGURATIONS}
    selected = {}
    for line in text.split("<!--", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 6 or cells[0] not in configs:
            continue
        payload, directory = configs[cells[0]]
        for mpi, runs in zip(MPI_NAMES, cells[2:]):
            runs = runs.split("<br>", 1)[0]
            root = BASE / mpi / "2n2r_c24" / directory
            selected[mpi, directory] = dict(mpi=mpi, directory=directory, payload=payload,
                run_names=[resolve_run_name(root, int(run.strip())) for run in runs.split(",")],
                baseline_us=None, source="original", expected={}, summaries={})
    if len(selected) != 76:
        raise ValueError("Incomplete original run table")

    # Later retest sections override the original table, preserving MPIonly suffixes.
    for block in re.split(r"(?m)(?=^#{1,2} 复测后结果)", text.split("## cm4_std", 1)[0])[1:]:
        block = re.split(r"(?m)^#{1,2} (?!复测后结果)", block, maxsplit=1)[0]
        location = re.search(r"cm4_inter / (\w+) / 2n2r_c24 / ([A-Za-z0-9_.]+)", block)
        baseline = re.search(r"baseline[^\n]*?([0-9]+\.[0-9]+) [μµ]s", block)
        if not location or not baseline:
            raise ValueError("Unrecognized retest section: " + block[:120])
        expected, summaries = {}, {}
        for case, table in re.findall(r"(?ms)^### Case (\d+)\n(.*?)(?=^### Case|\Z)", block):
            expected[case] = {name: float(value) for name, value in re.findall(
                r"(?m)^\| (run_\d+(?:_MPIonly)?) \| (-?[\d.]+) \|", table)}
            summary = re.search(r"\| (\d+)-run summary \| ([^|]+)\|", table)
            if not summary or int(summary[1]) != len(expected[case]) or not expected[case]:
                raise ValueError("Valid-run count does not match summary: " + str(location.groups()))
            summaries[case] = tuple(float(value.strip()) for value in summary[2].split("/"))
        if set(expected) != {"01", "06"} or set(expected["01"]) != set(expected["06"]):
            raise ValueError("Expected matching valid-run Case 01/06 tables: " + str(location.groups()))
        selected[location.groups()].update(run_names=list(expected["01"]), baseline_us=float(baseline[1]),
            source="retest", expected=expected, summaries=summaries)
    return sorted(selected.values(), key=lambda item: int(item["payload"].split(" B")[0].replace(",", "")))


def sample(entry, run, case, policy=("seq", "seq", "seq")):
    root = BASE / entry["mpi"] / "2n2r_c24" / entry["directory"]
    blocks = {}
    wait, threads = {"04": ("wait_all", 1), "05": ("wait_all", 12), **CASES}[case]
    for mode in ("midcomm", "no_midcomm"):
        path = root / mode / run / f"Comb_{case}_summary.csv"
        text = path.read_text()
        if (f"Wait Recv using {wait} method" not in text or
                f"Wait Send using {wait} method" not in text or
                not re.search(rf"(?m)^OMP num threads\s+{threads}\s*$", text)):
            raise ValueError(f"Unexpected case configuration: {path}")
        blocks[mode] = parse_summary(path)[("mpi", *policy)]
    mid, no = blocks["midcomm"], blocks["no_midcomm"]
    compute = mid["mid-comm"]["average"] * 1e6
    denominator = entry["baseline_us"] if entry["baseline_us"] is not None else compute
    if denominator <= 0:
        raise ValueError(f"Non-positive denominator: {root}/{run}/{case}")
    value = dict(run=run, case=case, wait_no_us=no["wait-recv"]["average"] * 1e6,
        wait_mid_us=mid["wait-recv"]["average"] * 1e6, compute_us=compute,
        denominator_us=denominator, bench_mid=mid["bench-comm"]["max"],
        cycles=int(re.search(r"-cycles;(\d+)", text)[1]))
    value["overlap"] = (value["wait_no_us"] - value["wait_mid_us"]) / denominator * 100
    if policy != ("seq", "seq", "seq"):
        value.update(pre_us=mid["pre-comm"]["average"] * 1e6,
            post_us=mid["post-comm"]["average"] * 1e6)
    expected = entry["expected"].get(case, {}).get(run) if policy == ("seq", "seq", "seq") else None
    if expected is not None and abs(value["overlap"] - expected) > 0.015:
        raise ValueError(f"Retest mismatch: {root}/{run}/{case}: {value['overlap']} vs {expected}")
    return value


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    entries = selections((ROOT.parent / "实验记录" / "消息大小影响.md").read_text())
    singles, raw = [], []
    comparisons = {name: [] for name in PAIRS}
    for entry in entries:
        meta = dict(payload=entry["payload"].split("(", 1)[1].rstrip(")"), mpi=entry["mpi"],
            directory=entry["directory"], runs=", ".join(entry["run_names"]),
            run_count=len(entry["run_names"]), source=entry["source"], baseline_us=entry["baseline_us"],
            normalization="fixed_old_baseline" if entry["baseline_us"] is not None else "measured_compute")
        samples = {case: [sample(entry, run, case) for run in entry["run_names"]] for case in CASES}
        cycle_counts = sorted({value["cycles"] for values in samples.values() for value in values})
        meta["cycles"] = ", ".join(str(count) for count in cycle_counts)
        for case, values in samples.items():
            overlaps = [value["overlap"] for value in values]
            stats = min(overlaps), mean(overlaps), max(overlaps)
            expected = entry["summaries"].get(case)
            if expected and any(abs(a - b) > 0.015 for a, b in zip(stats, expected)):
                raise ValueError(f"Retest summary mismatch: {entry['mpi']}/{entry['directory']}/{case}: {stats} vs {expected}")
            excluded = CASE_EXCLUSIONS.get((entry["mpi"], entry["directory"], case), set())
            values = [value for value in values if value["run"] not in excluded]
            samples[case] = values
            overlaps = [value["overlap"] for value in values]
            stats = min(overlaps), mean(overlaps), max(overlaps)
            case_meta = dict(meta, runs=", ".join(v["run"] for v in values), run_count=len(values))
            singles.append(dict(case_meta, case=case, min=stats[0], mean=stats[1], max=stats[2],
                anomaly=stats[0] < 0 or stats[2] > 100 or stats[2] - stats[0] > 30))
            raw.extend(dict(case_meta, **value) for value in values)
        for name, (first, second) in PAIRS.items():
            a, b = samples[first], samples[second]
            b_by_run = {value["run"]: value for value in b}
            paired = [(left, b_by_run[left["run"]]) for left in a if left["run"] in b_by_run]
            differences = [right["overlap"] - left["overlap"] for left, right in paired]
            pair_meta = dict(meta, runs=", ".join(left["run"] for left, _ in paired),
                             run_count=len(paired), first_run_count=len(a), second_run_count=len(b))
            comparisons[name].append(dict(pair_meta, **{
                first + "_overlap": mean(row["overlap"] for row in a),
                second + "_overlap": mean(row["overlap"] for row in b),
                "delta": mean(differences), "delta_min": min(differences), "delta_max": max(differences),
                "bench_change_pct": mean((right["bench_mid"] / left["bench_mid"] - 1) * 100 for left, right in paired),
            }))

    # Do not publish partial data if any raw sample or documented summary fails validation.
    datasets = dict(OVERLAP_DATA=singles, **comparisons)
    output = "".join(f"const {name} = {json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)};\n" for name, data in datasets.items())
    (ROOT / "data.js").write_text(output)
    write_csv(ROOT / "overlap-current.csv", singles)
    write_csv(ROOT / "overlap-runs-current.csv", raw)
    for name, (first, second) in PAIRS.items():
        write_csv(ROOT / f"case{first}_vs_case{second}-current.csv", comparisons[name])
    retests = [entry for entry in entries if entry["source"] == "retest"]
    print(f"Built {len(singles)} case points and {len(raw)} run/case samples; {len(retests)} retest points override original selections.")
    print("Validated all documented Case 01/06 retest rows and min/mean/max summaries against raw timings.")
    for entry in retests:
        print(f"{entry['mpi']}/{entry['directory']}: {entry['run_names'][0]}..{entry['run_names'][-1]}, baseline={entry['baseline_us']} us")


if __name__ == "__main__":
    main()
