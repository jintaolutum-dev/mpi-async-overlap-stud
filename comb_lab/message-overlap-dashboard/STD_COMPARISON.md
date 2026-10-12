# cm4_std Case 01 and Case 06

Rebuild with `../venv/bin/python build_std.py` from this directory.
The dashboard Dataset selector switches between the existing cm4_inter data
and cm4_std / 2n2r_c24 or 4n4r_c24.

After rebuilding the singles, run `../venv/bin/python build_std_comparisons.py`
to build Case 01/03, 03/06, 03/09, 06/09 (seq/seq/seq) and the Case 04/05/06
resource comparison (omp/seq/seq). Each group starts from the selected std
run list and requires all group members to have complete paired summaries.
All members use exactly the same run intersection. Their completion methods,
application thread counts, and otherwise matching command lines are checked.
No cm4_inter exclusions apply. Resources use the same measured-computation
normalization and retain all seven existing metric options.
`std-comparison-runs-current.csv` contains the group-specific timings;
`std-comparison-audit.csv` records missing or mismatched group/run pairs.

Selection requires both cases in both midcomm/no_midcomm directories for the
same run name, the MPI seq/seq/seq block, matching command-line configurations
apart from the computation target, wait_all completion, and 24/23 application
threads for Case 01/06. Missing or invalid pairs are recorded in
`std-run-audit.csv`; completeness does not establish freedom from timing noise.
No overlap-based exclusions or cm4_inter retest baselines are applied.

Each run uses `(wait_no_us - wait_mid_us) / compute_us * 100`, with its own
measured mid-comm average as denominator. Points show equally weighted run
means and run minimum/maximum, retaining negative and above-100 values.
Per-run timings and denominators are in `std-runs-current.csv`; aggregates
are in `std-current.csv`. The x coordinate is the maximum actual remote-peer
MPI send payload found in the run's process records, excluding self sends.
For 4n4r, remote peers need not have equal payloads; the distinct sizes are
also retained in the per-run CSV. No fixed mesh-boundary line is shown.

Initial scan: 174 case points and 470 case/run samples. Intel verbs/TCP have
19 points each per case for 2n2r, MPICH has 18. For 4n4r, MPICH has 19 and
Intel verbs has 12. Open MPI and 4n4r Intel TCP have no complete pairs yet.
These counts describe the current files, not permanently rejected workloads.
