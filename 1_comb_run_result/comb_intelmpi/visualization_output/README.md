# COMB visualization output

This folder contains per-condition communication breakdown charts for the
COMB benchmark runs under `comb_midcomm_omp/` (communication **with** an
injected compute kernel) and `comb_no_midcomm_omp/` (pure communication
baseline).

## Re-run visualization

You can regenerate everything directly from this subdirectory with:

```
bash run_visualize.sh
```

The wrapper script lives at `visualization_output/run_visualize.sh` and just
switches to the parent directory and runs `visualize_comb_results.py`.

## What a chart shows

One SVG per `(queue, run_name, case_id)`. Example:
`cm4_inter__run_1_big_mes_inter__case_05.svg`.

Each chart has four **sections** (horizontal groups), one per COMB test:

| label    | COMB section                                           |
|----------|--------------------------------------------------------|
| mock seq | `Comm mock Mesh seq Host Buffers seq Host seq Host`    |
| mock omp | `Comm mock Mesh omp Host Buffers omp Host omp Host`    |
| mpi  seq | `Comm mpi Mesh seq Host Buffers seq Host seq Host`     |
| mpi  omp | `Comm mpi Mesh omp Host Buffers omp Host omp Host`     |

Each section has two horizontal bars:

- **with compute** — the same section from `comb_midcomm_omp/`
  (compute injected during `mid-comm`).
- **no midcomm**   — the same section from `comb_no_midcomm_omp/`
  (no compute, i.e. pure communication baseline).

Every bar is a stack of the COMB phase averages, ordered:

```
pre-comm | post-recv | post-send | mid-comm | wait-recv | wait-send | post-comm
```

The `mid-comm` segment (orange) is where `comb_with_compute` injects the
compute kernel. In the *no midcomm* baseline this segment is absent (or
negligible).

## Time scale

COMB's per-phase CSV reports **per-call averages**. One cycle calls each
phase once per neighbour direction; `bench-comm` is the **total benchmark
wall clock**. To make bar totals comparable to `bench-comm`, every phase
value is scaled by `num_cycles` (parsed from the summary header, typically
`Num cycles 5`):

```
bar_phase_width  ∝  avg_phase_time × num_cycles
```

The text `total X.XXXs` next to each bar reports the `bench-comm` value
for that run (which should match the summed bar length up to small
rounding).

even a perfectly overlapped run is capped at `overlap = comm/compute`,
## Paper metric: overhead ratio

The main metric now follows the paper exactly. For one section we define:

```
compute         = mid_comm_with_compute × num_cycles
fixed_window    = wait_recv_mock × num_cycles
comm_window     = max(0, wait_recv_mpi_no_midcomm − wait_recv_mock_no_midcomm)
measured_window = compute + max(0, wait_recv_mpi_with_compute − wait_recv_mock_with_compute)
ideal           = max(compute, comm_window)      # perfect overlap
serialized      = compute + comm_window          # no overlap at all
overhead_ratio  = (measured_window − ideal) / (serialized − ideal)
                = (measured_window − max(compute, comm_window))
                  / min(compute, comm_window)
```

This is the paper's *overhead ratio*: how much extra time remains, relative
to the worst-case serialized overhead, but evaluated only on the overlap
window instead of the full COMB benchmark time.

Interpretation:

| overhead ratio | meaning                                                      |
|----------------|--------------------------------------------------------------|
| 0.0            | `bench_with == max(compute, comm)` — perfect overlap         |
| 1.0            | `bench_with == compute + comm` — fully serialized            |
| < 0            | better than ideal due to noise / measurement error           |
| > 1            | worse than serialized due to contention / extra slowdown     |

Here `comm_window` is not the full `bench-comm`, nor the raw `wait-recv`.
We use the part of `wait-recv` that looks like actual network waiting after
subtracting the fixed software overhead seen in the corresponding `mock`
section. For mpi rows that means:

- `mpi seq` uses `mock seq` as the fixed-overhead baseline
- `mpi omp` uses `mock omp` as the fixed-overhead baseline

Likewise, `measured_window` is the compute segment plus the residual
`wait-recv` left in the `with_compute` run after subtracting the matching
mock baseline. This matches the intuition that overlap is created between
`post-send` and `wait-recv`, and that part of `wait-recv` is only constant
software overhead rather than transferable communication time.

The denominator is `min(compute, comm_window)` — the amount of time that
could be hidden at best. Sections are paired within the same section name
(mpi↔mpi, mock↔mock, seq↔seq, omp↔omp).

For convenience, the CSV also contains:

```
overlap_ratio = 1 - overhead_ratio
```

That derived quantity is sometimes easier to read (`1` best, `0` serialized),
but the figures and captions now use the paper's `overhead_ratio` as the
primary metric.

### What to do when overlap is small because comm ≪ compute

On cm4_inter with 512³ / cutoff 250 the communication is very short
(≈0.6–1.0 s total) while the injected compute per cycle can be comparable
or even larger. In that regime there is physically very little room to
hide. Ways to get a more informative measurement:

- **Make comm dominate**: larger mesh (`-divide` more finely, larger per-rank
  size), more `-vars`, smaller `-comm cutoff` (forces more exchanges),
  more neighbours (`-periodic 1_1_1` is already on), slower fabric (this
  one is out of our control).
- **Make compute smaller**: reduce the compute workload in the
  `comb_with_compute` branch, or drop `-vars`, so that `compute ≲ comm`.
  Then even a modest fraction hidden shows up on the bar.
- **Enable async progress**: on Intel MPI set
  `I_MPI_ASYNC_PROGRESS=1` (and pin a progress thread), re-run, compare.

The chart already prints `compute` and `comm` (= `bench_no_midcomm`) per
section so you can tell at a glance which side is the bottleneck.

## Files

- `*.svg` — one chart per condition. Filename pattern:
  `{queue}__{run_name}__case_{case_id}.svg`.
- `overlap_summary.csv` — long-format table (one row per condition ×
  section) with the numbers used to draw the charts:
  `queue, run_name, case_id, case_label, section,
  bench_with_compute_s, bench_no_midcomm_s, compute_s, comm_window_s,
  fixed_mock_window_no_s, fixed_mock_window_with_s, measured_window_s,
   ideal_s, serial_s, overhead_ratio, overlap_ratio`.
- `index.html` — browsable gallery of all SVGs, grouped by
  `queue / run_name`. The meta line under each chart lists the overhead
  percentages for mock seq / mock omp / mpi seq / mpi omp.
- `mockup_condition_view.{py,svg}` — the original mockup used while
  agreeing on the layout; kept for reference.

## Regenerating

Python 3.10+ is required (`dataclasses`, `pathlib` with no extras). On
cm4 login nodes:

```bash
module load python/3.10.12-base
python /dss/dsshome1/08/ge63neh2/1_comb_run/comb_intelmpi/visualize_comb_results.py
```

Options:

- `--root PATH` (default: directory of the script) — folder that contains
  `comb_midcomm_omp/` and `comb_no_midcomm_omp/`.
- `--out PATH`  (default: `<root>/visualization_output`) — where SVG / CSV /
  HTML are written.

Re-running the script overwrites the previous SVG / CSV / HTML in place.

## Caveats

- A condition is skipped silently if **neither** variant has data. If only
  one side exists, the missing row is drawn as a grey "(not available)"
  placeholder and the ratio fields are undefined (left blank in the CSV).
- `num_cycles` is taken from the `Num cycles` header line. If the header
  changes format, the scaling will fall back to 1 and totals will look
  too short.
- The `mid-comm` phase is only meaningful for the `comb_with_compute`
  binary. In `comb_no_midcomm_omp/` it is typically 0.
- The compute amount depends on the `comb_with_compute` build and the
  cutoff / mesh size; comparisons across runs with different sizes or
  cutoffs are meaningful only inside the same run directory.
