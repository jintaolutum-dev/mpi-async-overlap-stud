#!/usr/bin/env python3
"""
MPI eager/rendezvous 环境变量设置示例
"""

print("=" * 70)
print("MPI 协议选择 - 具体环境变量设置")
print("=" * 70)
print()

# IntelMPI
print("=" * 70)
print("IntelMPI (Intel Message Passing Interface)")
print("=" * 70)
print()
print("自动协议选择（默认）:")
print("  # 不设置任何变量，用默认配置")
print()
print("Prefer Eager 模式:")
print("  export I_MPI_EAGER_THRESHOLD=4194304      # 4 MB")
print("  export I_MPI_SHM_EAGER_THRESHOLD=4194304  # 共享内存也用4MB阈值")
print()
print("Prefer Rendezvous 模式（强制禁用eager）:")
print("  export I_MPI_EAGER_THRESHOLD=1            # 1 byte")
print("  export I_MPI_SHM_EAGER_THRESHOLD=1        # 强制rendezvous")
print()
print("在脚本中运行:")
print("""
  #!/bin/bash
  export I_MPI_EAGER_THRESHOLD=1
  export I_MPI_SHM_EAGER_THRESHOLD=1
  srun -n 4 ./comb 512_512_512 -divide 2_2_1 ...
""")
print()

# OpenMPI
print("=" * 70)
print("OpenMPI (Open Source MPI)")
print("=" * 70)
print()
print("自动协议选择（默认）:")
print("  # 不设置任何变量，用默认配置")
print()
print("Prefer Eager 模式:")
print("  export OMPI_MCA_btl_vader_eager_limit=262144  # 256 KB (shared memory)")
print("  export OMPI_MCA_btl_tcp_eager_limit=262144    # 256 KB (TCP)")
print()
print("Prefer Rendezvous 模式（强制禁用eager）:")
print("  export OMPI_MCA_btl_vader_eager_limit=1       # 1 byte")
print("  export OMPI_MCA_btl_tcp_eager_limit=1         # 强制rendezvous")
print()
print("在脚本中运行:")
print("""
  #!/bin/bash
  export OMPI_MCA_btl_vader_eager_limit=1
  export OMPI_MCA_btl_tcp_eager_limit=1
  mpirun -n 4 ./comb 512_512_512 -divide 2_2_1 ...
""")
print()

# MPICH
print("=" * 70)
print("MPICH (MPI Implementation from Argonne National Lab)")
print("=" * 70)
print()
print("自动协议选择（默认）:")
print("  # 不设置任何变量，用默认配置")
print()
print("Prefer Eager 模式:")
print("  export MPIR_CVAR_CH4_OFI_EAGER_MAX_MSG_SIZE=262144  # 256 KB")
print()
print("Prefer Rendezvous 模式（强制禁用eager）:")
print("  export MPIR_CVAR_CH4_OFI_EAGER_MAX_MSG_SIZE=1       # 1 byte")
print()
print("在脚本中运行:")
print("""
  #!/bin/bash
  export MPIR_CVAR_CH4_OFI_EAGER_MAX_MSG_SIZE=1
  mpirun -n 4 ./comb 512_512_512 -divide 2_2_1 ...
""")
print()

# 对比表
print("=" * 70)
print("三种MPI的阈值对比")
print("=" * 70)
print()
print("┌────────────────┬───────────────────┬──────────────────────────────┐")
print("│ MPI实现        │ Eager阈值         │ 关键环境变量                 │")
print("├────────────────┼───────────────────┼──────────────────────────────┤")
print("│ IntelMPI       │ 4 MB (4194304)    │ I_MPI_EAGER_THRESHOLD        │")
print("│                │                   │ I_MPI_SHM_EAGER_THRESHOLD    │")
print("├────────────────┼───────────────────┼──────────────────────────────┤")
print("│ OpenMPI        │ 256 KB (262144)   │ OMPI_MCA_btl_vader_limit     │")
print("│                │                   │ OMPI_MCA_btl_tcp_limit       │")
print("├────────────────┼───────────────────┼──────────────────────────────┤")
print("│ MPICH          │ 256 KB (262144)   │ MPIR_CVAR_CH4_OFI_EAGER_SIZE │")
print("└────────────────┴───────────────────┴──────────────────────────────┘")
print()

# 实际案例
print("=" * 70)
print("实际应用案例：对比small消息的三种模式")
print("=" * 70)
print()
print("假设small配置：消息大小 0.75 MB，用 IntelMPI")
print()
print("模式1 - Auto（默认）:")
print("  srun -n 4 ./comb 128_128_128 -divide 2_2_1 ...")
print("  → 用IntelMPI默认协议选择（通常混合eager和rendezvous）")
print()
print("模式2 - Prefer Eager:")
print("  export I_MPI_EAGER_THRESHOLD=4194304")
print("  export I_MPI_SHM_EAGER_THRESHOLD=4194304")
print("  srun -n 4 ./comb 128_128_128 -divide 2_2_1 ...")
print("  → 0.75 MB < 4 MB → 使用 eager 协议（低延迟）")
print()
print("模式3 - Prefer Rendezvous:")
print("  export I_MPI_EAGER_THRESHOLD=1")
print("  export I_MPI_SHM_EAGER_THRESHOLD=1")
print("  srun -n 4 ./comb 128_128_128 -divide 2_2_1 ...")
print("  → 0.75 MB >= 1 byte → 强制使用 rendezvous（用来对比性能）")
print()
