"""Fixed, inspectable course demonstrations; every variant reuses identical inputs."""
from __future__ import annotations
from dataclasses import replace

from .models import Interrupt, InterruptType, Resource, SchedulerConfig, Task, TaskStage
from .scheduler import Scheduler


VARIANTS = ("baseline", "fcfs", "no_dynamic", "no_deadlock", "non_preemptive")


def resources() -> dict[str, Resource]:
    return {name: Resource(name, shared=name == "request_board") for name in
            ("tea_table", "cup_station", "return_station", "corridor", "request_board")}


def delivery(tid="T1", at=0, urgent=False) -> Task:
    return Task(tid, "紧急送水杯" if urgent else "递送水杯到 A 区", 3 if urgent else 2,
                at + (5 if urgent else 14), 4 if not urgent else 2,
                submitted_at=at, urgent=urgent, task_type="delivery", stages=[
                    TaskStage("取杯", 1, {"cup_station": 1, "request_board": 1}, ["cup_station", "request_board"]),
                    TaskStage("通道配送", 1 if urgent else 3, {"corridor": 1}, ["corridor"]),
                ])


def recycle(tid="R1", at=0) -> Task:
    return Task(tid, "回收空杯", 1, at + 18, 4, submitted_at=at, task_type="recycle", stages=[
        TaskStage("前往台面", 1, {"corridor": 1}, ["corridor"]),
        TaskStage("台面收集", 2, {"tea_table": 1}, preemptible=False),
        TaskStage("原子转移至回收区", 1, {"tea_table": 1, "return_station": 1},
                  ["tea_table", "return_station"], preemptible=False),
    ])


def tasks() -> list[Task]:
    return [delivery(),
            Task("T2", "整理茶歇台", 1, 18, 6, resources={"tea_table": 1}, task_type="maintenance"),
            Task("T3", "回收后最终整理", 1, 30, 2, dependencies=["R1"],
                 resources={"tea_table": 1}, task_type="maintenance")]


def interrupts() -> list[Interrupt]:
    return [
        Interrupt(2, InterruptType.URGENT, "客户临时请求送水杯", task=delivery("U1", 2, True)),
        Interrupt(5, InterruptType.ENVIRONMENT, "通道临时关闭", resource="corridor", duration=2),
        Interrupt(3, InterruptType.FAULT, "茶歇台操作位故障", resource="tea_table", duration=2),
        Interrupt(6, InterruptType.CUP_TAKEN, "A 区杯子已取走", task=recycle("R1", 6), cup_id="cup-A"),
        Interrupt(7, InterruptType.CUP_TAKEN, "重复杯子事件应忽略", task=recycle("R1", 7), cup_id="cup-A"),
        Interrupt(8, InterruptType.REQUEST, "普通送水请求", task=delivery("T4", 8)),
    ]


def config_for(variant: str, base: SchedulerConfig | None = None) -> SchedulerConfig:
    base = base or SchedulerConfig()
    changes = {"baseline": {}, "fcfs": {"policy": "fcfs"},
               "no_dynamic": {"dynamic_rescheduling": False},
               "no_deadlock": {"banker_enabled": False, "deadlock_recovery": False},
               "non_preemptive": {"preemptive": False}}
    if variant not in changes:
        raise ValueError(f"unknown scenario: {variant}")
    return replace(base, **changes[variant])


def build_scheduler(variant: str = "baseline") -> Scheduler:
    return Scheduler(tasks(), resources(), config_for(variant), interrupts())


def run_comparison() -> dict[str, dict]:
    return {variant: build_scheduler(variant).run() for variant in VARIANTS}


def deadlock_tasks() -> list[Task]:
    # Reversible synthetic reservation stages, distinct from irreversible business work.
    return [
        Task("A", "TABLE → RECYCLE 预留", 2, 30, 2, rollback_allowed=True, stages=[
            TaskStage("预留茶歇台", 1, {"tea_table": 1}, preemptible=False),
            TaskStage("申请回收区", 1, {"return_station": 1}, preemptible=False)]),
        Task("B", "RECYCLE → TABLE 预留", 1, 30, 2, rollback_allowed=True, stages=[
            TaskStage("预留回收区", 1, {"return_station": 1}, preemptible=False),
            TaskStage("申请茶歇台", 1, {"tea_table": 1}, preemptible=False)]),
    ]


def deadlock_demo() -> dict:
    return {name: Scheduler(deadlock_tasks(),
                           {r: Resource(r) for r in ("tea_table", "return_station")},
                           SchedulerConfig(banker_enabled=banker, deadlock_recovery=recover, max_time=20)).run()
            for name, banker, recover in (("avoidance", True, False), ("detection_only", False, False),
                                         ("detection_and_recovery", False, True))}
