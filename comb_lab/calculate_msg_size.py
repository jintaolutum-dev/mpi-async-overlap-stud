#!/usr/bin/env python3
"""
计算comb一次isend发送的消息大小

基于代码分析：
- msg_nbytes = msg->nbytes() * num_variables
- msg->nbytes() = sum of each item's nbytes
- item nbytes = sizeof(DataT) * size
- size = 鬼边界交换的网格点数

通信的本质：rank之间交换鬼边界
"""

def calculate_message_size(grid_size, ghost, divide, periodic, num_vars=3, dtype_size=8):
    """
    计算单个isend消息的大小（考虑rank位置）
    
    Args:
        grid_size: tuple (x, y, z) - 全局网格大小
        ghost: tuple (gx, gy, gz) - 鬼边界宽度
        divide: tuple (dx, dy, dz) - 进程网格划分
        periodic: tuple (px, py, pz) - 周期性边界条件 (0=non-periodic, 1=periodic)
        num_vars: 变量数（默认3）
        dtype_size: 数据类型大小（默认8字节=double）
    
    Returns:
        各方向消息大小
    """
    
    gx, gy, gz = grid_size
    ghx, ghy, ghz = ghost
    dx, dy, dz = divide
    px, py, pz = periodic
    
    # 每个rank的局部网格大小（不含鬼边界）
    local_x = gx // dx
    local_y = gy // dy
    local_z = gz // dz
    
    print(f"全局网格: {gx} × {gy} × {gz}")
    print(f"鬼边界: {ghx} × {ghy} × {ghz}")
    print(f"进程划分: {dx} × {dy} × {dz}")
    print(f"周期性: ({px}, {py}, {pz})")
    print(f"每个rank的局部网格: {local_x} × {local_y} × {local_z}")
    print()
    
    print("=== 单个isend消息大小（按通信方向）===")
    print()
    
    # X方向通信 (YZ面)
    print("X方向通信 (与左/右相邻rank交换YZ面):")
    if dx == 1 and px == 0:
        print("  - 只有1个rank，无X方向通信 (non-periodic)")
    else:
        msg_x_size = local_y * local_z * ghx
        msg_x_bytes = msg_x_size * dtype_size * num_vars
        print(f"  - 每条消息大小: {msg_x_size} elements × 3 vars × 8 bytes")
        print(f"    = {msg_x_bytes:,} bytes ({msg_x_bytes/1024/1024:.2f} MB)")
        if px == 0:
            print(f"  - 边界rank (rank 0和{dx-1}): 只发送给一个相邻rank")
        else:
            print(f"  - 周期性: 所有rank都发送给两个相邻rank (包括wrap-around)")
    print()
    
    # Y方向通信 (XZ面)
    print("Y方向通信 (与前/后相邻rank交换XZ面):")
    if dy == 1 and py == 0:
        print("  - 只有1个rank，无Y方向通信 (non-periodic)")
    else:
        msg_y_size = local_x * local_z * ghy
        msg_y_bytes = msg_y_size * dtype_size * num_vars
        print(f"  - 每条消息大小: {msg_y_size} elements × 3 vars × 8 bytes")
        print(f"    = {msg_y_bytes:,} bytes ({msg_y_bytes/1024/1024:.2f} MB)")
        if py == 0:
            print(f"  - 边界rank (rank 0和{dy-1}): 只发送给一个相邻rank")
        else:
            print(f"  - 周期性: 所有rank都发送给两个相邻rank")
    print()
    
    # Z方向通信 (XY面)
    print("Z方向通信 (与上/下相邻rank交换XY面):")
    if dz == 1 and pz == 0:
        print("  - 只有1个rank，无Z方向通信 (non-periodic)")
    else:
        msg_z_size = local_x * local_y * ghz
        msg_z_bytes = msg_z_size * dtype_size * num_vars
        print(f"  - 每条消息大小: {msg_z_size} elements × 3 vars × 8 bytes")
        print(f"    = {msg_z_bytes:,} bytes ({msg_z_bytes/1024/1024:.2f} MB)")
        if pz == 0:
            print(f"  - 边界rank (rank 0和{dz-1}): 只发送给一个相邻rank")
        else:
            print(f"  - 周期性: 所有rank都发送给两个相邻rank")
    print()
    
    print("=== 每个rank的isend调用次数 ===")
    isends_per_rank = 0
    if dx > 1 or px: isends_per_rank += (2 if (dx > 1 or px) else 1)  # X方向
    if dy > 1 or py: isends_per_rank += (2 if (dy > 1 or py) else 1)  # Y方向
    if dz > 1 or pz: isends_per_rank += (2 if (dz > 1 or pz) else 1)  # Z方向
    print(f"  - X方向: {2 if (dx > 1 or px) else 0} isends (send left + send right)")
    print(f"  - Y方向: {2 if (dy > 1 or py) else 0} isends")
    print(f"  - Z方向: {2 if (dz > 1 or pz) else 0} isends")
    print(f"  - 总计: {isends_per_rank} isends per rank")
    print()

# 配置中的big和small
print("=" * 70)
print("BIG配置: 512×512×512网格, ghost 8×8×8, 进程网格 2×2×1, 周期性 1_1_1")
print("=" * 70)
calculate_message_size((512, 512, 512), (8, 8, 8), (2, 2, 1), (1, 1, 1))

print()
print("=" * 70)
print("SMALL配置: 128×128×128网格, ghost 4×4×4, 进程网格 2×2×1, 周期性 1_1_1")
print("=" * 70)
calculate_message_size((128, 128, 128), (4, 4, 4), (2, 2, 1), (1, 1, 1))

print()
print("=" * 70)
print("对比: 如果是Non-Periodic边界 (0_0_0) 会怎样")
print("=" * 70)
calculate_message_size((512, 512, 512), (8, 8, 8), (2, 2, 1), (0, 0, 0))

print()
print("=" * 70)
print("对比: 同一问题用 1、2、4 个rank")
print("=" * 70)
print("网格: 512×512×512, ghost: 8×8×8, 周期性: 1_1_1")
print()

configs = [
    ("1 rank", (512, 512, 512), (8, 8, 8), (1, 1, 1)),
    ("2 ranks (1×2×1)", (512, 512, 512), (8, 8, 8), (1, 2, 1)),
    ("4 ranks (2×2×1)", (512, 512, 512), (8, 8, 8), (2, 2, 1)),
]

for label, grid, ghost, divide in configs:
    gx, gy, gz = grid
    ghx, ghy, ghz = ghost
    dx, dy, dz = divide
    
    local_x = gx // dx
    local_y = gy // dy
    local_z = gz // dz
    
    msg_x_bytes = local_y * local_z * ghx * 8 * 3 / 1024 / 1024
    msg_y_bytes = local_x * local_z * ghy * 8 * 3 / 1024 / 1024
    msg_z_bytes = local_x * local_y * ghz * 8 * 3 / 1024 / 1024
    
    num_isends = 6 if (dx > 1 or dy > 1 or dz > 1) else 0
    
    print(f"{label}:")
    print(f"  进程网格: {dx}×{dy}×{dz}, 每rank局部网格: {local_x}×{local_y}×{local_z}")
    print(f"  X向消息: {msg_x_bytes:.2f} MB")
    print(f"  Y向消息: {msg_y_bytes:.2f} MB")
    print(f"  Z向消息: {msg_z_bytes:.2f} MB")
    print(f"  每rank isend数: {num_isends}")
    print()

print()
print("=" * 70)
print("MPI协议选择: eager vs rendezvous")
print("=" * 70)
print()
print("什么是eager vs rendezvous:")
print("  - eager: 接收端提前准备好接收缓冲区（低延迟）")
print("  - rendezvous: 发送端先发request，接收端同意后才发送数据（节省内存）")
print()
print("协议选择规则: 消息大小 < 阈值 → eager | 消息大小 ≥ 阈值 → rendezvous")
print()
print("web_gui中的protocol_mode参数作用:")
print()
print("1. protocol_mode='auto':")
print("   - 不设置任何环境变量，用MPI默认配置")
print()
print("2. protocol_mode='eager' (prefer eager模式):")
print("   - IntelMPI: I_MPI_EAGER_THRESHOLD=4MB")
print("     → 消息<4MB用eager，≥4MB用rendezvous")
print("   - OpenMPI: btl_vader_eager_limit=256KB")
print("     → 消息<256KB用eager，≥256KB用rendezvous")
print("   → 倾向于用eager协议（因为阈值较高）")
print()
print("3. protocol_mode='rendezvous' (prefer rendezvous模式):")
print("   - IntelMPI: I_MPI_EAGER_THRESHOLD=1byte")
print("     → 强制所有消息用rendezvous（没有消息<1byte）")
print("   - OpenMPI: btl_vader_eager_limit=1byte")
print("     → 强制所有消息用rendezvous")
print("   → 完全禁用eager，全部用rendezvous（用来对比性能）")
print()
print("实验目的: 对比eager vs rendezvous对性能的影响")
print("  - small消息: eager可能更快（低延迟）")
print("  - large消息: rendezvous可能更快（避免内存溢出）")
