# 演示、统计口径与正式实验交接

## 固定演示

```bash
./scripts/run_experiments.sh
python3 run_demo.py --scenario compare --csv results/compare.csv
python3 run_demo.py --input data/demos/basic.json --view trace
```

固定业务演示 H=200，死锁专项 H=20；两者用于不同机制验证，不能跨场景直接比较利用率。

| 方案 | 相对 baseline 的唯一机制变化 | 检测是否保留 |
|---|---|---|
| baseline | 动态优先级、可抢占、银行家、检测与回滚 | 是 |
| fcfs | 排序改 FCFS（按 FCFS 定义不主动抢占） | 是 |
| no_dynamic | 仅关闭动态重排；抢占配置值保持，但静态语义不触发主动抢占 | 是 |
| non_preemptive | 仅关闭主动抢占 | 是 |
| no_deadlock | 关闭银行家与回滚，用于比较保护组合 | 是，保留为观测工具 |

`no_deadlock` 是保护组合对照，不能把差异归因于单个死锁算法。普通业务未形成死锁时，关闭保护也可能同样完成；使用相反申请顺序的专项场景展示区别。FCFS 排序与抢占语义联动；如果只研究优先级排序，应在双方均关闭抢占的配置下另做对照。

## 指标字段

| JSON 字段 | 定义 |
|---|---|
| `total_tasks` | 观察窗口内到达的任务数，含事件生成，去除重复杯子事件 |
| `completion_rate` | 完成数 / 到达数 |
| `on_time_completion_rate` | 按各自截止时间完成数 / 到达数 |
| `average_completion_delay`、`average_response_time` | 已完成任务的 `finish-arrival` 均值；保留旧字段兼容 |
| `average_lateness` | 已完成任务 `max(0,finish-deadline)` 均值 |
| `resource_utilization_by_resource` | 本阶段确实使用该资源的工作时间 / (H-资源不可用时间) |
| `resource_occupancy_by_resource` | 可服务期间被任务持有的时间 / 可服务时间，含持有等待 |
| `resource_utilization` | 有定义的互斥资源利用率简单平均；应优先报告逐资源值 |
| `conflict_count` | 因已占用进入一段新等待的次数，不逐时间步累加 |
| `safety_rejection_count` | 新的银行家不安全等待，与冲突、故障区分 |
| `deadlock_count` | 新出现的循环等待任务组数，未解除的持续环不重复累计 |
| `urgent_task_miss_rate` | 截止时间不晚于 H 的已到达紧急任务中，未按时完成的比例 |
| `rollback_work` / `redo_work` | 回滚丢失量 / 后续实际执行的重做量 |

无到达任务、无完成任务、无已到期紧急任务或资源服务时间为零时，相应比率/均值为 JSON `null`，CSV 为空；不填零制造优势。`unfinished` 给出未完成任务的在系统中时长、剩余总工作量和原因。未来任务保留在最终输入/任务表，但不进入分母或执行前快照。

`resource_busy_ticks`、`resource_held_ticks`、`resource_available_ticks`、`resource_outage_ticks`、`resource_outage_held_ticks` 保留原始计数，便于手算复核。故障期间有效工作为零，故障中保留占用单列。

## 本轮真实小案例结果

业务基线：6/6 完成，平均完成时延 7，紧急错失率 0，抢占 1 次。其他固定业务对照同样 6/6 完成且平均时延为 7；FCFS、静态和非抢占的紧急错失率为 1。这个小输入显示紧急任务与普通任务的时间交换，不证明平均时延普遍改善。

| 同一死锁输入 | 完成数 | 死锁数 | 安全拒绝 | 回滚数 | 损失 / 实际重做 |
|---|---:|---:|---:|---:|---:|
| 银行家避免 | 2 | 0 | 1 | 0 | 0 / 0 |
| 只检测 | 0 | 1 | 0 | 0 | 0 / 0 |
| 检测并恢复 | 2 | 1 | 0 | 1 | 1 / 1 |

只检测组到 H 正常结束并导出两个未完成任务，完成时延为空。避免与恢复的平均完成时延分别为 3 和 4；这是该固定输入的观测结果。

## 回归负载与正式实验

```bash
python3 -m scripts.verify_workloads --seeds 20 --output results/regression
```

脚本先为每个种子生成一份输入，五种策略复用，检查运行时不变量、工作量、固定窗口、摘要一致与 H 边界。保存原始输入、100 份结果、`metrics.csv` 和 `verification.json`。它是集成回归，负载参数尚未作为真实茶歇服务模型校准，不能直接当作正式实验结论。

王晶莹应另行完成普通负载、台面拥堵、紧急密集、故障强度等实验设计、指标手算和不少于约定独立种子的统计；李和雨负责公式与报告核对。正式报告需要样本数、均值/标准差、未完成数量、代价和全部原始记录。结果中的 `input`、种子、Git 提交、`source_sha256`、`input_sha256`、`workload_sha256` 用于追溯；后者不含策略配置，用来核对相同负载。
