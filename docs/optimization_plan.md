# DGTuner 优化方案

## 1. 核心思想

DGTuner 的优化目标可以简化为三个问题：

```text
1. 参数多少
   即需要调哪些数据库参数，删除哪些无关参数。

2. 工作负载大小
   即后续调参时是否必须每次执行完整 workload，能否筛出代表性 SQL 子集。

3. 参数取值范围
   即每个保留参数应该在多大的范围内搜索，能否进一步缩小上下界。
```

因此，整个方法可以概括为三阶段：

```text
Step 1: LLM 先验去除无关参数
Step 2: 自适应采样，同时缩小工作负载和参数数量
Step 3: 根据采样结果确定参数取值范围，并进入 BO 搜索
```

这三个阶段分别对应：

```text
参数数量    -> LLM 先验 + 采样相关性筛选
工作负载大小 -> SQL 去重 + 配置敏感性 SQL 筛选
参数取值范围 -> 根据优质采样结果和搜索历史收缩范围
```

---

## 2. 方法总览

完整流程如下：

```text
Input:
  - 原始参数空间 K
  - 原始 workload W
  - 数据库参数文档
  - workload 描述
  - 调参预算

Step 1:
  LLM 先验分析
  -> 删除明显无关参数
  -> 得到初始候选参数空间 K0

Step 2:
  自适应采样
  -> 分批采样配置
  -> 执行 workload
  -> 收集总执行时间和每条 SQL 执行时间
  -> 根据采样结果缩小 workload 和参数数量
  -> 得到 reduced workload Wr 和 reduced knob set Kr

Step 3:
  参数取值范围确定
  -> 根据采样结果和历史优质配置缩小参数上下界
  -> 得到 reduced knob range Rr
  -> 在 Kr + Rr + Wr 上执行 BO
  -> 最终用完整 workload 验证最优配置
```

更简洁地说：

```text
先决定调哪些参数。
再决定用哪些 SQL 调。
最后决定这些参数在哪些范围里调。
```

---

## 3. Step 1: LLM 先验去除无关参数

### 3.1 目标

第一步解决的是：

```text
参数多少？
```

数据库参数很多，但不是所有参数都和当前 workload 有关。

例如：

```text
日志参数
监控参数
debug 参数
tracing 参数
和当前查询路径无关的后台任务参数
```

这些参数如果进入 BO，会增加搜索维度，浪费配置评估次数。

因此第一步用 LLM 做粗粒度参数筛选。

### 3.2 LLM 输入

LLM 的输入包括：

```text
1. 参数名称
2. 参数说明
3. 参数默认值
4. 参数类型
5. 参数上下界
6. 参数所属模块
7. 当前 workload 特征
8. 当前数据库部署环境
```

例如：

```text
workload 是 ANN 查询为主。
数据库是 DingoDB。
运行环境是 2 节点或 7 节点。
并发线程数为 10。
```

### 3.3 LLM 输出

LLM 输出参数重要性分组：

```text
High relevance:
  必须保留，可能明显影响当前 workload。

Medium relevance:
  暂时保留，交给后续采样判断。

Low relevance:
  低优先级，可以考虑删除。

Irrelevant:
  明显无关，直接删除。

Risky:
  可能导致系统不稳定，不进入自动调参。
```

最终得到：

```text
K0 = LLM 过滤后的候选参数空间
```

### 3.4 注意事项

LLM 只做先验判断，不直接决定最终参数值。

原则是：

```text
只删除明显无关参数。
不确定的参数先保留。
后续再用采样结果做经验筛选。
```

这样可以避免 LLM 误删重要参数。

### 3.5 论文表述

```text
We first use an LLM to construct a coarse-grained knob prior from database documentation and workload descriptions. The LLM removes only obviously irrelevant or risky knobs, while uncertain knobs are kept for empirical probing.
```

---

## 4. Step 2: 自适应采样，同时缩小工作负载和参数数量

### 4.1 目标

第二步同时解决两个问题：

```text
1. 工作负载大小
2. 参数多少
```

也就是说，同一批采样数据要同时用于：

```text
1. 判断哪些 SQL 对参数变化敏感
2. 判断哪些参数对整体性能有影响
```

这是方法的核心。

### 4.2 为什么需要自适应采样

不能简单固定采样 15 组配置。

固定 15 的问题：

```text
1. 不同 workload 需要的样本数不同。
2. 不同参数空间需要的样本数不同。
3. 很难解释为什么是 15。
4. 采样太少结果不稳定。
5. 采样太多浪费时间。
```

因此使用：

```text
Adaptive LHS Probing
```

即：

```text
每轮采一批配置。
每轮更新 SQL 筛选结果和参数筛选结果。
如果连续多轮结果稳定，则停止采样。
```

### 4.3 采样方式

使用 Latin Hypercube Sampling, LHS。

原因：

```text
LHS 比纯随机采样覆盖更均匀。
少量样本也能覆盖多个参数维度。
适合作为初始 probing。
```

推荐默认设置：

```text
min_samples = 10
batch_size = 5
max_samples = 30
stable_rounds_required = 2
```

实际采样数量不是固定的：

```text
可能是 10
可能是 15
可能是 20
可能是 25
最多是 30
```

由稳定性决定。

### 4.4 每轮采样收集什么

对每组采样配置执行 workload，收���两类数据：

#### 4.4.1 配置级数据

```text
Config_i -> total_execution_time_i
```

转换成优化目标：

```text
target_i = -total_execution_time_i
```

用于判断参数和性能之间的关系。

#### 4.4.2 SQL 级数据

```text
Config_i:
  SQL_1 -> latency_1i
  SQL_2 -> latency_2i
  ...
  SQL_m -> latency_mi
```

用于判断每条 SQL 是否对配置变化敏感。

### 4.5 缩小工作负载大小

工作负载缩小分两层。

#### 4.5.1 SQL 去重

先删除高度相似 SQL。

相似性可以来自：

```text
1. SQL 类型
2. 目标表
3. where predicate
4. group by
5. order by
6. ANN 查询结构
```

得到：

```text
W_dedup
```

#### 4.5.2 配置敏感 SQL 筛选

对每条 SQL，计算它在不同采样配置下的执行时间波动。

使用 CV：

```text
CV = standard deviation / mean
```

对于 SQL q：

```text
latency(q) = [t_1, t_2, ..., t_n]
CV(q) = std(latency(q)) / mean(latency(q))
```

含义：

```text
CV 越大，说明 SQL 对参数变化越敏感。
CV 越小，说明 SQL 对参数变化不敏感。
```

保留：

```text
CV 排名靠前的 SQL。
```

得到：

```text
Wr = reduced workload
```

推荐策略：

```text
top_ratio = 0.1
min_sql = 10
max_sql = 100
```

即：

```text
保留 CV 前 10% 的 SQL。
至少保留 10 条。
最多保留 100 条。
```

### 4.6 缩小参数数量

用采样结果计算每个参数和整体性能目标的关系。

对每个参数 k：

```text
corr(k, target)
```

推荐使用：

```text
Spearman correlation
```

原因：

```text
数据库参数和性能之间不一定是线性关系。
Spearman 可以反映单调关系。
```

删除低相关参数：

```text
if abs(corr(k, target)) < threshold:
    remove k
```

推荐初始阈值：

```text
threshold = 0.05
```

得到：

```text
Kr = reduced knob set
```

更稳健的删除规则：

```text
1. 参数相关性低于阈值。
2. 连续多轮都低相关。
3. 不属于 LLM 标记的 high relevance 参数。
```

这样可以避免过早删除潜在重要参数。

### 4.7 稳定性判断

采样是否停止，不看采样数是否达到固定 15，而是看两个集合是否稳定：

```text
1. SQL 子集 Wr 是否稳定
2. 参数子集 Kr 是否稳定
```

#### 4.7.1 SQL 集合稳定性

当前轮 SQL 子集：

```text
W_t
```

上一轮 SQL 子集：

```text
W_{t-1}
```

使用 Jaccard：

```text
Jaccard(W_t, W_{t-1}) = |W_t ∩ W_{t-1}| / |W_t ∪ W_{t-1}|
```

#### 4.7.2 参数集合稳定性

当前轮参数子集：

```text
K_t
```

上一轮参数子集：

```text
K_{t-1}
```

使用 Jaccard：

```text
Jaccard(K_t, K_{t-1}) = |K_t ∩ K_{t-1}| / |K_t ∪ K_{t-1}|
```

#### 4.7.3 停止条件

如果连续多轮同时满足：

```text
Jaccard(W_t, W_{t-1}) >= 0.9
Jaccard(K_t, K_{t-1}) >= 0.9
```

则停止采样。

推荐：

```text
stable_rounds_required = 2
```

如果一直不稳定，则达到最大采样数后停止：

```text
max_samples = 30
```

### 4.8 Step 2 输出

第二步最终输出：

```text
1. reduced workload Wr
2. reduced knob set Kr
3. probing dataset D
```

其中 probing dataset D 包括：

```text
1. 每组配置
2. 每组配置的 total execution time
3. 每条 SQL 在每组配置下的 latency
```

这些数据后面还可以用于 BO 初始化。

---

## 5. Step 3: 确定参数取值范围

### 5.1 目标

第三步解决的是：

```text
参数取值范围
```

经过前两步，已经知道：

```text
调哪些参数 Kr
用哪些 SQL Wr
```

但每个参数的搜索范围仍可能很大。

例如：

```text
read_worker_num: [1, 128]
batch_size: [1, 10000]
cache_size: [128MB, 64GB]
```

如果直接在大范围内 BO，搜索仍然困难。

因此需要根据采样结果缩小取值范围。

### 5.2 根据优质采样配置缩小范围

从 probing dataset D 中选出表现最好的 top-k 配置：

```text
top_k = 3 或 5
```

对于每个连续参数 k，观察它在 top-k 配置中的取值：

```text
values(k) = [v_1, v_2, ..., v_k]
```

新的范围：

```text
lower_k = min(values(k))
upper_k = max(values(k))
```

例如：

```text
原始范围:
  read_worker_num: [1, 128]

top-3 配置中的取值:
  [12, 16, 20]

新范围:
  read_worker_num: [12, 20]
```

为了避免范围过窄，可以加 padding：

```text
new_lower = max(original_lower, lower_k - padding)
new_upper = min(original_upper, upper_k + padding)
```

padding 可以设为：

```text
原始范围的 5% 或 10%
```

### 5.3 根据相关性方向缩小 enum 参数

对于 enum 参数，例如：

```text
true / false
```

BO 中可以映射成：

```text
false -> 0
true  -> 1
```

如果：

```text
corr(k, target) > 0
```

说明参数取值越接近 1，target 越好。

则可以收缩为：

```text
k in [0.51, 1]
```

如果：

```text
corr(k, target) < 0
```

说明参数取值越接近 0，target 越好。

则可以收缩为：

```text
k in [0, 0.49]
```

建议只对强相关 enum 参数做这个操作：

```text
abs(corr(k, target)) > 0.4
```

### 5.4 搜索过程中的动态范围更新

参数范围不一定只缩一次。

在 BO 过程中，可以周期性更新范围：

```text
每 15 轮:
  根据 enum 参数相关性收缩 enum 范围。

每 40 轮:
  根据历史 top-k 配置收缩连续参数范围。
```

这对应当前代码中的思想：

```python
if (i + 1) % 15 == 0:
    change_param(i)

if (i + 1) % 40 == 0:
    change_con_param()
```

但论文中不要写死，可以写成：

```text
enum_refine_interval
continuous_refine_interval
```

### 5.5 Step 3 输出

第三步最终输出：

```text
1. reduced knob set Kr
2. reduced knob range Rr
3. reduced workload Wr
```

然后进入 BO：

```text
BO(Kr, Rr, Wr)
```

---

## 6. Bayesian Optimization 阶段

### 6.1 输入

BO 的输入不是原始空间，而是：

```text
1. 筛选后的参数集合 Kr
2. 缩小后的参数范围 Rr
3. 筛选后的 workload Wr
```

也就是：

```text
BO(Kr, Rr, Wr)
```

### 6.2 目标函数

每轮 BO：

```text
1. 选择下一组配置 c
2. 下发配置 c
3. 执行 reduced workload Wr
4. 得到执行时间 t
5. 返回 target = -t
```

即：

```text
maximize -execution_time
```

等价于：

```text
minimize execution_time
```

### 6.3 复用采样数据

Step 2 的 probing 数据已经执行过一批配置。

这些数据不应该浪费。

应该注册到 BO：

```text
for record in probing dataset D:
    BO.register(record.config, record.target)
```

这样 BO 不是冷启动，而是从已有观测开始。

---

## 7. 最终完整 workload 验证

### 7.1 为什么需要验证

BO 阶段使用的是 reduced workload Wr。

最终配置必须在完整 workload W 上验证。

原因：

```text
防止配置只在 reduced workload 上表现好。
保证最终结果对原始 workload 有效。
```

### 7.2 验证方式

从 BO 历史中选 top-k 配置：

```text
top_k = 5
```

在完整 workload 上重新执行：

```text
for config in top_k_configs:
    apply config
    run full workload W
    record full_execution_time
```

最终选择：

```text
full_execution_time 最小的配置
```

作为最终输出。

### 7.3 关键表述

```text
The reduced workload is used only for efficient search. The final candidate configurations are re-evaluated on the full workload to avoid overfitting to the reduced workload.
```

---

## 8. 三阶段伪代码

```text
Algorithm: DGTuner Three-Stage Optimization

Input:
  K: original knob space
  W: original workload
  Doc: database knob documentation
  B: tuning budget

Output:
  c*: final best configuration

Stage 1: Reduce knob number by LLM prior
  K0 = LLM_Filter(K, Doc, W)

Stage 2: Adaptive probing for workload size and knob number
  D = empty probing dataset
  prev_W = None
  prev_K = None
  stable_count = 0

  while |D| < max_samples:
      C_batch = LHS(K0, batch_size)
      for c in C_batch:
          apply c
          run W
          collect total runtime and per-query latency
          add record to D

      if |D| < min_samples:
          continue

      W_t = SelectSensitiveSQL(W, D)
      K_t = SelectImportantKnobs(K0, D)

      if prev_W is not None:
          workload_stability = Jaccard(W_t, prev_W)
          knob_stability = Jaccard(K_t, prev_K)

          if workload_stability >= theta_w
             and knob_stability >= theta_k:
              stable_count += 1
          else:
              stable_count = 0

      if stable_count >= required_stable_rounds:
          break

      prev_W = W_t
      prev_K = K_t

  Wr = W_t
  Kr = K_t

Stage 3: Determine knob value ranges
  Rr = ShrinkRanges(Kr, D)

Bayesian Optimization:
  Initialize BO with Kr and Rr
  Register probing records D into BO

  while budget remains:
      c = BO.suggest()
      apply c
      t = run Wr
      BO.register(c, -t)

      periodically:
          update Rr using search history

Final validation:
  C_top = top-k configs from BO history
  for c in C_top:
      apply c
      t_full = run W

  c* = config with minimum t_full
  return c*
```

---

## 9. 与已有工作的区别

已有 LLM 数据库调参方法通常是：

```text
LLM 分析参数
-> 缩小参数范围
-> 执行 workload 测试
-> 根据反馈继续缩小参数空间
```

DGTuner 更强调三个优化对象：

```text
1. 参数数量
2. 工作负载大小
3. 参数取值范围
```

主要区别：

```text
已有方法主要关注参数空间。
DGTuner 同时关注 workload 评估成本。
```

也就是说：

```text
已有方法:
  reduce knob space

DGTuner:
  reduce knob number
  reduce workload size
  reduce knob value range
```

特别是：

```text
DGTuner 使用采样数据识别配置敏感 SQL，
使后续 BO 不必每轮执行完整 workload。
```

这是区别于大多数已有 LLM 调参工作的关键点。

---

## 10. 实验指标

为了证明方法有效，需要分别证明三个缩减目标有效。

### 10.1 参数数量缩减效果

报告：

```text
原始参数数量
LLM 删除后参数数量
采样相关性筛选后参数数量
最终 BO 搜索参数数量
```

例如：

```text
Original knobs: 80
After LLM prior: 45
After probing pruning: 22
```

### 10.2 工作负载大小缩减效果

报告：

```text
原始 SQL 数量
去重后 SQL 数量
CV 筛选后 SQL 数量
workload reduction ratio
```

例如：

```text
Original SQL: 1000
After dedup: 200
After sensitivity selection: 30
Reduction ratio: 97%
```

### 10.3 参数取值范围缩减效果

报告：

```text
每个参数原始范围
缩小后的范围
范围缩小比例
```

例如：

```text
read_worker_num:
  original: [1, 128]
  reduced: [12, 24]
```

### 10.4 性能指标

报告：

```text
1. best execution time
2. tuning time
3. average evaluation time per configuration
4. number of evaluated configurations
5. speedup over default
6. speedup over baselines
7. final full workload performance
```

### 10.5 reduced workload 有效性

需要证明：

```text
reduced workload 上表现好的配置，在 full workload 上也表现好。
```

可以使用：

```text
Spearman ranking correlation
```

计算：

```text
同一批配置在 reduced workload 和 full workload 上的性能排名相关性。
```

---

## 11. 消融实验

建议做：

```text
DGTuner full
DGTuner without LLM prior
DGTuner without workload reduction
DGTuner without knob number pruning
DGTuner without range shrinking
DGTuner with fixed 15 probing samples
DGTuner with adaptive probing
BO on full workload
Random Search
SMAC3
LlamaTune / AgentTune
```

最重要的消融：

```text
1. without workload reduction
2. with fixed 15 probing samples
3. with adaptive probing
```

因为这能证明：

```text
1. 缩 workload 是否真的有效。
2. 自适应采样是否比固定采样更合理。
```

---

## 12. 推荐默认参数

```text
LLM prior:
  remove_only_obvious_irrelevant = true

Adaptive probing:
  min_samples = 10
  batch_size = 5
  max_samples = 30
  stable_rounds_required = 2
  workload_stability_threshold = 0.9
  knob_stability_threshold = 0.9

Workload reduction:
  sql_top_ratio = 0.1
  min_sql = 10
  max_sql = 100

Knob pruning:
  correlation_method = spearman
  weak_correlation_threshold = 0.05
  protect_llm_high_relevance = true

Range shrinking:
  top_k_configs = 3
  padding_ratio = 0.1
  enum_strong_correlation_threshold = 0.4
  enum_refine_interval = 15
  continuous_refine_interval = 40

Final validation:
  validate_top_k = 5
```

---

## 13. 当前代码改造重点

### 13.1 把固定采样改成自适应采样

当前逻辑类似：

```python
self.LSA(15)
```

目标：

```python
self.adaptive_probe(
    min_samples=10,
    batch_size=5,
    max_samples=30,
    stable_rounds_required=2,
)
```

### 13.2 SQL 筛选要返回集合

当前更多是写文件。

需要返回：

```python
selected_sql_set
```

用于计算：

```python
jaccard(selected_sql_set, prev_sql_set)
```

### 13.3 参数筛选要返回集合

需要返回：

```python
selected_knob_set
```

用于计算：

```python
jaccard(selected_knob_set, prev_knob_set)
```

### 13.4 参数范围收缩单独成模块

建议把第三步整理成独立逻辑：

```python
range_refiner.py
```

或者放在：

```python
dgtuner/knob_pruner.py
```

函数可以是：

```python
shrink_numeric_ranges_from_top_configs(...)
shrink_enum_ranges_by_correlation(...)
```

### 13.5 Probing 数据注册进 BO

Step 2 跑过的配置要进入 BO：

```python
for record in probing_records:
    optimizer.register(record.params, record.target)
```

### 13.6 完整 workload 验证

最终加：

```python
validate_top_k_on_full_workload(...)
```

不要只报告 reduced workload 上的最优结果。

---

## 14. 一句话总结

DGTuner 的方法可以总结为：

```text
先用 LLM 先验减少需要调的参数数量，
再用自适应采样同时缩小工作负载大小和参数数量，
最后根据采样和搜索历史确定参数取值范围，
并在缩小后的三维搜索对象上执行 BO，
最终回到完整 workload 验证最优配置。
```

更短的表述：

```text
DGTuner reduces knob number, workload size, and knob value range before Bayesian Optimization.
```

