# 复测后结果（openmpi，512 B / 256 B / 256 B，runs 017–026）

统计对象为 `cm4_inter / openmpi / 2n2r_c24 / msg_x512B_y256B_z256B`，策略为 MPI backend 的 `seq/seq/seq`。
每个 run 使用 Comb summary 中的 `average` 计时列计算：

`mean overlap = (wait_recv_no_mid_avg − wait_recv_mid_avg) / mid_comm_avg × 100%`

`10-run summary` 行给出这 10 个 run mean overlap 的 `min / mean / max`。

### Case 01

| Run | Mean overlap (%) |
|:---:|---:|
| run_017 | 88.46 |
| run_018 | 88.36 |
| run_019 | 96.91 |
| run_020 | 78.86 |
| run_021 | 86.89 |
| run_022 | 86.34 |
| run_023 | 90.98 |
| run_024 | 79.34 |
| run_025 | 85.24 |
| run_026 | 87.53 |
| 10-run summary | 78.86 / 86.89 / 96.91 |

### Case 06

| Run | Mean overlap (%) |
|:---:|---:|
| run_017 | 91.53 |
| run_018 | 80.68 |
| run_019 | 88.16 |
| run_020 | 100.28 |
| run_021 | 79.60 |
| run_022 | 81.02 |
| run_023 | 86.41 |
| run_024 | 84.56 |
| run_025 | 85.74 |
| run_026 | 84.76 |
| 10-run summary | 79.60 / 86.28 / 100.28 |

本次两个 case 的实测平均插入计算时间都在 **139.52–139.78 μs**，没有出现上一批约 6.3 ms 的计算阶段均值。Case 06 的 **100.28%** 按公式原样保留，未截断。
