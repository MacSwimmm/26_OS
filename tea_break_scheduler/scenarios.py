"""Deterministic scenarios used by the demo and the comparison table."""

from __future__ import annotations

from copy import deepcopy

from .models import Interrupt, InterruptType, Resource, SchedulerConfig, Task
from .scheduler import Scheduler


def resources() -> dict[str, Resource]:
    return {
        "tea_table": Resource("tea_table", capacity=1, shared=False),
        "cup_station": Resource("cup_station", capacity=1, shared=False),
        "return_station": Resource("return_station", capacity=1, shared=False),
        "corridor": Resource("corridor", capacity=1, shared=False),
    }


def tasks() -> list[Task]:
    return [
        Task("T1", "递送水杯到 A 区", priority=5, deadline=10, duration=4,
             resources={"cup_station": 1, "corridor": 1}, preemptible=True),
        Task("T2", "整理茶歇台", priority=3, deadline=14, duration=5,
             resources={"tea_table": 1, "corridor": 1}, preemptible=True),
        Task("T3", "回收空杯", priority=4, deadline=12, duration=4,
             dependencies=["T1"], resources={"return_station": 1, "corridor": 1}, preemptible=True),
        Task("T4", "补充杯子", priority=2, deadline=25, duration=3,
             resources={"cup_station": 1, "tea_table": 1}, preemptible=False),
    ]


def interrupts() -> list[Interrupt]:
    return [
        Interrupt(
            at=2,
            kind=InterruptType.URGENT,
            description="客户临时请求送水杯",
            task=Task("U1", "紧急送水杯", priority=10, deadline=7, duration=3,
                      resources={"cup_station": 1, "corridor": 1}, urgent=True),
        ),
        Interrupt(
            at=5,
            kind=InterruptType.ENVIRONMENT,
            description="通道被顾客短暂占用",
            resource="corridor",
            duration=2,
        ),
        Interrupt(
            at=11,
            kind=InterruptType.FAULT,
            description="回收区传感器故障，取消维护任务",
            target_task_id="T4",
        ),
    ]


def build_scheduler(variant: str = "baseline") -> Scheduler:
    configs = {
        "baseline": SchedulerConfig(dynamic_rescheduling=True, preemptive=True,
                                     banker_enabled=True, deadlock_detection=True,
                                     deadlock_recovery=True),
        "no_dynamic": SchedulerConfig(dynamic_rescheduling=False, preemptive=False,
                                       banker_enabled=True, deadlock_detection=True,
                                       deadlock_recovery=True),
        "no_deadlock": SchedulerConfig(dynamic_rescheduling=True, preemptive=True,
                                        banker_enabled=False, deadlock_detection=False,
                                        deadlock_recovery=False),
        "non_preemptive": SchedulerConfig(dynamic_rescheduling=True, preemptive=False,
                                           banker_enabled=True, deadlock_detection=True,
                                           deadlock_recovery=True),
    }
    if variant not in configs:
        raise ValueError(f"unknown scenario: {variant}")
    return Scheduler(deepcopy(tasks()), resources(), configs[variant], deepcopy(interrupts()))


def run_comparison() -> dict[str, dict]:
    return {variant: build_scheduler(variant).run() for variant in
            ("baseline", "no_dynamic", "no_deadlock", "non_preemptive")}


def deadlock_demo() -> dict:
    """Return a small two-task cycle for the paper's RAG figure."""

    from .deadlock import build_wait_for_graph, find_cycles

    allocation = {"A": {"tea_table": 1}, "B": {"return_station": 1}}
    waiting = {"A": {"return_station": 1}, "B": {"tea_table": 1}}
    graph = build_wait_for_graph(allocation, waiting)
    serializable_graph = {task_id: sorted(owners) for task_id, owners in graph.items()}
    return {"allocation": allocation, "waiting": waiting, "wait_for_graph": serializable_graph,
            "cycles": find_cycles(graph)}
