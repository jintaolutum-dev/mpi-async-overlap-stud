"""Build matched std completion and resource comparisons from selected runs."""
import csv
import json
import re
from statistics import mean
from build_data import ROOT, write_csv
from analyze_overlap import parse_summary

PAIRS = (("01", "06"), ("01", "03"), ("03", "06"), ("03", "09"), ("06", "09"))
METRICS = ("overlap", "wait_no_us", "wait_mid_us", "bench_mid", "pre_us", "post_us", "compute_us")


def read_sample(entry, run, case, mesh):
    blocks, signatures = {}, []
    for mode in ("midcomm", "no_midcomm"):
        path = ROOT.parent / "generated/cm4_std" / entry["mpi"] / entry["topology"] / entry["directory"] / mode / run / f"Comb_{case}_summary.csv"
        text = path.read_text()
        method = "test_all" if case in ("03", "09") else "wait_all"
        if any(f"Wait {phase} using {method} method" not in text for phase in ("Recv", "Send")):
            raise ValueError("Unexpected completion method")
        threads = {"01": 24, "03": 24, "04": 1, "05": 12, "06": 23, "09": 23}[case]
        if int(re.search(r"OMP num threads\s+(\d+)", text)[1]) != threads:
            raise ValueError("Unexpected thread count")
        args = re.search(r"(?m)^Args\s+(.*)$", text)[1]
        signatures.append(re.sub(r"-compute_target_us;[^;\s]+", "-compute_target_us;PAIRED", args))
        blocks[mode] = parse_summary(path)[("mpi", mesh, "seq", "seq")]
    if signatures[0] != signatures[1]:
        raise ValueError("Mismatched midcomm/no_midcomm arguments")
    mid, no = blocks["midcomm"], blocks["no_midcomm"]
    compute = mid["mid-comm"]["average"] * 1e6
    if compute <= 0:
        raise ValueError("Nonpositive computation denominator")
    value = dict(run=run, case=case, policy=f"{mesh}/seq/seq", compute_us=compute,
                 denominator_us=compute, cycles=int(re.search(r"-cycles;(\d+)", text)[1]),
                 wait_mid_us=mid["wait-recv"]["average"]*1e6,
                 wait_no_us=no["wait-recv"]["average"]*1e6,
                 bench_mid=mid["bench-comm"]["max"],
                 pre_us=mid["pre-comm"]["average"]*1e6,
                 post_us=mid["post-comm"]["average"]*1e6)
    value["overlap"] = (value["wait_no_us"]-value["wait_mid_us"])/compute*100
    # Completion methods differ by design; other command-line parameters must match.
    signature = re.sub(r"(-comm;wait_(?:recv|send);)(?:wait_all|test_all)", r"\1METHOD", signatures[0])
    return value, signature


def main():
    entries = [r for r in csv.DictReader((ROOT / "std-current.csv").open()) if r["case"] == "01"]
    comparisons, resources, raw, audit = [], [], [], []
    for entry in entries:
        for cases in (*PAIRS, ("04", "05", "06")):
            mesh = "omp" if len(cases) == 3 else "seq"
            group = "-".join(cases)
            samples = []
            for run in entry["runs"].split(", "):
                try:
                    values = [read_sample(entry, run, case, mesh) for case in cases]
                    if len({signature for _, signature in values}) != 1:
                        raise ValueError("Mismatched cross-case configuration")
                    samples.append([value for value, _ in values])
                except (OSError, ValueError, KeyError, TypeError) as error:
                    audit.append(dict(topology=entry["topology"], mpi=entry["mpi"], directory=entry["directory"], group=group, run=run, reason=str(error)))
            if not samples:
                continue
            meta = {k: entry[k] for k in ("topology", "mpi", "directory", "payload", "source", "normalization")}
            meta.update(baseline_us=None, runs=", ".join(s[0]["run"] for s in samples), run_count=len(samples),
                        cycles=", ".join(map(str, sorted({v["cycles"] for s in samples for v in s}))))
            raw.extend(dict(meta, group=group, **v) for s in samples for v in s)
            if mesh == "seq":
                first, second = cases
                delta = [s[1]["overlap"]-s[0]["overlap"] for s in samples]
                comparisons.append(dict(meta, pair=group, **{first+"_overlap": mean(s[0]["overlap"] for s in samples),
                    second+"_overlap": mean(s[1]["overlap"] for s in samples),
                    "delta": mean(delta), "delta_min": min(delta), "delta_max": max(delta),
                    "bench_change_pct": mean((s[1]["bench_mid"]/s[0]["bench_mid"]-1)*100 for s in samples)}))
            else:
                for i, case in enumerate(cases):
                    row = dict(meta, case=case, policy="omp/seq/seq")
                    for metric in METRICS:
                        values = [s[i][metric] for s in samples]
                        row.update({metric: mean(values), metric+"_min": min(values), metric+"_max": max(values)})
                    resources.append(row)
    for name, rows in (("std-comparisons-current.csv", comparisons), ("std-resources-current.csv", resources), ("std-comparison-runs-current.csv", raw)):
        with (ROOT / name).open("w", newline="") as handle:
            fields = list(dict.fromkeys(key for row in rows for key in row))
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    with (ROOT / "std-comparison-audit.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("topology", "mpi", "directory", "group", "run", "reason"))
        writer.writeheader()
        writer.writerows(audit)
    (ROOT / "std-comparisons-data.js").write_text(
        "const STD_COMPARISONS = " + json.dumps(comparisons, allow_nan=False) + ";\n" +
        "const STD_RESOURCES = " + json.dumps(resources, allow_nan=False) + ";\n")
    print(f"Built {len(comparisons)} comparison points, {len(resources)} resource points; {len(audit)} excluded group/run pairs.")


if __name__ == "__main__":
    main()
