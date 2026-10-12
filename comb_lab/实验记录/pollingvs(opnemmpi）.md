现在在这份文档里面探究polling 在openmpi下对overlap的影响。


| `8_8_8` | `1_1_1` | 1 | 1.56 KiB | 124.698
 `32_32_32` | `1_1_1` | 1 | 18.06 KiB | 345.424
| `32_32_32` | `1_1_1` | 16 | 289.00 KiB |
| `32_32_32` | `1_1_1` | 128 | 2.25 MiB |


| `8_8_8` | `1_1_1` | 1 | 1.56 KiB | 124.698

cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_027	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_027	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_028	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_028	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_029	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_029	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_030	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_030	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_031	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_031	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_032	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_032	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_033	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_033	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_034	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_034	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_035	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_035	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	midcomm	run_036	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 512B, Y/Z 256B/256B	no_midcomm	run_036



 `32_32_32` | `1_1_1` | 1 | 18.06 KiB | 345.424
    cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_016	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_016	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_017	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_017	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_018	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_018	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_019	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_019	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_020	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_020	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_021	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_021	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_022	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_022	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_023	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_023	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_024	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_024	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	midcomm	run_025	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 8KiB, Y/Z 4KiB/4KiB	no_midcomm	run_025



    | `32_32_32` | `1_1_1` | 16 | 289.00 KiB | 259.094

    	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_010	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_010	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_011	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_011	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_012	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_012	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_013	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_013	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_014	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_014	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_015	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_015	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_016	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_016	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_017	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_017	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_018	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_018	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	midcomm	run_019	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 128KiB, Y/Z 64KiB/64KiB	no_midcomm	run_019


    | `32_32_32` | `1_1_1` | 128 | 2.25 MiB |
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_006	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_006	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_007	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_007	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_008	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_008	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_009	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_009	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_010	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_010	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_011	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_011	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_012	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_012	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_013	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_013	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_014	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_014	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	midcomm	run_015	👁 📋 inter
	cm4_inter	openmpi	2n2r_c24	X 1.00MiB, Y/Z 512KiB/512KiB	no_midcomm	run_015

## Polling 2 overlap 结果（前三组）

策略：MPI backend，`seq/seq/seq`。按同编号 midcomm/no_midcomm 配对。

`overlap (%) = 100 * (wait_recv_no_avg - wait_recv_mid_avg) / mid_comm_avg`。分母为实测计算窗口时间（包含 polling 开销），不是固定通信基线。每个 case 先逐 run 计算，再取算术平均；负值及超过 100% 的值原样保留。

Case 01/02：24 计算线程、async off、wait_all/test_all；Case 03/04：23 计算线程、async on、预留 1 核、wait_all/test_all。对应输出文件分别为 Comb_00/01/02/03_summary.csv。全部 120 个配对 case 的两侧日志均正常退出，并核验 polling=2、线程数与等待方式。

### 1.56 KiB

单位：%。

| Run | Case 01 | Case 02 | Case 03 | Case 04 |
|---|---:|---:|---:|---:|
| run_027 | 90.43 | 82.99 | 107.86 | 35.21 |
| run_028 | 80.69 | 77.11 | 206.23 | 74.56 |
| run_029 | 80.09 | 90.00 | 67.93 | 152.65 |
| run_030 | 92.97 | 83.98 | 126.66 | 82.16 |
| run_031 | 70.86 | 82.48 | 47.05 | 166.33 |
| run_032 | 85.66 | 76.84 | 40.69 | 30.90 |
| run_033 | 79.70 | 79.32 | 63.99 | 174.95 |
| run_034 | 93.34 | 74.65 | 131.54 | 84.89 |
| run_035 | 93.78 | 94.08 | 48.39 | 79.31 |
| run_036 | 78.51 | 85.43 | 87.24 | 77.81 |
| 最小值 | 70.86 | 74.65 | 40.69 | 30.90 |
| 均值 | 84.60 | 82.69 | 92.76 | 95.88 |
| 最大值 | 93.78 | 94.08 | 206.23 | 174.95 |

### 18.06 KiB

单位：%。

| Run | Case 01 | Case 02 | Case 03 | Case 04 |
|---|---:|---:|---:|---:|
| run_016 | 54.55 | 77.40 | 78.66 | 85.44 |
| run_017 | 88.27 | 66.30 | 78.97 | 76.43 |
| run_018 | 75.38 | 73.95 | 115.01 | 60.56 |
| run_019 | 75.71 | 78.55 | 89.19 | 22.00 |
| run_020 | 72.11 | 65.85 | 126.55 | 164.69 |
| run_021 | 78.04 | 73.80 | 2.91 | 21.29 |
| run_022 | 74.84 | 71.61 | 16.02 | 116.90 |
| run_023 | 157.08 | 64.29 | 149.24 | 138.52 |
| run_024 | 74.98 | 75.89 | 135.17 | 84.03 |
| run_025 | 59.77 | 78.59 | 90.44 | 91.89 |
| 最小值 | 54.55 | 64.29 | 2.91 | 21.29 |
| 均值 | 81.07 | 72.62 | 88.22 | 86.18 |
| 最大值 | 157.08 | 78.59 | 149.24 | 164.69 |

### 289.00 KiB

单位：%。

| Run | Case 01 | Case 02 | Case 03 | Case 04 |
|---|---:|---:|---:|---:|
| run_010 | 10.50 | 0.06 | 19.84 | 123.37 |
| run_011 | 77.50 | 37.42 | 53.97 | 17.31 |
| run_012 | 92.01 | -76.39 | 106.65 | 12.71 |
| run_013 | 127.87 | 119.10 | 133.66 | 84.89 |
| run_014 | 60.28 | 80.47 | 35.86 | 47.69 |
| run_015 | 70.04 | -16.82 | 54.34 | 10.24 |
| run_016 | 55.61 | 81.72 | 99.24 | 82.15 |
| run_017 | 35.68 | -1.66 | -8.40 | -206.40 |(不参与dash计算)
| run_018 | 66.62 | 21.46 | -27.93 | -49.02 |
| run_019 | 77.76 | -12.09 | 37.85 | -0.05 |
| 最小值 | 10.50 | -76.39 | -27.93 | -206.40 |（不参与dash计算）
| 均值 | 67.39 | 23.33 | 50.51 | 12.29 |
| 最大值 | 127.87 | 119.10 | 133.66 | 123.37 |

## Polling 2 overlap 结果（2.26 MiB）

范围：run_006–015，MPI backend，seq/seq/seq。四个 case 对应 Comb_00–03。80 个运行日志均正常退出，已核验 polling=2、线程数与等待方式。

`overlap (%) = 100 * (wait_recv_no_avg - wait_recv_mid_avg) / mid_comm_avg`。分母为实测计算窗口时间，含 polling 开销。逐 run 计算后取算术平均；负值及超过 100% 的值原样保留。

| Run | Case 01 | Case 02 | Case 03 | Case 04 |
|---|---:|---:|---:|---:|
| run_006 | -6.59 | -41.05 | -130.38 | 86.39 |
| run_007 | 96.02 | 163.01 | -432.85 | 137.85 |(不参与dash计算)
| run_008 | 122.19 | -87.21 | 111.71 | 175.24 |
| run_009 | -60.64 | 12.92 | -245.53 | 92.92 |(不参与dash计算)
| run_010 | -7.07 | -32.08 | -75.67 | -94.08 |
| run_011 | 29.61 | 50.75 | 48.48 | -23.49 |
| run_012 | -76.53 | 21.79 | -113.36 | 120.95 |
| run_013 | -107.13 | -9.47 | -106.68 | 61.82 |
| run_014 | 76.57 | 106.10 | -97.09 | 234.73 |
| run_015 | -45.51 | -22.17 | -229.08 | -38.47 |
| 最小值 | -107.13 | -87.21 | -432.85 | -94.08 |
| 均值 | 2.09 | 16.26 | -127.04 | 75.39 |
| 最大值 | 122.19 | 163.01 | 111.71 | 234.73 |
