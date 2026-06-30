# ToyTE Dataset Design

> **End-to-End Two-Stage Multi-Path Traffic Engineering Toy**
> 不是 placement/knapsack toy。显式多路径、共享链路竞争、端到端 recourse。

---

## 1. 设计目标

源起：旧 `toy_instances.py` 的星型单跳拓扑退化为背包问题，无法验证多路径路由、链路竞争、场景化 recourse 等核心机制。

ToyTE 的四条设计原则：

1. **真实多路径**：每个 task-compute pair 至少 2 条 ingress 和 2 条 egress 路径
2. **链路竞争**：不同 task 的路径共享瓶颈链路，需要分流决策
3. **异构算力**：三个 compute node 有不同资源配比，placement 影响资源压力
4. **场景耦合**：网络故障和算力故障都反映到同一个端到端 service ratio z[i,s]

---

## 2. 拓扑

```
        ┌──a(2)──┬──mA(6)──┬──b(4)──┐
s1(0) ──┤        │         │        ├── t1(9)
        ├──c(3)──┤         ├──d(5)──┤
s2(1) ──┤        │  mB(7)  │        ├── t2(10)
        │        ├──┘      └──┘      │
        │  mC(8) │                   │
        └────────┘                   └──
```

| 节点 | ID | 类型 |
|:--|:--|:--|
| s1, s2 | 0, 1 | source |
| a, c, b, d | 2, 3, 4, 5 | forwarding (仅转发) |
| mA, mB, mC | 6, 7, 8 | compute-capable |
| t1, t2 | 9, 10 | destination |

24 条有向边：

```
Source:        s1→a  s1→c  s2→a  s2→c
Inter-fwd:     a→c   c→a
Ingress:       a→mA  a→mB  a→mC  c→mA  c→mB  c→mC
Egress:        mA→b  mA→d  mB→b  mB→d  mC→b  mC→d
Inter-fwd:     b→d   d→b
Dest:          b→t1  d→t1  b→t2  d→t2
```

---

## 3. 路径设计

每个 task-compute pair 有 **3 条 ingress + 3 条 egress** 路径：

```
Ingress[t=0→mA]:
  0: s1→a→mA     (直接经 a)
  1: s1→c→mA     (直接经 c)
  2: s1→a→c→mA   (a→c 迂回)

Egress[mA→t1]:
  0: mA→b→t1     (直接经 b)
  1: mA→d→t1     (直接经 d)
  2: mA→b→d→t1   (b→d 迂回)
```

### 共享瓶颈链路

| 链路 | 容量 | 用途 |
|:--|:--|:--|
| a→c, c→a | 6.0 | 两任务经迂回路径时争用 |
| b→d, d→b | 8.0 | 两任务出口迂回时争用 |

当两任务都走迂回路径（如 `s1→a→c→mB` 和 `s2→c→a→mB`），a→c 和 c→a 同时被占用，容量 6 < 流量 10+10。

---

## 4. 算力设计

3 个 compute node 的异构资源配比：

| 节点 | CPU | GPU | HBM | 特点 |
|:--|:--|:--|:--|:--|
| mA | 8 | 2 | 2 | CPU-rich, GPU-poor |
| mB | 2 | 8 | 2 | CPU-poor, GPU-rich |
| mC | 5 | 5 | 5 | balanced |

两任务算力需求：

| 任务 | CPU | GPU | HBM | 偏好 |
|:--|:--|:--|:--|:--|
| task 0 | 4 | 1 | 1 | CPU-heavy → 偏好 mA |
| task 1 | 1 | 4 | 1 | GPU-heavy → 偏好 mB |

共同放置时的瓶颈：

- 两任务都放 mA：GPU 需求 5 > 容量 2
- 两任务都放 mB：CPU 需求 5 > 容量 2
- 两任务都放 mC：CPU=GPU=5 = 容量 5（紧）

这创建了清晰的 trade-off：分开放置 (0→mA, 1→mB) 避免算力瓶颈但增加链路压力；一起放置则某资源溢出。

---

## 5. 场景设计

4 个场景：

| 场景 | 概率 | 描述 | sigma/B 影响 | C_s 影响 |
|:--|:--|:--|:--|:--|
| s0 (normal) | 0.5 | 全正常 | 全部 1.0 | 全部正常 |
| s1 (node A fail) | 0.2 | 转发节点 a 不可用 | a 所有邻接边 → 0 | 无 |
| s2 (mA fail) | 0.2 | mA 算力全失 | 无 | C_s[mA] = 0 |
| s3 (bottleneck derate) | 0.1 | a→c 降额 30% | sigma[a→c] = 0.3 | 无 |

s1 影响的边：s1→a, s2→a, a→c, c→a, a→mA, a→mB, a→mC（所有 incident to node a）。

s3 影响 a→c 从 6.0 降至 1.8，迂回路径几乎不可用。

---

## 6. 数据对象

`ToyTEData` dataclass（定义在 `toy_te_data.py`）：

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| V | list[int] | 所有节点 ID |
| E | list[tuple] | 有向边列表 |
| M | list[int] | 算力节点 |
| R | list[int] | 转发节点 |
| K | list[int] | 资源维度 [CPU=0, GPU=1, HBM=2] |
| B | dict[e → float] | 名义链路容量 |
| C_normal | dict[m → dict[k → float]] | 名义算力容量 |
| I | list[int] | 任务 ID |
| task_src, task_dst | dict[i → node] | 任务源宿 |
| b_in, b_out | dict[i → float] | 入/出站带宽需求 |
| w | dict[i → dict[k → float]] | 算力需求向量 |
| valid_assign | set[(i,m)] | 合法 placement |
| P_in, P_out | dict[(u,v) → list[path]] | 候选路径 |
| S | list[int] | 场景 ID |
| prob | dict[s → float] | 场景概率 |
| sigma | dict[e → dict[s → float]] | 链路可用率 |
| B_s | dict[e → dict[s → float]] | 场景链路容量 |
| C_s | dict[m → dict[k → dict[s → float]]] | 场景算力容量 |
| alpha_cvar | float | CVaR 置信水平 |
| routing_mode | str | "per_task_od" |

---

## 7. CVaR 符号约定

$$ \text{CVaR}_{\beta}(L^{\text{E2E}}) = \eta + \frac{1}{1-\beta} \sum_{s} p_s \cdot u_s $$

$$
\begin{aligned}
u_s &\ge L^{\text{E2E}}_s - \eta \\
u_s &\ge 0 \\
0 &\le \eta \le 1
\end{aligned}
$$

| 符号 | 代码 | 含义 |
|:--|:--|:--|
| $\beta$ | `beta_cvar` | 置信水平 (0.8) |
| $\eta$ | `alpha_cvar` | VaR 辅助变量（**不是**置信水平） |
| $u_s$ | `u_s` | 场景尾部超额 |
| $\gamma$ | `gamma_cvar` | 可选风险预算上界 |
| $L^{\text{E2E}}_s$ | `L_s` | 场景端到端损失 |

---

## 8. 验证清单

`validate_toy_te_data()` 自动检查：

1. 每个 task 有候选 compute node
2. 每个 task-compute pair 有 P_in 和 P_out
3. 每个 P_in ≥ 2 条路径
4. 每个 P_out ≥ 2 条路径
5. Ingress 路径起于 source、止于 compute node
6. Egress 路径起于 compute node、止于 destination
7. 路径中所有边存在于 E
8. 所有 B[e] > 0
9. 所有 C_normal ≥ 0
10. 所有 b_in, b_out, w ≥ 0
11. sum_s p_s = 1
12. 所有 B_s ≥ 0
13. 所有 C_s ≥ 0
14. 至少一个共享瓶颈链路
15. 至少一个算力瓶颈
16. 非 knapsack（多源、多宿、多路径、共享链路）
