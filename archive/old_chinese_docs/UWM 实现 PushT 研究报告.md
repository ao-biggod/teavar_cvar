# UWM 实现 PushT 研究报告

> 日期：2026-06-05
> 平台：AutoDL (RTX 4090)
> 目标：在 UWM 框架中复现 PushT 任务，定位与官方 Diffusion Policy 之间性能差距的来源

---

## 摘要

本研究基于 UWM 框架实现 PushT 任务，并通过一系列排查实验定位其与官方 Diffusion Policy 之间的性能差距来源。初始 UWM score 仅为 0.11；修复 agent_pos 归一化不一致以及 action normalization 与 `clip_sample=True` 不匹配的问题后，分数提升到约 0.43，说明原始低分主要来自工程问题，不能直接用于评价 UWM 方法本身。

然而，修复后 UWM/AdaLN-DiT 仍显著低于官方 DP 的约 0.95。后续实验逐步排除了 video/dynamics head、视觉编码器、模型规模以及数据/eval 协议作为主要瓶颈的可能性：去掉 video head 后 DP-only 没有显著超过 UWM joint；将 image 换成 20D keypoint 后分数仍停留在约 0.44；缩小模型不能解决目前的问题；外部正对照则显示，在相同 PushT 数据和评估协议下，小型 cross-attention Transformer 可达到 0.998。

综合来看，现有证据强烈指向：当前 UWM 在 PushT 上的 0.39～0.44 并不是 joint video/action training 概念本身的上限，而更可能是 AdaLN-DiT conditioning 在强空间几何任务上的架构瓶颈。由于外部正对照同时改变了 Transformer 实现、causal mask、EMA、LR schedule 和 inference steps 等因素，严格单变量结论仍需通过在 UWM 内部仅替换 AdaLN 为 cross-attention 的实验最终确认。

---

## 一、研究问题

用 UWM 官方代码在 PushT 上训练+评估，初始 score 仅 **0.11**，而充分训练的 Diffusion Policy 官方图像基线在 PushT 上报告约 **0.95**，绝对差距约 0.84。这个差距从哪来？

多次对比实验寻找原因：

1. 工程 bug（normalizer、采样截断）
2. 观测类型（图像 vs 低维特征）
3. 模型规模（150M 参数是否过参数化或欠参数化）
4. 视频预测头（video/dynamics loss预测未来视觉状态 是帮助还是拖累）
5. 数据/评估协议（数据是否有 bug，eval 是否公平）
6. 条件注入机制（AdaLN vs 其他方式）
7. 训练组合（EMA、LR schedule、inference steps）

我在下面的研究中逐一排查这些因素，收束到最主要的瓶颈。

---

## 二、第一阶段：修复工程 Bug

### 2.1 Bug 1：agent_pos 训练/评估归一化不一致

训练时 `PushTDataset.__getitem__` 会将 `agent_pos` 通过 MinMax 归一化到 `[-1, 1]`，但早期 `eval_pusht.py` 直接传了原始 `[0, 512]` 坐标：

```python
# 训练时（静默应用）
agent_pos = lowdim_normalizer["agent_pos"](agent_pos)  # [0,512] → [-1,1]

# 早期 eval（遗漏了归一化）
agent_pos = env_obs["agent_pos"]  # 原始 [0,512]！
```

训练时模型学到的 agent_pos 分布是 `[-1, 1]`，评估时却看到了 `[0, 512]`，范围差 250 倍。

### 2.2 Bug 2：归一化方式有误，action normalization 与 `clip_sample=True` 不匹配

`clip_sample=True` 本身不是错误——官方 DP 在 MinMax/Limits normalizer 下使用该设置是合理的。但早期实验使用 mean/std normalizer，normalized action 可能超出 `[-1, 1]`（如 `[-2.1, 2.8]`），此时 `clip_sample=True` 会截断有效动作分布到[-1,1]。在当前 UWM 实现中，关闭 `clip_sample` 后分数显著提升，因此问题更准确地说是 **action normalization 与 scheduler clipping 范围在当前实现中不匹配**，而不是 `clip_sample=True` 本身错误。

### 2.3 修复效果

```
M3 (原始 UWM joint):               0.11
  → 修复 agent_pos 归一化:         ~0.19
  → 修复 clip_sample=False:        0.42-0.43
= M4 (UWM joint C, 其中 C 为配置编号：归一化 agent_pos + clip_sample=False):  0.434
```

**结论：原始 0.11 主要是工程问题，不能用于评价 UWM 方法本身。** 但修复后的 0.43 仍然远低于 DP 官方的 0.95。

> **说明**：后续出现的 "joint C"、"DP-only C" 中的 **C** 指上述修复后的配置（归一化 agent_pos + `clip_sample=False`）。"joint" = action + video 联合训练，"DP-only" = 仅 action 扩散，无视频头。修复前的早期版本称 "joint old"。

---

## 三、第二阶段：修复后仍存在主要 Gap

修复工程问题后，使用 image 或 20D keypoint 的 UWM AdaLN-DiT 系列主要稳定在 0.39～0.44 范围；5D compact state 表现更低（约 0.18），说明输入表达本身也会影响上限：

| ID | 模型 | 架构 | 参数量 | 观测 | 条件机制 | 关键差异 | Score |
|:--:|------|------|:---:|------|------|------|:---:|
| M4 | UWM joint C | AdaLN-DiT 12L/768E | 150M | 图像 + agent_pos | AdaLN | 动作+视频联合 | 0.434 |
| M5 | DP-only C | AdaLN-DiT 12L/768E | 150M | 图像 + agent_pos | AdaLN | 去掉视频头 | 0.391 |
| M6 | DP-only + EMA | AdaLN-DiT 12L/768E | 150M | 图像 + agent_pos | AdaLN | M5 + EMA 0.9999 | 0.397 |
| M7 | UWM-DP-KP baseline | AdaLN-DiT 12L/768E | 150M | 20D keypoint | AdaLN | 同 AdaLN-DiT action backbone，观测换为 20D keypoint | 0.442 |
| M8 | UWM-DP-KP small | AdaLN-DiT **6L/256E** | 11M | 20D keypoint | AdaLN | M7 缩到 6 层 | 0.389 |
| M9 | UWM obstoken hybrid | AdaLN-DiT 12L/768E | 150M | 20D keypoint | AdaLN + obs-token | M7 叠加 obs token | 0.367 |
| M13 | 5D state baseline early | AdaLN-DiT 12L/768E | 150M | 5D state | AdaLN | 早期有 bug | 0.092 |
| M14 | B1 (meanstd, noclip) | AdaLN-DiT 12L/768E | 150M | 5D state | AdaLN | 修复 normalizer | 0.186 |
| M15 | B2 (minmax, clip) | AdaLN-DiT 12L/768E | 150M | 5D state | AdaLN | minmax norm | 0.186 |

注：DP-only C，非官方的Diffusion policy，结构与UWM相同

> **评分**：M4-M6 来自确定性 paired eval（50 个共同种子 100000-100049，`deterministic_paired_eval.py`），以保证同种子下严格可比。M7-M15 来自各实验独立的 50-episode eval，主要用于趋势比较。早期非确定性 eval 中 M4 为 0.418、M5 为 0.358，差异源自种子集合和 eval 脚本不同。

DP 官方 UNet 基线作为参照：

| ID | 模型 | 架构 | 参数量 | 条件机制 | 训练量/来源 | Score | 用途 |
|:--:|------|------|:---:|------|------|:---:|------|
| M1 | **自训 DP UNet** | ConditionalUnet1D | 252M | FiLM | 本地训练 50 epoch | 0.726 | 本地复现参照 |
| M2 | **官方 DP UNet** | ConditionalUnet1D | 252M | FiLM | 官方完整 3050 epoch / 论文报告 | 0.949 | 官方上限参照 |

> M1 说明本地 DP pipeline 和 PushT 环境可以正常训练到较高分；M2 用作官方 DP 充分训练后的性能上限参照。两者训练量不同，不应被解释为同一 checkpoint 的 eval 差异。

**此时问题为：为什么 UWM 在 PushT 上稳定卡在 0.4 左右，而 DP 官方架构可达 0.95？**

---

## 四、第三阶段：逐个排除常见因素

### 4.1 Video/Dynamics Head 在当前条件下是中性

```
UWM joint C (M4):  0.434  ─┐
DP-only C   (M5):  0.391  ─┘  差异 0.043，paired t-test p=0.40，不显著
```

去掉视频预测头后分数没有显著变化。**在当前 AdaLN 条件下，video head 既没有明显帮助也没有明显拖累**。但这不排除在更好的条件机制下 video head 可能发挥正面作用。

### 4.2 视觉编码器不太可能是当前主要瓶颈

```
Image + AdaLN-DiT  (M4):  0.434  ─┐
20D keypoint + AdaLN-DiT (M7):  0.442  ─┘  差异 0.008，几乎无变化
```

虽然 image 与 20D keypoint 实验之间并非严格单变量替换，但二者都使用 AdaLN-DiT action diffusion backbone，且分数都停留在 0.4 左右。尤其是直接提供更干净的 20D keypoint 后，模型仍无法突破约 0.44，说明当前主要瓶颈不太可能只是视觉编码器，而更可能在后续 action diffusion backbone / conditioning 机制。


### 4.3 模型规模不是瓶颈

```
AdaLN-DiT 12L/768E (M7):  0.442  ─┐
AdaLN-DiT 6L/256E  (M8):  0.389  ─┘  缩小 14 倍，分数下降 0.05
```

缩小模型后分数略微下降，说明单纯的容量的减少不能解决问题；但 150M 相比 11M 只提升了约 0.05，说明在当前 AdaLN-DiT 设计下，单纯增加容量的收益很有限。

### 4.4 输入表达影响上限，但 20D keypoint 已足够

```
20D keypoint + AdaLN-DiT (M7):  0.442
5D state     + AdaLN-DiT (M15): 0.186
```

5D state `[agent_x, agent_y, block_x, block_y, block_angle]` 中的角度用单个标量表示，取值范围 `[0, 2π]`，端点在物理上同一姿态但数值相距最远，MinMax 归一化后不连续。20D keypoint 用 9 个均匀分布的空间点隐式编码位姿，避免了周期性问题，且足够支撑高分 policy（见第五章）。

---

## 五、第四阶段：外部正对照验证

为了解决"到底是数据/eval 有问题还是 UWM 架构有问题"这个关键问题，引入了两个**外部正对照**——它们不使用 UWM 的任何代码，仅使用同一数据集和同一 eval 协议：

| ID | 模型 | 代码来源 | 架构 | 参数量 | 条件机制 | Score |
|:--:|------|------|------|:---:|------|:---:|
| M10 | **B3 local DiT** | 手写 PyTorch TransformerEncoder | TransformerEncoder 6L/256E | 5M | obs-as-token | **0.722** |
| M12 | **E4 KP-TfD** | DP 官方 `TransformerForDiffusion` | TransformerDecoder 8L/256E | 5M | cross-attn + causal | **0.998** |

**定位**：M10 和 M12 不是 UWM 内部的严格单变量 ablation，而是外部正对照。它们与 UWM AdaLN-DiT 之间除了条件机制，还混入了 Transformer 类型、因果关系 mask、EMA、LR schedule、inference steps 等差异。

**价值**：它们证明了在同样的 PushT 数据和 eval 协议下，小型 Transformer policy 可以达到 0.72 ~ 0.998。因此**数据、评估流程和环境本身可以支持接近满分的结果**，当前 0.44 不能归因于数据或 eval 有问题。

**对外部对照与 UWM AdaLN-DiT 之间差异的分解**：

| 差异项 | M7 (UWM AdaLN-DiT) | M12 (E4 KP-TfD) |
|------|------|------|
| 条件注入 | AdaLN 全局调制 | cross-attention |
| Transformer 类型 | UWM AdaLNAttentionBlock | PyTorch TransformerDecoder |
| Self-attention mask | 双向 | 因果 |
| EMA | 无 | 0.9999 |
| LR schedule | constant | cosine + warmup |
| Inference steps | 10 DDIM | 100 DDPM |
| 代码实现 | UWM | Diffusion Policy 官方 |

结合 UWM 内部 image/keypoint/small/EMA 等实验（第四章），在这些混入因素中，**最强嫌疑集中在条件注入机制（AdaLN vs cross-attention）**，但严格单变量结论需要 UWM 内部替换实验进一步确认。

---

## 六、第五阶段：思考为什么当前 AdaLN-DiT conditioning 可能不适合 PushT

### 6.1 AdaLN 的工作方式

```
obs → Linear → global_feature (768D)
       │
  ┌────┴────┐
  │  scale  │  shift  │  gate  │    ← 三个全局向量
  └────┬────┘
       ↓
  out = gate ⊙ (scale ⊙ LayerNorm(x) + shift)  ← 对 layer 内所有 token 施加相同调制
```

### 6.2 PushT 需要什么样的条件信号

PushT 要求模型从观测中提取精确的空间信息——"T 块在哪里、什么角度"，然后为 16 个未来时间步各自生成对应的 `[x, y]` 目标坐标。第 1 步可能需要向左侧大幅度移动，第 8 步可能只需要微小调整方向。**每个 action token 需要的信息不同。**

### 6.3 AdaLN 的问题

1. **全局调制压缩并弱化空间信息**：所有观测被压缩为单一全局向量，T 块的空间位置和朝向被混入同一个 embedding，模型难以进行 token 级的精确信息路由，模型更难为不同 action token 路由精确的空间几何信息，例如每个未来时间步对应的移动方向和幅度。

2. **缺少 token 级别差异化**：同一层的 16 个 action token 接收完全相同的 scale/shift/gate 调制，无法为不同时间步提供不同强度的引导。

3. **视频 token 可能占用 self-attention 容量**（对 UWM joint，属假设而非结论）：9 个视频 latent token 和 8 个 register 占据了序列的 ~50%。但在 paired eval 中 UWM joint vs DP-only 差异不显著，因此这不是当前的主要实证结论。

### 6.4 为什么 obs-as-token 和 cross-attention 更好

**obs-as-token**（B3）：观测被编码为 1 个 token 直接拼入 self-attention 序列，每个 action token 通过 attention 权重从观测中提取自己需要的信息。

**cross-attention**（E3/E4）：进一步解耦——action 序列的 self-attention 管时间一致性，cross-attention 管从观测 memory 中查询空间信息。各司其职，加上 causal mask 提供了合理的物理归纳偏置。

### 6.5 在 AdaLN 上叠加 obs-token 为何无效

M9 在 AdaLN 基础上额外拼接了一个 obs token 参与 self-attention，结果从 0.442 降至 0.367。可能原因是 AdaLN 全局调制与 obs-token attention 两种条件路径相互干扰，也可能是 token 顺序/position embedding/attention mask 设计未适配。**因此下一步应该是完整替换而非简单叠加。**

---

## 七、当前结论

1. **原始 0.11 主要来自工程问题。** 修复 agent_pos 归一化不一致和 action sampling clipping 问题后，UWM AdaLN-DiT 的真实水平提升到约 0.39～0.44。

2. **在当前 AdaLN-DiT 条件机制下，video/dynamics head 没有显著帮助或拖累。** UWM joint C (0.434) 与 DP-only C (0.391) 的 paired comparison 差异不显著（paired t-test p=0.40），因此不能把当前低分简单归因于 video loss。

3. **视觉编码器不太可能是当前主要瓶颈。** Image 输入和 20D keypoint 输入在 AdaLN-DiT 下都停留在约 0.42～0.44，说明即使移除图像编码难度，模型仍无法充分利用观测信息。

4. **模型规模不是主要瓶颈。** 150M AdaLN-DiT 相比 11M AdaLN-DiT 只带来约 0.05 提升，而 5M cross-attention Transformer 可达到 0.998，说明正确的 conditioning 机制和归纳偏置比参数量更关键。

5. **外部正对照证明数据、环境和 eval 协议可以支持接近满分的 policy。** M10/M12 不是严格单变量 ablation，但它们证明当前 0.44 不能归因于 PushT 数据或评估流程本身。

6. **现有证据强烈指向 AdaLN-DiT 的条件注入方式 / action diffusion backbone 是当前主要瓶颈，其中 AdaLN global conditioning 是最值得优先验证的因素。** 最终确认需要在 UWM 框架内进行严格替换实验：保留 UWM 的 video prediction、DualTimestepEncoder、VAE latent 和 joint loss，仅将 AdaLN 条件注入替换为 cross-attention。

---

## 八、下一步最高优先级实验

将下一步拆分为两个独立阶段，分别回答"条件机制本身是否有效"和"对齐 DP recipe 后能到多高"：

**阶段 A：架构单变量实验**

- **保留**：视频预测头、VAE latent、DualTimestepEncoder、MultiViewVideoPatchifier、联合 action+dynamics loss、当前 UWM 训练 recipe
- **仅替换**：将 `AdaLNAttentionBlock` 替换为 cross-attention block（action tokens 和 video tokens 各自通过 cross-attention 查询观测 memory，cross-attention 的 obs memory 应尽量保留空间结构，例如 keypoint tokens、ResNet feature map tokens 或 VAE spatial latent tokens，而不是仅使用单一 pooled global embedding；否则该实验可能仍无法充分验证 token-level conditioning 的作用）
- **目的**：验证 conditioning 机制本身是否是瓶颈。如果阶段 A 就能显著提升，例如从 0.44 提升到 0.6 以上，则强烈支持 AdaLN conditioning 是当前主要瓶颈。

**阶段 B：Recipe 对齐实验**

- **在阶段 A 的 cross-attention 版本上**，对齐 DP 的训练食谱：EMA 0.9999、cosine LR + warmup、100 DDPM inference steps
- **目的**：验证在最优条件机制下，recipe 差异能额外贡献多少，以及 UWM joint training 的最终上限。

无论结果指向哪个方向，这两个实验能最终回答：

> 1. 在正确条件机制下，UWM 的 video/action joint training 能到什么分数？
> 2. 联合训练的 video head 是帮助、中性还是拖累？
> 3. UWM joint training 概念本身是否适合 PushT 这类强空间几何依赖的单任务场景？

---

## 附录：全部模型速查表

| ID | 名称 | 架构 | 参数量 | 观测 | 条件 | 备注 | Score |
|:--:|------|------|:---:|------|------|------|:---:|
| M1 | DP UNet 自训 | ConditionalUnet1D | 252M | 图像 | FiLM | 本地训练 50 epoch | 0.726 |
| M2 | DP UNet 官方 | ConditionalUnet1D | 252M | 图像 | FiLM | 官方完整 3050 epoch / 论文报告 | 0.949 |
| M3 | UWM joint 早期 | AdaLN-DiT 12L | 150M | 图像 | AdaLN | 有 normalizer bug | 0.112 |
| M4 | UWM joint C | AdaLN-DiT 12L | 150M | 图像 | AdaLN | 修复 bug | 0.434 |
| M5 | DP-only C | AdaLN-DiT 12L | 150M | 图像 | AdaLN | 去视频头 | 0.391 |
| M6 | DP-only + EMA | AdaLN-DiT 12L | 150M | 图像 | AdaLN | M5 + EMA | 0.397 |
| M7 | UWM-DP-KP | AdaLN-DiT 12L | 150M | keypoint | AdaLN | 同 AdaLN action backbone，换 20D keypoint | 0.442 |
| M8 | UWM-DP-KP small | AdaLN-DiT 6L | 11M | keypoint | AdaLN | 缩模型 | 0.389 |
| M9 | UWM obstoken hybrid | AdaLN-DiT 12L | 150M | keypoint | AdaLN+token | 叠 token | 0.367 |
| M10 | B3 local DiT | TransformerEncoder 6L | 5M | keypoint | obs-as-token | 外部正对照 | 0.722 |
| M12 | E4 KP-TfD | TransformerDecoder 8L | 5M | keypoint | cross-attn | 外部正对照 | 0.998 |
| M13 | 5D state baseline early | AdaLN-DiT 12L | 150M | 5D state | AdaLN | 有 bug | 0.092 |
| M14 | B1 meanstd noclip | AdaLN-DiT 12L | 150M | 5D state | AdaLN | 修 normalizer | 0.186 |
| M15 | B2 minmax clip | AdaLN-DiT 12L | 150M | 5D state | AdaLN | minmax norm | 0.186 |

> **UWM 体系内模型**（M3-M9, M13-M15）：全部使用 AdaLN-DiT backbone，最高 score 0.442。
> **外部正对照模型**（M10, M12）：不使用 UWM 代码，不含视频预测/VAE/AdaLN，仅用于验证数据与 eval 的可靠性及正确条件机制的上限。
> **DP 官方 UNet 模型**（M1, M2）：ConditionalUnet1D + FiLM，作为方法参照。
