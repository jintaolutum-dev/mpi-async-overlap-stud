"""Scan complete cm4_std pairs; retain all values and publish an audit trail."""
import json
import re
from statistics import mean
from build_data import ROOT, write_csv
from analyze_overlap import parse_summary, actual_send_payloads


def main():
    points, raw, audit = [], [], []
    for topology in ("2n2r_c24", "4n4r_c24"):
        for mpi in ("openmpi", "intelmpi", "intelmpi_tcp", "mpich"):
            for directory in sorted((ROOT.parent / "generated/cm4_std" / mpi / topology).glob("msg_*")):
                accepted = []
                names = sorted({p.name for mode in ("midcomm", "no_midcomm")
                                for p in (directory / mode).glob("run_*") if p.is_dir()})
                for run in names:
                    try:
                        values, signatures = [], []
                        missing = [f"{mode}/{run}/Comb_{case}_summary.csv"
                                   for mode in ("midcomm", "no_midcomm") for case in ("01", "06")
                                   if not (directory / mode / run / f"Comb_{case}_summary.csv").is_file()]
                        if missing:
                            raise ValueError("Missing summaries: " + ", ".join(missing))
                        payloads = actual_send_payloads(directory / "midcomm" / run)
                        sizes = [size for rank, sends in payloads.items() for peer, size in sends if peer != rank]
                        if not sizes:
                            raise ValueError("Missing actual remote-peer payload records")
                        for case in ("01", "06"):
                            blocks = {}
                            for mode in ("midcomm", "no_midcomm"):
                                path = directory / mode / run / f"Comb_{case}_summary.csv"
                                text = path.read_text()
                                for phase in ("Recv", "Send"):
                                    if f"Wait {phase} using wait_all method" not in text:
                                        raise ValueError("Unexpected completion method")
                                threads = int(re.search(r"OMP num threads\s+(\d+)", text)[1])
                                if threads != {"01": 24, "06": 23}[case]:
                                    raise ValueError("Unexpected application thread count")
                                args = re.search(r"(?m)^Args\s+(.*)$", text)[1]
                                signatures.append(re.sub(r"-compute_target_us;[^;\s]+", "-compute_target_us;PAIRED", args))
                                blocks[mode] = parse_summary(path)[("mpi", "seq", "seq", "seq")]
                            mid, no = blocks["midcomm"], blocks["no_midcomm"]
                            compute = mid["mid-comm"]["average"] * 1e6
                            if compute <= 0:
                                raise ValueError("Nonpositive measured computation")
                            wait_mid = mid["wait-recv"]["average"] * 1e6
                            wait_no = no["wait-recv"]["average"] * 1e6
                            values.append(dict(topology=topology, mpi=mpi, directory=directory.name,
                                run=run, case=case, payload_bytes=max(sizes),
                                remote_payloads_bytes=", ".join(map(str, sorted(set(sizes)))),
                                cycles=int(re.search(r"-cycles;(\d+)", text)[1]),
                                wait_mid_us=wait_mid, wait_no_us=wait_no, compute_us=compute,
                                denominator_us=compute, overlap=(wait_no-wait_mid)/compute*100))
                        if len(set(signatures)) != 1:
                            raise ValueError("Mismatched paired command-line configuration")
                        accepted.extend(values)
                        audit.append(dict(topology=topology, mpi=mpi, directory=directory.name, run=run, status="accepted", reason=""))
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        audit.append(dict(topology=topology, mpi=mpi, directory=directory.name, run=run, status="excluded", reason=str(error)))
                raw.extend(accepted)
                for case in ("01", "06"):
                    values = [v for v in accepted if v["case"] == case]
                    if not values:
                        continue
                    sizes = {v["payload_bytes"] for v in values}
                    if len(sizes) != 1:
                        raise ValueError(f"Payload changes across runs: {directory}")
                    size = sizes.pop()
                    overlaps = [v["overlap"] for v in values]
                    points.append(dict(topology=topology, mpi=mpi, directory=directory.name, case=case,
                        payload=f"{size / (1024 if size < 1048576 else 1048576):.2f} " + ("KiB" if size < 1048576 else "MiB"),
                        payload_bytes=size, runs=", ".join(v["run"] for v in values), run_count=len(values),
                        source="complete_pairs", baseline_us=None, normalization="measured_compute",
                        cycles=", ".join(map(str, sorted({v["cycles"] for v in values}))),
                        min=min(overlaps), mean=mean(overlaps), max=max(overlaps),
                        anomaly=min(overlaps)<0 or max(overlaps)>100 or max(overlaps)-min(overlaps)>30))
    points.sort(key=lambda r: (r["topology"], r["mpi"], r["payload_bytes"], r["case"]))
    write_csv(ROOT / "std-current.csv", points)
    write_csv(ROOT / "std-runs-current.csv", raw)
    write_csv(ROOT / "std-run-audit.csv", audit)
    (ROOT / "std-data.js").write_text("const STD_DATA = " + json.dumps(points, allow_nan=False) + ";\n")
    print(f"Built {len(points)} points, {len(raw)} case/run samples; {sum(r['status']=='excluded' for r in audit)} excluded pairs (see audit).")


if __name__ == "__main__":
    main()
