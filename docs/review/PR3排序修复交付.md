# PR #3 排序修复与交付

日期：2026-11-16。修复及本地验证完成；用户审阅后已授权使用 MacSwimmm 账户提交、推送并在检查通过后合并。发布状态以 GitHub 对应 PR 与主分支为准，本文保留修复时的验收证据。

本轮基于 GitHub 主分支 `027d38a8c9d04c224b9a2091b2b25f1a411f840b`，工作分支为 `codex/pr3-policies-review`，独立工作区为 `/home/hanzhhh/桌面/26_OS-policies-review`。原工作区 `/home/hanzhhh/桌面/26_OS` 的 main 保持原状；该旧本地分支停在 `73aa279`，不能用其 52 项测试替代目标主分支的 68 项验收。

## 完成情况

已补齐文档第 13 节规定的排序软件交付：排序接口、并列规则、手算案例、核对入口、真实日志、算法说明和答辩操作。复用了 PR #3 的正确排序与案例基础，并统一修复与集成；实际工作不能全部记作原提交者个人已完成。

初次审查版本为 `cdeae66`。工作开始时 PR 已更新到 `d38d9df`，删除了理由中的“紧急任务优先”，但未同步原测试。最新代码通过 GitHub 内容接口核对，`policies.py` 的 Git blob 为 `0be06173a902130e2867feb75e997c836410fa04`。以原 PR 树加该最新文件复现：83 项全量测试有 1 项失败、1 项报错，分别为理由测试过期和排序 JSON 被当作仿真场景。

整理待提交材料时，PR 又更新到 `1cb6b88`，同步了理由断言，但将脚本和测试指向不存在的 `data/policies_cases.json`，实际额外上传在 `tests/policies_cases.json`，原 `data/demos/` 文件也仍在。已核对该提交的文件树和对应文件，并在独立临时区复现 83 项中 2 项报错。还多出一份 `scripts/test_policies.py` 测试副本。本地待提交版本采用单一 `data/policies/cases.json` 和 `tests/test_policies.py`，不继承这些路径与副本问题。

## 修改与目的

| 文件 | 修改 | 目的 |
|---|---|---|
| `tea_break_scheduler/policies.py` | 保留 FCFS `(arrival,id)` 与优先级 `(-priority,deadline,arrival,id)`；集中键定义；补齐理由、统一策略校验、反向比较拒绝 | 保证解释与真实规则一致，排序无副作用 |
| `tea_break_scheduler/scheduler.py` | 仅在原 `_start_tasks` 的成功日志处增加候选名次、比较对象和依据；动态和静态分别解释 | 让 CLI、网页和 JSON 中真实运行也能核对理由 |
| `data/policies/cases.json` | 独立存放 10 个带观察时刻、输入、推导与预期的排序案例 | 避免混入完整场景目录，补全并列与紧急标记边界 |
| `scripts/check_policies.py` | 一键核对、非法输入拒绝、失败退出码、完整归档；禁止归档覆盖输入 | 防止空集合假通过、错误预期被回写或证据不足 |
| `scripts/verify_policy_compatibility.py` | 两个独立进程运行基线/修改版，比较结果与逐边界状态摘要 | 可复现地核验原有行为是否一致 |
| `tests/test_policies.py` | 28 项排序、理由、输入不变、命令与真实引擎联调检查 | 覆盖此前局部测试遗漏的集成问题 |
| `tests/dashboard_browser.mjs` | 增加实际网页事件文本断言 | 确认页面收到真实排序理由 |
| `.github/workflows/verify.yml` | 增加排序案例核对与结果归档步骤 | 后续提交时自动复验案例 |
| 文档与验证记录 | 排序说明、接口变化、分工交接、演示入口及本记录 | 使代码、报告口径和现场操作一致 |

## 核心保护与影响

`models.py`、`resources.py`、`deadlock.py`、`metrics.py`、`scenarios.py`、`scenario_io.py`、`run_demo.py`、`dashboard_server.py`、`assets/dashboard-app.js` 和 `config.json` 已与基线逐字节比较，全部一致，SHA-256 记录在 `policies-validation.json`。

引擎仍调用原来的 `_ready_tasks()` 一次并按同一列表尝试；抢占、容量、资源申请、拒绝原因、等待图、执行推进、回滚、完成时间和统计计算没有改写。引擎文件的实际改动是导入解释函数、取得名次，以及补充成功事件文本和 `ordering` 字段。

对用户可见的变化是：CLI 和网页事件能显示“候选第几位、相对谁、哪个键决定了次序”；JSON 的 `start/resume/stage_start` 增加 `ordering`，`reason` 从固定英文摘要变为具体中文说明。事件数量、类型、时刻与业务字段不变，源码摘要随代码变化。依赖旧 `reason` 完整字符串的外部工具需要改读结构化字段。

名次是候选尝试列表中的位置。排前仍可能因资源受阻，后面的其他资源任务可以运行；静态队列不会因新任务优先级高而伪造重排理由。日志变长会略增结果体积与格式化工作量；本轮没有进行性能提升评测。

## 本地验证结果

| 检查 | 结果 |
|---|---|
| 原始主分支全量 Python 测试 | 68 项通过 |
| 修复后全量测试，Python 3.12.3 | 96 项通过 |
| 修复后全量测试，Python 3.10.21 | 96 项通过 |
| 预先列明的排序案例 | 10/10 通过 |
| 浏览器回归，Node 22 + Microsoft Edge | 21 项通过，含排序理由文本断言，无未捕获页面错误 |
| 混合负载回归 | 20 个种子 × 5 种策略，100 次通过 |
| 原有 CLI、死锁三组、JSON 输入、CSV 导出 | 通过 |
| 原实验指标手算入口 | 通过 |
| Python 编译与空白检查 | 通过 |

最关键的行为对比共 119 对运行：5 个固定策略、3 组死锁、11 份现有演示 JSON、100 份固定种子负载。共核对 4,192 个边界快照。每份完整结果、任务状态、资源账本、运行集合、等待请求、指标，以及全部事件的顺序/时刻/业务负载均一致。

比较只排除了本次有意变化的三类成功事件的 `reason/ordering`，以及版本/源码等 `metadata`；未排除任何任务字段、指标、其他事件或资源字段。结果为 `all_equal=true`，没有差异。摘要证据见 [policies-validation.json](policies-validation.json)；每次运行的摘要和完整本地日志位于 `results/policies/`。

本轮在 Ubuntu 24.04 本机验证。没有提交代码，因此没有新的远端 CI 运行；本地浏览器使用 Microsoft Edge，CI 配置使用 Chromium。软件回归不等于教师目标机器已经验收，也不重新认定其他成员的正式实验结论。

## 复核命令

在当前待审阅工作区执行：

```bash
cd /home/hanzhhh/桌面/26_OS-policies-review
python3 -m unittest discover -s tests -v
python3 scripts/check_policies.py --no-archive
python3 run_demo.py --scenario baseline --view trace
python3 run_demo.py --scenario no_dynamic --view trace
```

行为对比可用一个临时基线工作区重现：

```bash
git worktree add --detach /tmp/teaflow-policies-base 027d38a8c9d04c224b9a2091b2b25f1a411f840b
python3 scripts/verify_policy_compatibility.py --baseline-root /tmp/teaflow-policies-base
git worktree remove /tmp/teaflow-policies-base
```

此命令使用同一 Python 解释器分别运行两个版本，不混用模块；输出只排除上述已声明字段。脚本是本次排序修复的兼容性核对入口，不是所有未来功能变化都必须满足的统一约束。

## 提交与发布

建议提交标题：`fix: complete policy ordering validation and runtime explanations`。

提交说明位于 `results/policies/commit-message.txt`，PR 说明位于 `results/policies/pr-description.md`，补丁位于 `results/policies/pr3-policies.patch`。本轮修复从已验证的主分支创建独立分支，由 MacSwimmm 账户发布修复 PR，检查通过后合并并关闭被替代的原 PR #3。具体提交和自动检查结果通过 GitHub 对应记录核对。
