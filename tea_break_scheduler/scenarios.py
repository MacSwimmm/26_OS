"""Deterministic scenarios used by the demo and the comparison table."""

from __future__ import annotations

from copy import deepcopy

from .models import Interrupt, InterruptType, Resource, SchedulerConfig, Task, TaskStage
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
            description="维护操作位短暂故障，暂停后恢复任务",
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
    """Run the same staged task input under avoidance and recovery policies."""

    def deadlock_tasks() -> list[Task]:
        return [
            Task("A", "整理茶歇台后转移物品", 2, 30, 2,
                 stages=[TaskStage("占用茶歇台", 1, {"tea_table": 1}),
                         TaskStage("申请回收区", 1, {"return_station": 1})],
                 rollback_allowed=True),
            Task("B", "占用回收区后整理台面", 1, 30, 2,
                 stages=[TaskStage("占用回收区", 1, {"return_station": 1}),
                         TaskStage("申请茶歇台", 1, {"tea_table": 1})],
                 rollback_allowed=True),
        ]

    def run_variant(banker: bool, detect: bool, recover: bool) -> dict:
        scheduler = Scheduler(deadlock_tasks(),
                              {"tea_table": Resource("tea_table"),
                               "return_station": Resource("return_station")},
                              SchedulerConfig(workers=2, banker_enabled=banker,
                                              deadlock_detection=detect,
                                              deadlock_recovery=recover,
                                              max_time=20))
        return scheduler.run()

    return {
        "avoidance": run_variant(True, True, False),
        "detection_only": run_variant(False, True, False),
        "detection_and_recovery": run_variant(False, True, True),
    }
