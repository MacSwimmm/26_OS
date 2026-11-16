# 候选排序、理由与验证

例如，同一时刻已有 A（priority=1）和 B（priority=3）两个候选：FCFS 在到达时间相同时按编号把 A 排前；优先级策略把 B 排前。候选排前意味着先尝试申请资源；申请失败时，引擎仍可尝试后面的其他任务。

本文对应项目说明第 6.1、6.2、13.2、13.3 节。基于 PR #3 的排序接口与案例补齐并集成，实际贡献以提交记录为准。

## 范围与接口

`tea_break_scheduler/policies.py` 接收给定的候选列表，只返回排序和解释，不修改列表或任务字段。排序结果是新列表，其中仍引用原 Task 对象。依赖满足、实际到达、资源申请、抢占、故障、时间推进与死锁由引擎及相应模块负责。

```python
from tea_break_scheduler.policies import order_tasks, rank_tasks, explain, format_ranking

order_tasks(tasks, "priority")     # [Task, ...]
rank_tasks(tasks, "priority")      # [(Task, "相对下一候选的理由"), ...]
format_ranking(tasks, "fcfs")      # "A -> B"
explain(first, second, "priority") # 两个任务必须已按该策略排列
```

另保留 `selection_reason(policy)` 的策略级摘要接口，两个有效策略的返回值保持兼容。所有接口遇到未知策略都抛 `ValueError`，包括空列表与 `explain(..., None, ...)`。`explain` 遇到反向任务对也抛 `ValueError`，避免输出“1 > 3”这样的错误解释；完全相同的排序键说明为“保留输入次序”。实际引擎另行禁止重复任务编号。

模块只依赖标准库，支持 Python 3.10+。

## 规则与数学定义

| 策略 | 升序比较键 | 并列处理 |
|---|---|---|
| FCFS | `(submitted_at, task_id)` | 到达相同才比较编号 |
| 优先级 | `(-priority, deadline, submitted_at, task_id)` | 优先级相同才比较截止时间，依次继续 |

任务编号按字符串字典序比较，例如 `T10 < T2 < T9`。这不是提取数字后的自然序。优先级越大越靠前，截止时间为绝对模拟时刻，软截止不自动取消任务。

设候选集为 C，任务 t 的键为 k(t)，完整排列写为：

```text
(t1, ..., tn) = sort(C, key=k)
k(t1) <= k(t2) <= ... <= k(tn)
```

只表示队首时才使用 `argmin(t in C) k(t)`。引擎保证编号唯一，因此不同任务最终能由编号确定次序。

`urgent` 不在排序键中，不能独立改变顺序。固定业务默认给紧急送水 3、普通送水 2、整理/回收 1；自定义输入仍以明确提供的 priority 为准。紧急标记在原引擎的抢占资源考虑和指标分类中另有用途，不能据此推导出排序里有额外紧急规则。

固定优先级不含老化、EDF 或优先级继承，也不保证全局最优与没有饥饿。

## 真实日志与执行次序

动态模式由引擎筛选 READY 任务，每次按规则排序。纯排序函数没有当前时钟，不会自行排除未来任务或依赖未满足任务；直接传入整份任务计划得到的排序不能当作实时调度轨迹。

静态模式保留 t=0 初始输入任务的排序，后续到达按到达时间、编号追加；不会因后来的高优先级重新排队。它不使用动态理由解释冻结队列。

成功开始、恢复和阶段开始事件（`start/resume/stage_start`）提供：

| 字段 | 含义 |
|---|---|
| `reason` | 页面和 CLI 可读的候选名次、比较依据及资源检查通过说明 |
| `ordering.mode` | `dynamic` 或 `static` |
| `ordering.policy` | `fcfs` 或 `priority` |
| `ordering.rank` | 本次候选列表内从 1 开始的名次 |
| `ordering.candidate_count` | 本次尝试开始前的候选数量 |
| `ordering.compared_to` | 紧随该任务的候选编号，末位为 null |
| `ordering.reason` | 动态模式的首个决胜键，或静态队列的实际依据 |

例如 A、B 同优先级，截止时间分别为 10、20，日志为：

```text
动态排序候选第 1/2 位；相对 B：同优先级，截止时间更早（10 < 20）；资源检查通过
```

名次是本次尝试列表中的位置，不是最终开始次序或资源安全证明。队首受阻时，低名次但使用其他资源的任务可以成功执行，并保留其真实名次；受阻原因仍查看独立的 `resource_wait` 等事件。抢占使某个运行任务重新就绪时，它按原引擎流程在之后的尝试中处理，本次日志不会假装重新枚举了全部候选。

## 预先列明的核对案例

`data/policies/cases.json` 是专用排序案例集合，带 `kind=ordering_cases`，不是 `run_demo.py --input` 所接收的完整场景。每例提供观察时刻、输入、手算步骤及预期；脚本只读，不把程序结果回写为预期。

| 案例 | 观察时刻 | 验证点 | 预期 |
|---|---:|---|---|
| C1 | 2 | FCFS 先比较到达，再比较编号 | T1 → T2 → T3 |
| C2 | 2 | 同一批已到达任务按优先级排序 | T2 → T1 → T3 |
| C3 | 5 | 同优先级比较截止时间，再比较编号 | C → D → A → B |
| C4 | 0 | 前三级相同，由编号决胜 | t1 → t2 → t3 |
| C5 | 0 | 空候选集 | 空 |
| C6 | 5 | 同优先级、同截止，比较到达时间 | Z → A |
| C7 | 0 | FCFS 同时到达，按字符串编号 | T10 → T2 → T9 |
| C8 | 0 | 紧急标记不能越过优先级 | N → U |
| C9 | 3 | 单候选 | ONLY |
| C10 | 0 | 紧急标记不能越过同优先级截止时间 | N → U |

C1/C2 均在 t=2 观察，所有列入的任务已到达；它们验证相同候选的排序差异，不意味着 t=0 能预知未来任务。

在仓库根目录执行：

```bash
python3 -m unittest discover -s tests -p 'test_policies.py' -v
python3 scripts/check_policies.py
python3 scripts/check_policies.py --json-out results/policies/validation.json
```

脚本打印“输入、观察时刻、手算、预期、实际、理由、判定”，记录实际输入、预期、结果、Python/系统、UTC 时间、Git 和源码/案例摘要。默认归档到 `results/policies_validation.json`，也支持 `--no-archive`。全部匹配返回 0；顺序不符返回 1；非法文件、空案例集合、未来候选或无效预期等输入错误返回 2，不会把 0 个案例视为全部通过。

## 答辩操作与说明

若已启动网页服务，保持**终端 1**运行 `python3 dashboard_server.py`；以下命令在**终端 2**、当前待验收版本的仓库根目录执行。

```bash
python3 scripts/check_policies.py --no-archive
python3 run_demo.py --scenario baseline --view trace
python3 run_demo.py --scenario no_dynamic --view trace
```

先展示 C1/C2 的相同输入和不同预期，再展示 C6 的到达并列规则及 C8/C10 的紧急标记边界。说明：“我们预先按规则列出顺序，再和程序输出核对。排序函数只决定候选尝试顺序，真正开始还要通过资源检查。”

随后展示实际轨迹中的候选名次与比较对象；静态组显示静态依据，资源等待单独记录。网页事件列表也读取同一 `reason`，不是前端重新实现排序。

## 本轮验收边界

原始主分支 `027d38a` 与修改版本已进行任务结果、资源、快照和规范化事件轨迹对比；数字与具体范围见 [修复交付记录](review/PR3排序修复交付.md)。此次软件验收不替代正式实验分析、报告整合或教师目标机器的现场演示。
