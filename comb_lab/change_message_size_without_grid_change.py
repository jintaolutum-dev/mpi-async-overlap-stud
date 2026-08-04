#!/usr/bin/env python3
"""
在网格大小不变的情况下，改变消息大小的方法
"""

print("=" * 80)
print("在网格大小不变的情况下，改变消息大小的方法")
print("=" * 80)
print()

print("消息大小公式：")
print("  msg_nbytes = (local_y × local_z × ghost_x) × 8 × num_vars")
print()

print("保持网格 512×512×512 不变，可以改变的参数：")
print()

print("=" * 80)
print("方法1：改变鬼边界宽度（ghost）")
print("=" * 80)
print()
print("网格: 512×512×512, 进程: 2×2×1, 变量: 3")
print()

configs = [
    ("ghost 4×4×4", (4, 4, 4), "0.38-0.75 MB"),
    ("ghost 8×8×8", (8, 8, 8), "0.75-1.5 MB"),  # 这是当前的small
    ("ghost 16×16×16", (16, 16, 16), "1.5-3 MB"),
    ("ghost 32×32×32", (32, 32, 32), "3-6 MB"),
]

for label, ghost, sizes in configs:
    ghx, ghy, ghz = ghost
    # 2×2×1 分割 512³ 网格
    local_x, local_y, local_z = 256, 256, 512
    
    msg_x_mb = (local_y * local_z * ghx * 8 * 3) / 1024 / 1024
    msg_y_mb = (local_x * local_z * ghy * 8 * 3) / 1024 / 1024
    msg_z_mb = (local_x * local_y * ghz * 8 * 3) / 1024 / 1024
    
    print(f"{label}:")
    print(f"  命令: -divide 2_2_1 -ghost {ghx}_{ghy}_{ghz} -vars 3")
    print(f"  消息大小: X={msg_x_mb:.2f}MB, Y={msg_y_mb:.2f}MB, Z={msg_z_mb:.2f}MB")
    print()

print("=" * 80)
print("方法2：改变变量数（vars）")
print("=" * 80)
print()
print("网格: 512×512×512, 进程: 2×2×1, 鬼边界: 8×8×8")
print()

for num_vars in [1, 2, 3, 4, 6]:
    local_x, local_y, local_z = 256, 256, 512
    ghx, ghy, ghz = 8, 8, 8
    
    msg_x_mb = (local_y * local_z * ghx * 8 * num_vars) / 1024 / 1024
    msg_y_mb = (local_x * local_z * ghy * 8 * num_vars) / 1024 / 1024
    msg_z_mb = (local_x * local_y * ghz * 8 * num_vars) / 1024 / 1024
    
    print(f"vars={num_vars}:")
    print(f"  命令: -divide 2_2_1 -ghost 8_8_8 -vars {num_vars}")
    print(f"  消息大小: X={msg_x_mb:.2f}MB, Y={msg_y_mb:.2f}MB, Z={msg_z_mb:.2f}MB")
    print()

print("=" * 80)
print("方法3：改变进程数（divide）")
print("=" * 80)
print()
print("网格: 512×512×512, 鬼边界: 8×8×8, 变量: 3")
print()

divides = [
    ("1×1×1", (1, 1, 1)),
    ("2×1×1", (2, 1, 1)),
    ("2×2×1", (2, 2, 1)),
    ("2×2×2", (2, 2, 2)),
    ("4×4×1", (4, 4, 1)),
]

for label, divide in divides:
    dx, dy, dz = divide
    local_x, local_y, local_z = 512 // dx, 512 // dy, 512 // dz
    ghx, ghy, ghz = 8, 8, 8
    
    msg_x_mb = (local_y * local_z * ghx * 8 * 3) / 1024 / 1024
    msg_y_mb = (local_x * local_z * ghy * 8 * 3) / 1024 / 1024
    msg_z_mb = (local_x * local_y * ghz * 8 * 3) / 1024 / 1024
    
    print(f"{label} (rank数={dx*dy*dz}):")
    print(f"  每rank网格: {local_x}×{local_y}×{local_z}")
    print(f"  消息大小: X={msg_x_mb:.2f}MB, Y={msg_y_mb:.2f}MB, Z={msg_z_mb:.2f}MB")
    print()

print("=" * 80)
print("建议的对比方案（在512³网格上）")
print("=" * 80)
print()

print("场景1: 减小消息大小（用于eager测试）")
print("  方案A: ghost 4×4×4, vars=1 → 最小化消息")
print("         结果: ~0.05-0.1 MB")
print()
print("  方案B: ghost 8×8×8, vars=1 → 小消息")
print("         结果: ~0.1-0.2 MB")
print()

print("场景2: 保持当前消息大小")
print("  当前: ghost 8×8×8, vars=3, divide 2×2×1")
print("         结果: 0.75-1.5 MB")
print()

print("场景3: 增加消息大小（用于rendezvous测试）")
print("  方案C: ghost 16×16×16, vars=3 → 较大消息")
print("         结果: ~1.5-3 MB")
print()
print("  方案D: ghost 32×32×32, vars=3 → 大消息")
print("         结果: ~3-6 MB")
print()

print("场景4: 增加rank数（减小每rank消息）")
print("  方案E: divide 4×4×1 (16 ranks) → 分割更细")
print("         结果: 消息大小↓")
print()

print("=" * 80)
print("在config中修改这些参数")
print("=" * 80)
print()
print("编辑 config/comb_cm4.yaml，修改相关部分：")
print()
print("1. 修改ghost（鬼边界）:")
print("   ghost:")
print("     small_ghost:        # 新增")
print("       size: \"512_512_512\"")
print("       ghost: \"4_4_4\"      # ← 改这里")
print("       periodic: \"1_1_1\"")
print("       vars: 3")
print()
print("2. 修改vars（变量数）:")
print("   grid:")
print("     small:")
print("       size: \"512_512_512\"")
print("       ghost: \"8_8_8\"")
print("       periodic: \"1_1_1\"")
print("       vars: 1            # ← 改这里（从3改成1）")
print()
print("3. 修改divide（进程分割）:")
print("   topology:")
print("     - name: 4rank_2d")
print("       nodes: 2")
print("       ntasks_per_node: 2")
print("       cpus_per_task: 28")
print("       divide: \"2_2_1\"    # ← 改成 \"4_4_1\" 或其他")
print()

print("=" * 80)
print("推荐：用ghost参数做对比最简单")
print("=" * 80)
print()
print("在config里增加新的grid配置：")
print()
print("""
grid:
  small_tiny:
    size: "512_512_512"
    ghost: "4_4_4"      # 最小消息
    periodic: "1_1_1"
    vars: 3
    cutoff: 250

  small:
    size: "512_512_512"
    ghost: "8_8_8"      # 当前
    periodic: "1_1_1"
    vars: 3
    cutoff: 250

  small_large:
    size: "512_512_512"
    ghost: "16_16_16"   # 较大消息
    periodic: "1_1_1"
    vars: 3
    cutoff: 250
""")
print()
print("然后在web_gui中就可以同时选择这三个grid配置！")
print()
