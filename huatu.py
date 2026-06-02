import numpy as np
import matplotlib.pyplot as plt
import subprocess
import re

# ================= 配置区 =================
# 扫描的 scale 范围，步长越小曲线越平滑
scales = np.arange(1.0, 5.1, 0.4) 
topology = "B4"
beta = 0.999
demand_downscale = 2.0
k = 12

# 用于存储结果
results = []

print(f"开始批量仿真，拓扑: {topology}, Beta: {beta}...")

# 2. 循环运行仿真
for s in scales:
    print(f"正在运行 Scale = {s:.1f} ...", end="", flush=True)
    
    # 构造命令行指令
    cmd = [
        "python", "main.py", 
        "--topology", topology, 
        "--beta", str(beta), 
        "--scale", str(s), 
        "--demand_downscale", str(demand_downscale),
        "--k", str(k),
        "--iterations", "1"  # 快速出图可以用1，正式实验建议设大
    ]
    
    try:
        # 运行并捕获输出
        process = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = process.stdout
        
        # 使用正则表达式从输出中提取 "平均保障吞吐率" 的数值
        # 假设输出格式为: 平均保障吞吐率 (1-alpha): 96.6168%
        match = re.search(r"平均保障吞吐率 \(1-alpha\): ([\d\.]+)%", output)
        if match:
            val = float(match.group(1)) / 100.0  # 转为 0-1 的小数
            results.append(val)
            print(f" 完成: {val:.4f}")
        else:
            print(" 失败 (无法解析输出)")
            results.append(None)
            
    except Exception as e:
        print(f" 运行报错: {e}")
        results.append(None)

# 3. 开始绘图
plt.figure(figsize=(8, 6))

# 处理可能的 None 值
valid_scales = [scales[i] for i in range(len(results)) if results[i] is not None]
valid_results = [results[i] for i in range(len(results)) if results[i] is not None]

plt.plot(valid_scales, valid_results, marker='o', color='red', linestyle='-', linewidth=2, label='TEAVAR (Python)')

# 设置坐标轴（参考论文 Figure 7）
plt.xlabel('Demand Scale', fontsize=12)
plt.ylabel('Guaranteed Throughput (1 - α)', fontsize=12)
plt.title(f'Availability vs. Demand Scale ({topology})', fontsize=14)
plt.ylim(0, 1.05)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend()

# 保存并展示
plt.savefig('availability_reproduction.png', dpi=300)
print("\n绘图完成！图片已保存为 availability_reproduction.png")
plt.show()