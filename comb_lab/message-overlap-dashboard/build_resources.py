#!/usr/bin/env python3
"""Build the omp/seq/seq resource comparison from the shared run selection."""
import json
from statistics import mean
from build_data import ROOT, selections, sample, write_csv


def main():
    points, raw = [], []
    metrics = ("overlap", "wait_no_us", "wait_mid_us", "bench_mid", "pre_us", "post_us", "compute_us")
    for entry in selections((ROOT.parent / "消息大小影响.md").read_text()):
        meta = dict(mpi=entry["mpi"], payload=entry["payload"].split("(")[1].rstrip(")"),
                    directory=entry["directory"], source=entry["source"],
                    runs=", ".join(entry["run_names"]), run_count=len(entry["run_names"]),
                    baseline_us=entry["baseline_us"], policy="omp/seq/seq",
                    normalization="fixed_old_baseline" if entry["baseline_us"] is not None else "measured_compute")
        for case in ("04", "05", "06"):
            values = [sample(entry, run, case, ("omp", "seq", "seq")) for run in entry["run_names"]]
            row = dict(meta, case=case, cycles=", ".join(map(str, sorted({v["cycles"] for v in values}))))
            for metric in metrics:
                numbers = [v[metric] for v in values]
                row[metric] = mean(numbers)
                row[metric + "_min"] = min(numbers)
                row[metric + "_max"] = max(numbers)
            points.append(row)
            raw.extend(dict(meta, **value) for value in values)
    write_csv(ROOT / "resources-current.csv", points)
    write_csv(ROOT / "resources-runs-current.csv", raw)
    (ROOT / "resources-data.js").write_text("const RESOURCE_DATA = " + json.dumps(points, ensure_ascii=False, allow_nan=False) + ";\n")
    print(f"Validated and built {len(points)} resource points, {len(raw)} run/case samples.")


if __name__ == "__main__":
    main()
