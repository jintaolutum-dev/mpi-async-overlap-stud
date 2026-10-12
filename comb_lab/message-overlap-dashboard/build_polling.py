#!/usr/bin/env python3
"""Rebuild seq/seq/seq polling comparisons from the documented runs and raw timers."""
import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from analyze_overlap import parse_summary

BASE = ROOT.parent / 'generated/cm4_inter/intelmpi/2n2r_c24'
POLICY = ('mpi', 'seq', 'seq', 'seq')
OPENMPI_POLLING_EXCLUSIONS = {
    'msg_x128KiB_y64KiB_z64KiB': {'run_017'},
    'msg_x1.00MiB_y512KiB_z512KiB': {'run_007', 'run_009'},
}


def sample(directory, run, case, polling, mpi='intelmpi', file_case=None):
    blocks, settings = {}, {}
    for mode in ('midcomm', 'no_midcomm'):
        path = BASE.parent.parent / mpi / '2n2r_c24' / directory / mode / run / f'Comb_{file_case or case}_summary.csv'
        if not path.exists():
            return None, f'{mode}/{run}/Comb_{case}_summary.csv: missing'
        text = path.read_text()
        block = parse_summary(path).get(POLICY)
        if not block or not all(key in block for key in ('wait-recv', 'mid-comm', 'bench-comm')):
            return None, f'{mode}/{run}/Comb_{case}_summary.csv: incomplete timers'
        count = re.search(r'-compute_poll_count;([0-9]+)', text)
        if (int(count[1]) if count else 0) != (2 if polling else 0):
            raise ValueError(f'Unexpected polling count: {path}')
        settings[mode] = {key: float(re.search(pattern, text)[1]) for key, pattern in {
            'target_us': r'-compute_target_us;([0-9.]+)', 'cycles': r'-cycles;(\d+)',
            'threads': r'OMP num threads\s+(\d+)'}.items()}
        blocks[mode] = block
    mid, no = blocks['midcomm'], blocks['no_midcomm']
    a, b = settings['midcomm'], settings['no_midcomm']
    if a['cycles'] != b['cycles'] or a['threads'] != b['threads'] or b['target_us'] != 0:
        raise ValueError(f'Inconsistent paired configuration: {directory}/{run}/{case}')
    compute = mid['mid-comm']['average'] * 1e6
    if compute <= 0:
        raise ValueError(f'Nonpositive compute time: {directory}/{run}/{case}')
    wait_no, wait_mid = no['wait-recv']['average'] * 1e6, mid['wait-recv']['average'] * 1e6
    return dict(mpi=mpi, directory=directory, run=run, case=case, polling=polling,
                overlap=(wait_no-wait_mid)/compute*100, wait_no_us=wait_no,
                wait_mid_us=wait_mid, compute_us=compute, target_us=a['target_us'],
                cycles=int(a['cycles']), threads=int(a['threads']),
                bench_mid_s=mid['bench-comm']['max'],
                cycle_mid_ms=mid['bench-comm']['max'] / a['cycles'] * 1e3), None


def summarize(values, requested, missing):
    return dict(n=len(values), requested=requested, runs=[v['run'] for v in values], missing=missing,
                **{key: (mean(v[key] for v in values) if values else None)
                   for key in ('overlap', 'wait_no_us', 'wait_mid_us', 'compute_us', 'bench_mid_s', 'cycle_mid_ms')},
                min=min((v['overlap'] for v in values), default=None),
                max=max((v['overlap'] for v in values), default=None),
                target_us=sorted({v['target_us'] for v in values}),
                cycles=sorted({v['cycles'] for v in values}))


def main():
    text = (ROOT.parent / '实验记录/pollingvs(intelmpiverbs).md').read_text().split('<!-- polling-overlap-results: begin -->')[0]
    groups = {}
    for x, y, z, mode, run in re.findall(
            r'cm4_inter\s+intelmpi\s+2n2r_c24\s+X ([^,]+), Y/Z ([^/]+)/([^\s]+)\s+(midcomm|no_midcomm)\s+(run_\d+)', text):
        directory = f'msg_x{x}_y{y}_z{z}'
        groups.setdefault(directory, {}).setdefault(run, set()).add(mode)
    if not groups:
        raise ValueError('No polling runs found in pollingvs.md')
    with (ROOT / 'overlap-current.csv').open() as handle:
        old = {(r['directory'], r['case']): r for r in csv.DictReader(handle) if r['mpi']=='intelmpi'}
    rows, raw = [], []
    for directory, runs in groups.items():
        if any(modes != {'midcomm', 'no_midcomm'} for modes in runs.values()):
            raise ValueError(f'Unpaired run selection: {directory}')
        for case in [f'{c:02}' for c in range(10)]:
            # Other cases use the same original run cohort as Case 01.
            selection = old.get((directory, case), old[directory, '01'])
            cohorts = {}
            for polling, names in [(False, selection['runs'].split(', ')), (True, sorted(runs))]:
                values, missing = [], []
                for run in names:
                    # User-requested exclusion, restricted to this polling case.
                    if polling and directory == 'msg_x128KiB_y64KiB_z64KiB' and case == '01' and run == 'run_025':
                        missing.append('run_025: excluded at user request (Case 01 polling only)')
                        continue
                    value, issue = sample(directory, run, case, polling)
                    if issue:
                        missing.append(issue)
                    else:
                        values.append(value)
                        raw.append(value)
                cohorts['polling' if polling else 'no_polling'] = summarize(values, names, missing)
            rows.append(dict(mpi='intelmpi', directory=directory, payload=selection['payload'], case=case, **cohorts))
    with (ROOT / 'overlap-current.csv').open() as handle:
        old = {(r['directory'], r['case']): r for r in csv.DictReader(handle) if r['mpi'] == 'openmpi'}
    for directory, start in [('msg_x512B_y256B_z256B', 27),
                             ('msg_x8KiB_y4KiB_z4KiB', 16),
                             ('msg_x128KiB_y64KiB_z64KiB', 10),
                             ('msg_x1.00MiB_y512KiB_z512KiB', 6)]:
        for case, old_case, file_case in [('01', '01', '00'), ('02', '03', '01'),
                                           ('03', '06', '02'), ('04', '09', '03')]:
            selection = old[directory, old_case]
            cohorts = {}
            for polling, names in [(False, selection['runs'].split(', ')),
                                   (True, [f'run_{n:03d}' for n in range(start, start + 10)])]:
                values, missing = [], []
                for run in names:
                    if polling and run in OPENMPI_POLLING_EXCLUSIONS.get(directory, set()):
                        missing.append(f'{run}: excluded at user request (all four polling cases)')
                        continue
                    value, issue = sample(directory, run, case, polling, 'openmpi',
                                          file_case if polling else old_case)
                    if issue:
                        missing.append(issue)
                    else:
                        values.append(value)
                        raw.append(value)
                cohorts['polling' if polling else 'no_polling'] = summarize(values, names, missing)
            rows.append(dict(mpi='openmpi', directory=directory, payload=selection['payload'], case=case, **cohorts))
    (ROOT / 'polling-data.js').write_text('const POLLING_DATA = '+json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False)+';\n')
    with (ROOT / 'polling-runs.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader()
        writer.writerows(raw)
    print(f'Built {len(rows)} message/case comparisons, {len(raw)} run/case samples.')
    for r in rows:
        if r['case'] in ('01','06'):
            print(r['payload'], r['case'], 'old/new n:',r['no_polling']['n'],r['polling']['n'])


if __name__ == '__main__':
    main()
