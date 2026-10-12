# Case 04 / 05 / 06 resource comparison

Policy: MPI backend, mesh `omp`, many/few buffers `seq/seq`.
Run selection is shared with `build_data.py` and reads `消息大小影响.md`:
active retest sections override original runs; pending-review sections do not.
No old and retest runs are pooled. OpenMPI 3.39 MiB currently uses old runs
005--007, while 4.52 MiB uses the active run_019--028 retest selection
(50 cycles, MPI + Mock), excluding the historical MPI-only batch.

All three cases use wait_all. Application thread counts are 1, 12, 23.
Intel requests 1, 12, 1 progress threads; the MPICH setup requests one each.
OpenMPI reserves 1, 12, 1 CPU IDs but does not explicitly pin its TCP progress
thread to those IDs. The injected compute window remains serial.

Each run uses matched midcomm and no_midcomm summaries. Overlap uses
`(wait_no_us - wait_mid_us) / denominator_us * 100`. Active retest points
retain the documented fixed baseline; original points use the measured
computation time of the selected case and policy. This is mixed normalization,
not a newly estimated omp-policy communication baseline.

Runtime is the per-run rank maximum of bench-comm, averaged across selected
runs. Other timing metrics use summary averages, then equal-weight run means.
Tables and tooltips retain run minima/maxima without removing outliers.

Rebuild from the comb_lab directory:

```bash
venv/bin/python message-overlap-dashboard/build_resources.py
```

Outputs: `resources-data.js`, `resources-current.csv`, and
`resources-runs-current.csv`. Existing seq-policy completion views are unchanged.
