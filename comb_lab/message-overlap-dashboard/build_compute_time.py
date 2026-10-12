#!/usr/bin/env python3
"""Build compute-window charts from the per-run results in 计算时间vs.md."""
from pathlib import Path
import csv
import json
import re
from statistics import fmean

ROOT = Path(__file__).resolve().parent
source = ROOT.parent / '实验记录' / '计算时间vs（intelmpi).md'
text = source.read_text().split('## 逐 run 结果', 1)[1].split('## 缺失数据说明', 1)[0]
records = []
for line in text.splitlines():
    group = re.fullmatch(r'### (.+) · (0.5|2)Tcommunication', line)
    if group:
        payload, factor = group.groups()
    elif line.startswith('#### '):
        policy = line[5:]
    elif re.match(r'^\| \d{3} \|', line):
        cells = [x.strip() for x in line.split('|')[1:-1]]
        for case, value in enumerate(cells[1:]):
            records.append(dict(payload=payload, factor=factor, policy=policy,
                                run=cells[0], case=f'{case:02d}',
                                overlap=None if value == 'N/A' else float(value)))
assert len(records) == 3200
# Historical no-polling reference cohort; recompute with measured compute time.
import sys
sys.path.insert(0, str(ROOT.parent))
from analyze_overlap import parse_summary
policies = list(dict.fromkeys(r['policy'] for r in records))
payload_order = list(dict.fromkeys(r['payload'] for r in records))
with (ROOT / 'overlap-current.csv').open() as handle:
    reference = {(r['payload'], r['case']): r for r in csv.DictReader(handle)
                 if r['mpi'] == 'intelmpi' and r['payload'] in payload_order}
base = ROOT.parent / 'generated/cm4_inter/intelmpi/2n2r_c24'
reference_meta = {}
for payload in payload_order:
    for case in [f'{i:02}' for i in range(10)]:
        entry = reference.get((payload, case), reference[payload, '01'])
        for run in entry['runs'].split(', '):
            blocks, config = {}, {}
            try:
                for mode in ('midcomm', 'no_midcomm'):
                    path = base / entry['directory'] / mode / run / f'Comb_{case}_summary.csv'
                    content = path.read_text()
                    poll = re.search(r'-compute_poll_count;(\d+)', content)
                    assert not poll or int(poll[1]) == 0, path
                    config[mode] = (float(re.search(r'-compute_target_us;([\d.]+)', content)[1]),
                                    int(re.search(r'-cycles;(\d+)', content)[1]))
                    blocks[mode] = parse_summary(path)
                assert config['no_midcomm'][0] == 0 and config['midcomm'][1] == config['no_midcomm'][1]
            except OSError:
                blocks = {}
            for policy in policies:
                value = None
                try:
                    key = ('mpi', *policy.split('/'))
                    mid, no = blocks['midcomm'][key], blocks['no_midcomm'][key]
                    compute = mid['mid-comm']['average']
                    if compute > 0:
                        value = (no['wait-recv']['average'] - mid['wait-recv']['average']) / compute * 100
                except KeyError:
                    pass
                records.append(dict(payload=payload, factor='1', policy=policy, run=run,
                                    case=case, overlap=value))
                if 'midcomm' in config:
                    reference_meta.setdefault((payload, policy, case), set()).add(config['midcomm'])
# Read raw timings for every cohort; use one historical mock-corrected
# communication reference per payload/case/policy for all three factors.
from functools import lru_cache
@lru_cache(None)
def raw_blocks(directory, run, case, mode):
    path = base / directory / mode / run / f'Comb_{case}_summary.csv'
    try:
        return parse_summary(path)
    except OSError:
        return {}
for record in records:
    entry = reference.get((record['payload'], record['case']), reference[record['payload'], '01'])
    run = record['run'] if record['run'].startswith('run_') else 'run_' + record['run']
    key = ('mpi', *record['policy'].split('/'))
    record.update(hidden_us=None, compute_us=None, communication_us=None, hidden_tcomm=None)
    try:
        mid = raw_blocks(entry['directory'], run, record['case'], 'midcomm')[key]
        no_blocks = raw_blocks(entry['directory'], run, record['case'], 'no_midcomm')
        no = no_blocks[key]
        compute = mid['mid-comm']['average'] * 1e6
        hidden = (no['wait-recv']['average'] - mid['wait-recv']['average']) * 1e6
        if compute > 0:
            record.update(hidden_us=hidden, compute_us=compute, overlap=100*hidden/compute)
        if record['factor'] == '1':
            mock = no_blocks[('mock', *record['policy'].split('/'))]
            record['communication_us'] = (no['wait-recv']['average'] - mock['wait-recv']['average']) * 1e6
    except KeyError:
        pass
    if record['hidden_us'] is None:
        record['overlap'] = None
baselines = {}
for record in records:
    if record['factor'] == '1' and record['communication_us'] is not None:
        key = (record['payload'], record['case'], record['policy'])
        baselines.setdefault(key, []).append(record['communication_us'])
for record in records:
    values = baselines.get((record['payload'], '06', record['policy']), [])
    baseline = fmean(values) if values else None
    record['tcomm_us'] = baseline
    if baseline is not None and baseline > 0 and record['hidden_us'] is not None:
        record['hidden_tcomm'] = record['hidden_us'] / baseline
rows = []
for payload in dict.fromkeys(r['payload'] for r in records):
    for factor in ('0.5', '1', '2'):
        for policy in dict.fromkeys(r['policy'] for r in records):
            for case in range(10):
                selected = [r for r in records if (r['payload'], r['factor'], r['policy'], r['case']) == (payload, factor, policy, f'{case:02d}')]
                valid = [r for r in selected if r['overlap'] is not None]
                values = [r['overlap'] for r in valid]
                rows.append(dict(payload=payload, factor=factor, policy=policy, case=f'{case:02d}',
                                 n=len(valid), min=min(values) if values else None,
                                 mean=fmean(values) if values else None, max=max(values) if values else None,
                                 runs=', '.join(r['run'] for r in valid),
                                 missing=', '.join(r['run'] for r in selected if r['overlap'] is None)))
for row in rows:
    row['requested'] = row['n'] + (len(row['missing'].split(', ')) if row['missing'] else 0)
    meta = sorted(reference_meta.get((row['payload'], row['policy'], row['case']), set())) if row['factor'] == '1' else []
    row['reference_config'] = '; '.join(f'{target:g} us / {cycles} cycles' for target, cycles in meta)
for row in rows:
    selected = [v for v in records if all(v[k] == row[k] for k in ('payload', 'factor', 'policy', 'case'))]
    row['tcomm_us'] = selected[0]['tcomm_us'] if selected else None
    row['metrics'] = {}
    for metric in ('hidden_us', 'hidden_tcomm'):
        valid = [v for v in selected if v[metric] is not None]
        values = [v[metric] for v in valid]
        row['metrics'][metric] = dict(n=len(valid), min=min(values) if values else None,
            mean=fmean(values) if values else None, max=max(values) if values else None,
            runs=', '.join(v['run'] for v in valid),
            missing=', '.join(v['run'] for v in selected if v[metric] is None))
(ROOT / 'compute-time-data.js').write_text('const COMPUTE_TIME_DATA = ' + json.dumps(rows, ensure_ascii=False, allow_nan=False) + ';\n')
for filename, data in [('compute-time-summary.csv', rows), ('compute-time-runs.csv', records)]:
    with (ROOT / filename).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)

# Standalone exports for the two main cases, suitable for sharing.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharey=False)
payloads = list(dict.fromkeys(r['payload'] for r in rows))
for ax, case in zip(axes, ('01', '06')):
    right = ax.twinx()
    right.set_ylabel('Hidden Tcomm (%)')
    plotted_values = []
    for offset, factor, color in [(-0.26, '0.5', '#087f73'), (0, '1', '#0065bd'), (0.26, '2', '#e25d3f')]:
        selected = [r for r in rows if r['case'] == case and r['policy'] == 'seq/seq/seq' and r['factor'] == factor]
        means = np.array([r['mean'] for r in selected])
        low, high = np.array([r['min'] for r in selected]), np.array([r['max'] for r in selected])
        x = np.arange(4) + offset
        ax.bar(x, means, .21, color={'0.5':'#a9d5ca','1':'#a9c5e5','2':'#edc0a4'}[factor], edgecolor=color, linewidth=.5, label=f'{factor} Tcomm', zorder=3)
        hidden = [r['metrics']['hidden_tcomm']['mean']*100 if r['metrics']['hidden_tcomm']['mean'] is not None else float('nan') for r in selected]
        plotted_values.extend([v for v in list(means)+hidden if np.isfinite(v)])
        right.plot(x, hidden, color=color, linestyle='None', marker='o', markersize=5, markerfacecolor='white', markeredgecolor=color, markeredgewidth=1.3)

    for index, payload in enumerate(payloads):
        points = [next(r for r in rows if r['case'] == case and r['policy'] == 'seq/seq/seq' and r['factor'] == factor and r['payload'] == payload) for factor in ('0.5', '1', '2')]
        values = [r['metrics']['hidden_tcomm']['mean']*100 if r['metrics']['hidden_tcomm']['mean'] is not None else float('nan') for r in points]
        right.plot(np.array([-.26, 0, .26])+index, values, color='#334155', linewidth=1.4, zorder=1)
    ax.set_title(f'Case {case}')
    ax.set_xticks(range(4), payloads)
    ax.set_xlabel('Peer payload')
    ax.axhline(0, color='#68737d', lw=.8)
    ax.grid(axis='y', color='#dfe4df', zorder=0)
    lo, hi = min(0, *plotted_values), max(0, *plotted_values)
    step = 20 if hi-lo > 60 else 10 if hi-lo > 20 else 5
    lower, upper = np.floor(lo/step)*step, np.ceil((hi+step*.3)/step)*step
    for axis in (ax, right):
        axis.set_ylim(lower, upper)
        axis.set_yticks(np.arange(lower, upper+step/2, step))
    ax.set_ylabel('Overlap (%)')
axes[0].set_ylabel('Overlap (%)')
fig.legend(*axes[1].get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.5, .92), ncol=3, frameon=False, fontsize=9)
fig.suptitle('Intel MPI · cm4_inter · 2n2r_c24 · seq/seq/seq', fontsize=15)
fig.text(.5, .025, 'Bars: overlap (%) on left axis; within-group lines: hidden Tcomm (%) on right axis. Same color: same compute group.\nNormalization: measured mid-comm time. All groups: raw timings; historical targets/cycles differ.', ha='center', fontsize=9)
fig.tight_layout(rect=(0, .1, 1, .88))
for ext in ('png', 'pdf'):
    fig.savefig(ROOT / f'compute-time-overlap.{ext}', dpi=180)
print(f'Built {len(rows)} groups from {len(records)} entries; {sum(r["overlap"] is None for r in records)} missing.')
