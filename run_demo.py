#!/usr/bin/env python3
"""Run a live console demo or write machine-readable simulation results."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tea_break_scheduler.models import Task, TaskState
from tea_break_scheduler.scenarios import build_scheduler, deadlock_demo, run_comparison


STATE_LABELS = {
    TaskState.PENDING: "未到达",
    TaskState.READY: "就绪",
    TaskState.RUNNING: "运行",
    TaskState.BLOCKED: "等待资源",
    TaskState.PAUSED: "暂停",
    TaskState.COMPLETED: "完成",
    TaskState.CANCELLED: "撤销",
}
EVENT_LABELS = {
    "urgent_submitted": "紧急任务到达",
    "preempt": "抢占",
    "pause": "中断暂停",
    "resume_ready": "恢复就绪",
    "resource_wait": "资源等待",
    "deadlock_detected": "检测到死锁",
    "rollback": "回滚恢复",
    "deadlock_unresolved": "死锁未解除",
    "complete": "任务完成",
    "cancel": "任务撤销",
    "resource_blocked": "资源关闭",
    "resource_restored": "资源恢复",
}


def _task_status(task: Task) -> str:
    label = STATE_LABELS[task.state]
    stage = task.current_stage.name if task.current_stage else task.name
    if task.state == TaskState.RUNNING:
        return f"{label}:{stage} 剩余{task.remaining}"
    if task.state == TaskState.BLOCKED:
        return f"{label}:{stage}"
    return label


def _progress_row(now: int, tasks: dict[str, Task], events: list[dict], delay: float) -> None:
    active = [f"{task.task_id} {task.name}({_task_status(task)})"
              for task in tasks.values()
              if task.state in (TaskState.RUNNING, TaskState.BLOCKED, TaskState.PAUSED)]
    recent = []
    for event in events:
        label = EVENT_LABELS.get(event["event"])
        if label:
            task = event.get("task_id", "")
            reason = event.get("reason", "")
            recent.append(f"{label} {task} {reason}".strip())
    active_text = "；".join(active) if active else "当前无活动任务"
    event_text = " | ".join(recent[-4:]) if recent else "本步无新事件"
    print(f"t={now:>3}  {active_text}  ||  {event_text}", flush=True)
    if delay:
        time.sleep(delay)


def _print_result_table(name: str, result: dict) -> None:
    metrics = result["metrics"]
    print(f"\n{name}：{result.get('stop_reason', '已结束')}")
    print("任务       状态       到达  开始  完成  剩余")
    for task_id, task in result["tasks"].items():
        state = TaskState(task["state"])
        fmt = lambda value: "-" if value is None else str(value)
        print(f"{task_id:<10} {STATE_LABELS[state]:<8} {task['submitted_at']:>4}  "
              f"{fmt(task['started_at']):>4}  {fmt(task['finished_at']):>4}  {task['remaining']:>4}")
    print("\n关键指标")
    for label, key in (
        ("完成率", "completion_rate"),
        ("平均响应时间", "average_response_time"),
        ("平均逾期时长", "average_lateness"),
        ("资源利用率", "resource_utilization"),
        ("死锁次数", "deadlock_count"),
        ("资源冲突", "conflict_count"),
        ("安全性拒绝", "safety_rejection_count"),
        ("紧急任务错失率", "urgent_task_miss_rate"),
        ("抢占次数", "preemptions"),
        ("回滚次数/重做工作量", "rollback_count"),
    ):
        value = metrics.get(key)
        if value is not None:
            if key == "rollback_count":
                value = f"{value} / {metrics.get('rollback_work', 0)}"
            print(f"  {label}: {value}")
    resources = metrics.get("resource_utilization_by_resource", {})
    if resources:
        print("  逐资源利用率: " + ", ".join(
            f"{resource}={value if value is not None else 'N/A'}"
            for resource, value in resources.items()
        ))


def _print_comparison(results: dict[str, dict]) -> None:
    print("方案                 完成率  平均响应  紧急错失  死锁  抢占  回滚")
    for name, result in results.items():
        metrics = result["metrics"]
        show = lambda value: "N/A" if value is None else str(value)
        print(f"{name:<20} {metrics['completion_rate']:>6}  "
              f"{show(metrics['average_response_time']):>8}  "
              f"{show(metrics['urgent_task_miss_rate']):>8}  "
              f"{metrics['deadlock_count']:>4}  {metrics['preemptions']:>4}  "
              f"{metrics['rollback_count']:>4}")


def main() -> int:
    parser = argparse.ArgumentParser(description="茶歇服务员任务调度仿真")
    parser.add_argument("--scenario", choices=["baseline", "no_dynamic", "no_deadlock",
                                                 "non_preemptive", "compare", "deadlock"],
                        default="baseline")
    parser.add_argument("--output", type=Path, help="write full JSON results to this path")
    parser.add_argument("--view", choices=["summary", "trace", "json"], default="summary",
                        help="summary table, event trace, or full JSON (default: summary)")
    parser.add_argument("--live", action="store_true", help="print one progress row per simulation tick")
    parser.add_argument("--delay", type=float, default=0.25,
                        help="seconds between live progress rows (default: 0.25)")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    if args.scenario == "deadlock":
        result = deadlock_demo()
        if args.view == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_comparison(result)
    elif args.scenario == "compare":
        result = run_comparison()
        if args.view == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_comparison(result)
    else:
        scheduler = build_scheduler(args.scenario)
        callback = (lambda now, tasks, events: _progress_row(now, tasks, events, args.delay)) if args.live else None
        result = scheduler.run(progress_callback=callback)
        if args.view == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not args.live:
                print("仿真已结束。运行中观察过程请添加 --live。")
            _print_result_table(args.scenario, result)
            if args.view == "trace":
                print("\n事件轨迹")
                for event in result["trace"]:
                    label = EVENT_LABELS.get(event["event"], event["event"])
                    print(f"t={event['time']:>3}  {label}: "
                          f"{event.get('task_id', '')} {event.get('reason', event.get('description', ''))}".rstrip())

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完整 JSON 已保存：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
