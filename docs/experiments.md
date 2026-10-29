# Linux 仿真与对比实验

## 运行

```bash
./scripts/run_experiments.sh
```

脚本会生成 `results/baseline.json`、`results/compare.json` 和 `results/deadlock.json`。每个 JSON 同时保存汇总指标、任务最终状态和逐时刻轨迹，便于复现实验和整理原始数据。

## 对比组

| 组别 | 动态重调度 | 抢占 | 银行家/检测/恢复 | 目的 |
| --- | --- | --- | --- | --- |
| baseline | 有 | 有 | 有 | 完整方案 |
| no_dynamic | 无 | 无 | 有 | 观察环境和紧急中断下的退化 |
| no_deadlock | 有 | 有 | 无 | 对比死锁机制的必要性 |
| non_preemptive | 有 | 无 | 有 | 对比抢占策略 |

## 论文表格建议

将每组 `metrics` 的完成率、平均响应时间、平均逾期时长、逐资源利用率、死锁次数、资源冲突、安全性拒绝和紧急任务错失率放在同一张表中。`average_completion_delay` 按本项目定义表示完成时延（完成时刻减到达时刻），逾期时长单列为 `average_lateness`。无完成任务或无符合条件紧急任务时对应值为空。当前演示使用固定事件时间，先用于验证机制和可复现性；开展正式实验时再按共同随机负载要求复用输入，并保留种子、配置和版本。
