from pathlib import Path
import re, csv
OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent

def parse(path):
    text = path.read_text()
    ranks = int(re.search(r'Started rank \d+ of (\d+)', text)[1])
    result = {}; key = None
    for line in text.splitlines():
        m = re.match(r'Starting test Comm (\w+) Mesh (\w+) Host Buffers (\w+) Host (\w+) Host', line)
        if m:
            key = (m[1], m[2]+'/'+m[3]+'-'+m[4]); assert key not in result
            result[key] = {}
        m = re.match(r'([\w-]+):\s+num (\d+) avg ([\d.eE+-]+) s min ([\d.eE+-]+) s max ([\d.eE+-]+) s', line)
        if m and key:
            result[key][m[1]] = (int(m[2]), float(m[3]), float(m[5]))
    assert len(result) == 8, str(path)
    return ranks, result

rows = []
for run in range(6,16):
    for case in range(10):
        paths = [BASE/mode/('run_%03d'%run)/('Comb_%02d_summary'%case) for mode in ['no_midcomm','midcomm']]
        nr, no = parse(paths[0]); mr, mid = parse(paths[1]); assert nr == mr == 2
        for backend, strategy in no:
            a, b = no[backend,strategy], mid[backend,strategy]
            n, comp, _ = b['mid-comm']
            assert a['wait-recv'][0] == b['wait-recv'][0] == n == 200
            assert a['bench-comm'][0] == b['bench-comm'][0] == nr
            assert comp > 0
            delta = a['wait-recv'][1]-b['wait-recv'][1]
            serial = a['bench-comm'][2]+comp*n/nr
            saved = serial-b['bench-comm'][2]
            rows.append(dict(run='run_%03d'%run,case='%02d'%case,backend=backend,strategy=strategy,ranks=nr,cycles=n//nr,
                wait_no_us=a['wait-recv'][1]*1e6,wait_mid_us=b['wait-recv'][1]*1e6,compute_avg_us=comp*1e6,
                bench_no_max_ms=a['bench-comm'][2]*1e3,bench_mid_max_ms=b['bench-comm'][2]*1e3,
                serial_total_ms=serial*1e3,blue_pct=delta/comp*100,red_pct=saved/serial*100,
                overlap_total_ms=delta*n/nr*1e3,saved_total_ms=saved*1e3,
                source_no=str(paths[0]),source_mid=str(paths[1])))
assert len(rows)==800
with (OUT/'overlap.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
lines=['# run_006–run_015 overlap 计算结果','',
'依据 comb_lab/实验记录.md 的蓝柱与红柱公式；每个 run 仅与同编号的 no_midcomm/midcomm 配对，同 backend、case 和执行策略匹配。',
'','blue = (wait_no_avg - wait_mid_avg) / mid_comm_avg × 100%',
'','serial_total = bench_no_max + mid_comm_avg × mid_comm_num / ranks',
'','red = (serial_total - bench_mid_max) / serial_total × 100%',
'','输入为 Comb_*_summary（明确标注秒、num/avg/min/max）。所有 800 组均为 2 ranks × 100 cycles；bench-comm 的 num 为 2。保留负值和超过 100% 的值，不截断。Mock 的非零值作为框架/测量波动参照。',
'','CSV 包含原始均值、bench 最大值、串行基线、全部 cycles 的隐藏等待量及 saved 时间，以及输入文件路径。',
'','## MPI Case 01 / 06 概览','', '每格为蓝柱 % / 红柱 %；策略表示 Mesh / 两种 Buffer 执行策略。','',
'| Run | Case | omp/omp-omp | omp/omp-seq | omp/seq-seq | seq/seq-seq |','|---|---|---:|---:|---:|---:|']
strategies=['omp/omp-omp','omp/omp-seq','omp/seq-seq','seq/seq-seq']
for run in range(6,16):
    for case in ['01','06']:
        subset={r['strategy']:r for r in rows if r['run']=='run_%03d'%run and r['case']==case and r['backend']=='mpi'}
        lines.append('| run_%03d | %s | '%(run,case)+' | '.join('%.2f / %.2f'%(subset[s]['blue_pct'],subset[s]['red_pct']) for s in strategies)+' |')
for run in range(6,16):
    lines += ['', '## run_%03d 全部结果'%run,'','| Case | Backend | Strategy | wait no (μs) | wait mid (μs) | compute (μs) | Blue (%) | Red (%) |','|---|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['run']=='run_%03d'%run:
            lines.append('| {case} | {backend} | {strategy} | {wait_no_us:.3f} | {wait_mid_us:.3f} | {compute_avg_us:.3f} | {blue_pct:.2f} | {red_pct:.2f} |'.format(**r))
(OUT/'overlap.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines[:36]))
print('Validated and wrote',len(rows),'rows to',OUT)
