# Comb MPI Experiment Analysis

## Multi-node OpenMPI

This change affects OpenMPI only. Intel MPI still uses its own
`comb_intelmpi.slurm.j2` template and `srun` launcher.

The old `openmpi/4.1.7-gcc13` module was built without Slurm support. On one
node it worked because no remote rank had to be started. On multiple nodes it
fell back to SSH, but compute nodes do not permit passwordless SSH between
them, so the job hung. Use `openmpi/4.1.8-gcc13` with
`mpirun --mca plm slurm`; regenerate OpenMPI scripts after this change.

## Primary MPI Overlap Metric

The primary MPI overlap metric measures how much exposed communication time is
hidden by the `midcomm` variant.

For each paired case, compare runs with identical MPI implementation,
topology, grid size, async setting, OpenMP thread count, and wait mode:

$$
R_{overlap} = \frac{C_{no\_mid} - C_{mid}}{C_{no\_mid}}
$$

where:

$$
C = \texttt{wait-recv}
$$

- `C_no_mid` is taken from the matching `no_midcomm/Comb_XX_summary.csv`.
- `C_mid` is taken from the matching `midcomm/Comb_XX_summary.csv`.
- Use only the `Starting test Comm mpi ...` block. Do not use `Comm mock` for
	the primary metric.

The blue bar in each result chart is `Wait-recv reduction`, namely
$R_{overlap}$. The case label shows `no_midcomm/midcomm` timings:

- `Post`: average `post-send` time.
- `Wrecv`: average `wait-recv` time; this is the input to the blue metric.
- `Tmax`: maximum `bench-comm` time; this is the input to the red metric.

## Overall Overlap Gain

Use `bench-comm` as the end-to-end benchmark time. It measures the complete
benchmark loop from the initial MPI barrier to the final MPI barrier, including
physics work, communication startup, waiting, and the `mid-comm` work when it
is enabled. Do not use `test-comm`, because it is the separate correctness-test
phase.

The `mid-comm` timer records each injected-compute invocation, while
`bench-comm` covers the complete five-cycle benchmark. First compute the
per-rank injected-compute time over the whole benchmark:

$$T_{\mathrm{mid}}=\mathrm{avg}(\texttt{mid-comm})\times\frac{\mathrm{num}(\texttt{mid-comm})}{\mathrm{ranks}}$$

Then calculate the fraction of serial communication-plus-compute work removed
by overlap:

$$ G_{overall} = \frac{T^{max}_{no\_mid} + T_{mid} - T^{max}_{with\_mid}} {T^{max}_{no\_mid} + T_{mid}} $$

where:

- $T^{max}_{no\_mid}$ is the `max(s)` value of `bench-comm` in the matching
	`no_midcomm/Comb_XX_summary.csv`.

- $T^{max}_{with\_mid}$ is the `max(s)` value of `bench-comm` in the matching
	`midcomm/Comb_XX_summary.csv`.
- $T_{mid}$ is estimated from the `mid-comm` timer observed in the `midcomm`
	run. It is an in-situ estimate, not a separate standalone compute benchmark.

The red bar in each result chart is `Overall overlap gain`, namely
$G_{overall}$.

## Result Charts

Click a result to open its `Wait-recv reduction` (blue) and `Overall overlap
gain` (red) chart.

| MPI | Topology | Message size | Result chart |
| --- | --- | --- | --- |
| OpenMPI | 1 node, 2 ranks, 24 threads | small_msg | [open chart](generated/cm4_inter/openmpi/1n2r_c24/small_msg/analysis/overlap_metrics.png) |
| OpenMPI | 1 node, 2 ranks, 24 threads | medium | [open chart](generated/cm4_inter/openmpi/1n2r_c24/medium/analysis/overlap_metrics.png) |
| OpenMPI | 1 node, 2 ranks, 24 threads | large | [open chart](generated/cm4_inter/openmpi/1n2r_c24/large/analysis/overlap_metrics.png) |
| OpenMPI | 2 nodes, 2 ranks, 24 threads | small_msg | [open chart](generated/cm4_inter/openmpi/2n2r_c24/small_msg/analysis/overlap_metrics.png) |
| OpenMPI | 2 nodes, 2 ranks, 24 threads | medium | [open chart](generated/cm4_inter/openmpi/2n2r_c24/medium/analysis/overlap_metrics.png) |
| OpenMPI | 2 nodes, 2 ranks, 24 threads | large | [open chart](generated/cm4_inter/openmpi/2n2r_c24/large/analysis/overlap_metrics.png) |
| Intel MPI | 1 node, 2 ranks, 24 threads | small_msg | [open chart](generated/cm4_inter/intelmpi/1n2r_c24/small_msg/analysis/overlap_metrics.png) |
| Intel MPI | 1 node, 2 ranks, 24 threads | medium | [open chart](generated/cm4_inter/intelmpi/1n2r_c24/medium/analysis/overlap_metrics.png) |
| Intel MPI | 1 node, 2 ranks, 24 threads | large | [open chart](generated/cm4_inter/intelmpi/1n2r_c24/large/analysis/overlap_metrics.png) |
| Intel MPI | 2 nodes, 2 ranks, 24 threads | small_msg | [open chart](generated/cm4_inter/intelmpi/2n2r_c24/small_msg/analysis/overlap_metrics.png) |
| Intel MPI | 2 nodes, 2 ranks, 24 threads | medium | [open chart](generated/cm4_inter/intelmpi/2n2r_c24/medium/analysis/overlap_metrics.png) |
| Intel MPI | 2 nodes, 2 ranks, 24 threads | large | [open chart](generated/cm4_inter/intelmpi/2n2r_c24/large/analysis/overlap_metrics.png) |



