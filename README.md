# 茶歇服务员任务调度仿真系统

本仓库对应《操作系统（Linux）》期末论文选题 4：**茶歇服务员任务调度算法研究**。项目使用纯 Python 标准库实现，能够在 Ubuntu 22.04/Linux 上直接运行，代码用于支撑论文中的建模、算法说明、对比实验和演示。

## 已覆盖的考核点

- 任务结构体：优先级、截止时间、执行时长、前置依赖、资源需求、是否可抢占、状态和剩余时间。
- 资源竞争：茶歇台、取杯区、回收区、通行通道等互斥资源；竞争时支持延迟、重排和临时重试。
- 调度：静态优先级/截止时间预调度，动态重调度；抢占和非抢占两种模式。
- 死锁全套机制：银行家算法避免、资源分配图/等待图检测、回滚/资源释放/撤销恢复。
- 中断：紧急服务请求、环境扰动、故障中断；支持保存运行状态和恢复。
- 指标：完成率、平均完成时延、资源利用率、死锁次数、冲突次数、紧急任务错失率。
- Linux 仿真：基准场景、无动态重调度、无死锁机制、抢占/非抢占对比，并输出可复现的 JSON 结果。

## 快速开始

只需要 Python 3.10+，不需要第三方包：

```bash
python3 run_demo.py --scenario baseline
python3 run_demo.py --scenario compare --output results/compare.json
python3 -m unittest discover -s tests -v
```

也可以使用 Linux 启动脚本：

```bash
chmod +x scripts/run_experiments.sh
./scripts/run_experiments.sh
```

## 目录结构

```text
26_OS/
├── tea_break_scheduler/       # 可复用的调度器、资源模型、死锁算法、指标
├── run_demo.py                # 命令行演示和对比实验入口
├── scripts/run_experiments.sh # Ubuntu/Linux 一键运行脚本
├── tests/                     # 可重复的单元测试
├── docs/                      # 架构、实验和分工说明
└── results/                   # 实验运行后生成的 JSON（不提交大文件）
```

## 论文和答辩使用方式

1. 先运行 `baseline` 查看一组带中断的完整调度轨迹。
2. 运行 `compare`，比较 `banker+dynamic+preemptive`、无死锁机制、无动态重调度和非抢占模式。
3. 把 `results/*.json` 中的指标整理成论文表格，把 `trace` 中的时间线整理成流程图。
4. 答辩时重点解释 `Task` 结构、银行家安全性检查、等待图环检测和中断保存/恢复。

完整模型、算法和实验说明见 [docs/architecture.md](docs/architecture.md) 与 [docs/experiments.md](docs/experiments.md)。
