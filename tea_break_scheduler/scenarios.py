# 固定 workload 用于讲解机制和回归验证，不应当作经真实业务采样校准的统计数据。
from __future__ import annotations
from dataclasses import replace

from .models import Interrupt, InterruptType, Resource, SchedulerConfig, Task, TaskStage
from .scheduler import Scheduler


VARIANTS = ("baseline", "fcfs", "no_dynamic", "no_deadlock", "non_preemptive")


def resources() -> dict[str, Resource]:
    # request_board 是共享只读信息，不进入互斥占用账本或等待图。
    return {name: Resource(name, shared=name == "request_board") for name in
            ("tea_table", "cup_station", "return_station", "corridor", "request_board")}


def delivery(tid="T1", at=0, urgent=False) -> Task:
    # 取杯和通道配送拆成两个阶段，分别观察各资源的占用区间。
    return Task(tid, "紧急送水杯" if urgent else "递送水杯到 A 区", 3 if urgent else 2,
                at + (5 if urgent else 14), 4 if not urgent else 2,
                submitted_at=at, urgent=urgent, task_type="delivery", stages=[
                    TaskStage("取杯", 1, {"cup_station": 1, "request_board": 1}, ["cup_station", "request_board"]),
                    TaskStage("通道配送", 1 if urgent else 3, {"corridor": 1}, ["corridor"]),
                ])


def recycle(tid="R1", at=0) -> Task:
    # 最后的转移阶段同时持有台面和回收区，且不可抢占，用于保护原子操作。
    return Task(tid, "回收空杯", 1, at + 18, 4, submitted_at=at, task_type="recycle", stages=[
        TaskStage("前往台面", 1, {"corridor": 1}, ["corridor"]),
        TaskStage("台面收集", 2, {"tea_table": 1}, preemptible=False),
        TaskStage("原子转移至回收区", 1, {"tea_table": 1, "return_station": 1},
                  ["tea_table", "return_station"], preemptible=False),
    ])


def tasks() -> list[Task]:
    # T3 依赖事件在 t=6 创建的 R1，展示动态到达的前置任务约束。
    return [delivery(),
            Task("T2", "整理茶歇台", 1, 18, 6, resources={"tea_table": 1}, task_type="maintenance"),
            Task("T3", "回收后最终整理", 1, 30, 2, dependencies=["R1"],
                 resources={"tea_table": 1}, task_type="maintenance")]


def interrupts() -> list[Interrupt]:
    # 外部请求、故障和重复杯子事件都按模拟时间注入，由调度器统一排序处理。
    return [
        Interrupt(2, InterruptType.URGENT, "客户临时请求送水杯", task=delivery("U1", 2, True)),
        Interrupt(5, InterruptType.ENVIRONMENT, "通道临时关闭", resource="corridor", duration=2),
        Interrupt(3, InterruptType.FAULT, "茶歇台操作位故障", resource="tea_table", duration=2),
        Interrupt(6, InterruptType.CUP_TAKEN, "A 区杯子已取走", task=recycle("R1", 6), cup_id="cup-A"),
        Interrupt(7, InterruptType.CUP_TAKEN, "重复杯子事件应忽略", task=recycle("R1", 7), cup_id="cup-A"),
        Interrupt(8, InterruptType.REQUEST, "普通送水请求", task=delivery("T4", 8)),
    ]


def config_for(variant: str, base: SchedulerConfig | None = None) -> SchedulerConfig:
    # 每个对照只覆盖目标开关，其余字段沿用相同基线，避免混入额外变量。
    base = base or SchedulerConfig()
    changes = {"baseline": {}, "fcfs": {"policy": "fcfs"},
               "no_dynamic": {"dynamic_rescheduling": False},
               "no_deadlock": {"banker_enabled": False, "deadlock_recovery": False},
               "non_preemptive": {"preemptive": False}}
    if variant not in changes:
        raise ValueError(f"unknown scenario: {variant}")
    return replace(base, **changes[variant])


def build_scheduler(variant: str = "baseline") -> Scheduler:
    # 每次重新创建可变输入，确保不同实验实例之间不共享运行状态。
    return Scheduler(tasks(), resources(), config_for(variant), interrupts())


def run_comparison() -> dict[str, dict]:
    # 对照组复用相同场景数据，只改变 config_for 指定的调度配置。
    return {variant: build_scheduler(variant).run() for variant in VARIANTS}


def deadlock_tasks() -> list[Task]:
    # A 先取台面再申请回收区，B 以相反顺序申请，从而形成可复现的循环等待。
    # 这里模拟可回滚的资源预留，不代表可以回滚真实的不可逆服务操作。
    return [
        Task("A", "TABLE → RECYCLE 预留", 2, 30, 2, rollback_allowed=True, stages=[
            TaskStage("预留茶歇台", 1, {"tea_table": 1}, preemptible=False),
            TaskStage("申请回收区", 1, {"return_station": 1}, preemptible=False)]),
        Task("B", "RECYCLE → TABLE 预留", 1, 30, 2, rollback_allowed=True, stages=[
            TaskStage("预留回收区", 1, {"return_station": 1}, preemptible=False),
            TaskStage("申请茶歇台", 1, {"tea_table": 1}, preemptible=False)]),
    ]


def deadlock_demo() -> dict:
    # 三组共用任务与资源，只改变银行家避免和检测后恢复两个配置。
    return {name: Scheduler(deadlock_tasks(),
                           {r: Resource(r) for r in ("tea_table", "return_station")},
                           SchedulerConfig(banker_enabled=banker, deadlock_recovery=recover, max_time=20)).run()
            for name, banker, recover in (("avoidance", True, False), ("detection_only", False, False),
                                         ("detection_and_recovery", False, True))}
