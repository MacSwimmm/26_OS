# 茶歇服务员任务调度仿真系统

本仓库对应《操作系统（Linux）》期末论文选题 4：**茶歇服务员任务调度算法研究**。项目使用纯 Python 标准库实现，能够在 Ubuntu 22.04/Linux 上直接运行，代码用于支撑论文中的建模、算法说明、对比实验和演示。

## 已覆盖的考核点

- 任务结构体：优先级、截止时间、执行时长、前置依赖、资源需求、是否可抢占、状态和剩余时间。
- 资源竞争：茶歇台、取杯区、回收区、通行通道等互斥资源；竞争时支持延迟、重排和临时重试。
- 调度：静态初始顺序与动态优先级重排；支持分阶段任务、抢占与进度恢复。
- 死锁机制：分阶段增量申请接入银行家检查；实际等待关系构造等待图；可回滚任务恢复到检查点并记录重做量。
- 中断：紧急请求可抢占资源冲突的低优先级任务；环境和故障事件可暂停任务、释放资源并在可用后恢复。
- 指标：完成率、平均响应时间、平均逾期时长、逐资源利用率、死锁/冲突/安全性拒绝、回滚成本和紧急任务错失率。
- Linux 仿真：基准场景、无动态重调度、无死锁机制、抢占/非抢占对比，并输出可复现的 JSON 结果。

## 快速开始

只需要 Python 3.10+，不需要第三方包：

```bash
python3 run_demo.py --scenario baseline --live
python3 run_demo.py --scenario compare
python3 run_demo.py --scenario deadlock
python3 -m unittest discover -s tests -v
```

默认结果视图显示任务状态表和关键指标。加 `--live` 可按模拟时间查看正在运行、等待、暂停、恢复和完成事件；默认每步停留 0.25 秒，可用 `--delay 0.5` 放慢或 `--delay 0` 关闭等待。`--view trace` 显示单组事件时间线，`--view json` 显示完整数据。用 `--output results/baseline.json` 保存完整 JSON 结果，不影响终端简报。

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

1. 运行 `baseline` 查看紧急请求抢占、环境暂停和故障暂停后的恢复轨迹。
2. 运行 `deadlock`，同一分阶段输入分别验证银行家避免、只检测不恢复、检测并回滚恢复。
3. 运行 `compare`，比较动态重调度、抢占及死锁保护开关对固定演示输入的影响。
4. 把 `results/*.json` 中的指标整理成论文表格，把 `trace` 中的时间线整理成流程图。
5. 答辩时重点解释 `Task`/`TaskStage`、银行家安全性检查、等待图环检测和中断保存/恢复。

完整模型、算法和实验说明见 [docs/architecture.md](docs/architecture.md) 与 [docs/experiments.md](docs/experiments.md)。
