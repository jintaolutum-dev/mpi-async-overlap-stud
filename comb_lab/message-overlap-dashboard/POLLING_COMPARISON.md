# Polling comparison

The main dashboard includes a separate Polling comparison section at
`index.html#polling-comparison`. It covers Intel MPI verbs, cm4_inter/2n2r_c24,
MPI seq/seq/seq, cases 00–09 and the message sizes listed in
`../实验记录/pollingvs.md`.

Rebuild the snapshot after more experiment results arrive, from `comb_lab`:

```bash
./venv/bin/python message-overlap-dashboard/build_polling.py
```

The builder reads polling run selections from the original run list in
`pollingvs.md`, and the no-polling cohort from `overlap-current.csv`.
Cases without their own selection use the Case 01 cohort. Raw
`Comb_CC_summary.csv` files supply both groups' MPI timings. The builder verifies
poll count (2 vs absent/0), paired cycles/thread counts and zero-compute baselines.
Missing files or incomplete timer blocks are excluded per case and listed in the UI.

Both bar series use `(wait_no_avg - wait_mid_avg) / mid_compute_avg * 100`.
Each message size has side-by-side no-polling and polling bars. Bar heights are
the arithmetic means of per-run percentages; overlap whiskers show min–max.
Missing values are null and leave an empty bar position. Timing metrics
are also available. The difference column is a difference of independent cohort
means, not a paired-run effect estimate. Target compute and cycles are displayed
because the historical and polling cohorts may differ in those settings.

Generated files: `polling-data.js` and `polling-runs.csv`. The browser shows a
static snapshot; refreshing alone does not rebuild it. Existing dashboard
curves and their normalization remain as before.
