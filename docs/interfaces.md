# 模块接口与数据约定

## 入口

```python
from tea_break_scheduler.scenarios import build_scheduler
scheduler = build_scheduler("baseline")
result = scheduler.run(progress_callback=None)
```

每次运行新建引擎。输入会深复制，不因一组实验改变另一组。`run()` 只能调用一次；结束结果由 JSON 可序列化字典组成。`progress_callback(t, tasks, events)` 在执行 `[t,t+1)` 前及终止边界调用；任务对象仅供读取，需自行复制后保留。服务端使用 `asdict` 创建独立快照，不把可变引用当作历史。

## 排序、资源与死锁

- `policies.order_tasks(tasks, "fcfs" | "priority") -> list[Task]`：返回新列表，不改变输入状态。
- `ResourceManager.try_acquire(task, arrived_tasks, t, request) -> AllocationResult`：增量、原子申请；成功返回 `granted=True`，失败返回原因。未知资源、负数、超过 Max 等非法输入抛 `ValueError`。
- 失败原因：`resource occupied`、`resource outage`、`Banker safety check rejected request`，分别表示所有权冲突、暂不可用和不安全。
- `release(task_id, names=None)`：释放指定资源或全部资源。通过 `allocation[task_id]` 查询账目，外部不应直接修改。
- `request_is_safe(BankerState, task_id, request)`：试分配，不修改原状态；`is_safe` 返回 `(bool, safe_order)`。
- `build_wait_for_graph(allocation, waiting)`、`find_cycles(graph)`：只接真实的占用等待请求，不接依赖/故障/安全拒绝。

引擎统一处理状态切换、计数、中断和回滚；排序函数与基础资源接口不应独立推进时间。

## JSON 场景输入（schema_version=1）

```json
{
  "schema_version": 1,
  "seed": null,
  "resources": {"tea_table": {"capacity": 1}},
  "config": {"max_time": 10, "policy": "priority"},
  "tasks": [
    {"task_id": "A", "name": "整理台面", "priority": 1,
     "deadline": 8, "duration": 2, "resources": {"tea_table": 1}}
  ],
  "events": []
}
```

`python3 run_demo.py --input data/demos/basic.json` 为可运行示例。任务必填 `task_id/name/priority/deadline/duration`；可选 `submitted_at`、`dependencies`、`preemptible`、`urgent`、`rollback_allowed`、`max_retries`、`task_type`、`max_claim`、`stages`。单阶段 `resources` 与 `stages` 二选一。输入不接受 `state/remaining/finished_at/checkpoint` 等运行时字段。

阶段结构：`{"name":"整理", "duration":2, "resources":{"tea_table":1}, "release_resources":["tea_table"], "preemptible":true}`。未列入释放清单的占用保留到后续阶段；任务完成时全部释放。Max 未填写时由各阶段声明保守推导。

事件 `kind` 可取：

| kind | 额外字段 | 行为 |
|---|---|---|
| `request` | `task` | 普通请求 |
| `urgent` | `task` | 紧急请求，强制 urgent 标记；优先级仍由任务指定 |
| `cup_taken` | `task`、`cup_id` | 首次创建该杯子的回收任务，重复事件忽略 |
| `environment` / `fault` | `resource` 或 `target_task_id`，以及 `duration>0` 或 `end_at>at` | 有限暂停 |
| `restore` | `resource` | 显式恢复资源当前关闭状态 |

所有事件必填 `at/kind/description`。事件到达时间覆盖嵌入任务的 `submitted_at`；初始与事件任务合并校验依赖和唯一编号，重复杯子事件除外。时间、资源量必须为整数，开关必须为布尔值。

配置默认：`max_time=200`、`workers=null`、`policy="priority"`，动态、抢占、银行家、检测、恢复均开启，`detection_period=1`。恢复依赖检测，不允许启恢复却关检测。检测仅支持单实例互斥资源。

## 结果（metadata.schema_version=2）

- `input`：实际输入任务、资源、事件、配置和种子，可保存后再次传给 `--input`。
- `tasks`：最终运行状态，包括阶段、工作量、等待原因、检查点、重试和完成时间；含未来输入任务。
- `trace`：按非递减边界时刻记录事件，包含原因、申请、释放、丢失量和恢复信息。
- `metrics`：定义见 `docs/experiments.md`，无定义值用 `null`。
- `unfinished`：窗口内未完成任务的 `age/remaining_work/reason`。
- `config/observation_horizon/elapsed_time/stop_reason`：配置、统一窗口、执行结束时刻、原因。
- `metadata`：Python、系统、Git 提交、是否修改、源码摘要、输入摘要、负载摘要及种子；Git 不可用时相应字段为 `null`。

`source_sha256` 覆盖调度包所有 Python 源码；`workload_sha256` 覆盖任务、资源和事件，不包含策略配置。判断同种子对照是否共用负载时使用后者。

## HTTP 与网页快照

启动 `python3 dashboard_server.py --host 127.0.0.1 --port 8765`。

| 接口 | 响应 |
|---|---|
| `GET /api/health` | 引擎可用状态与 schema 版本 |
| `GET /api/config` | 默认外观设置 |
| `GET /api/scenarios` | 场景编号、名称 |
| `POST /api/run`，body=`{"scenario":"baseline"}` | 单场景结果与边界快照 |
| 同接口 `compare` / `deadlock` | `comparisons` 指标表与 `results` 原始结果 |

单场景返回 `scenario/label/result/snapshots`。每个快照含 `time/tasks/resources/events/metrics`，只展示已到达任务；任务额外含 `stage_name/held_resources/waiting_request`；资源含 `capacity/shared/available/blocked_until/holders`。`available=0` 可能由故障造成，不代表一定有人占用；网页占用量从 `holders` 计算。

服务一次性计算快照，浏览器按速度回放。页面上的“运行中”是模拟时钟播放状态；这不是硬件遥测。输入体限 1 MB；非法 JSON、场景名或对象形状返回 400；静态资源使用白名单。
