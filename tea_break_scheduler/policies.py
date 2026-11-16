# 本模块只产生候选任务的排序视图，不修改任务状态、资源账本或事件队列。
# 基于 PR #3 的排序交付补齐；实际贡献以提交记录为准。
from __future__ import annotations

from .models import Task

FCFS = "fcfs"
PRIORITY = "priority"
POLICIES = (FCFS, PRIORITY)


def _validate_policy(policy: str) -> None:
    if policy not in POLICIES:
        raise ValueError(f"unknown ordering policy: {policy}")


def _key(task: Task, policy: str) -> tuple:
    # 单一处定义全序键：策略差异只体现在这里，避免两处维护导致不一致。
    if policy == FCFS:
        # 同一到达时刻按 ID 稳定排序，保证重复运行结果一致。
        return (task.submitted_at, task.task_id)
    if policy == PRIORITY:
        # priority 越大越靠前；其余键依次用截止时间、到达时刻和 ID 打破平局。
        return (-task.priority, task.deadline, task.submitted_at, task.task_id)
    raise ValueError(f"unknown ordering policy: {policy}")


def order_tasks(tasks: list[Task], policy: str) -> list[Task]:
    # 先显式校验策略名：sorted 对空列表不会调用 key，只在 key 里抛错会漏掉空候选集的情况。
    _validate_policy(policy)
    # 返回 sorted 新列表，避免策略函数改变调用者持有的任务顺序。
    return sorted(tasks, key=lambda task: _key(task, policy))


def explain(task: Task, runner_up: Task | None, policy: str) -> str:
    # 说明 task 为什么排在 runner_up 之前；runner_up 为 None 表示已到末位。
    # 只描述实际排序键；不将 urgent 属性误写为额外优先规则。
    _validate_policy(policy)
    if runner_up is None:
        return "其后无候选"
    left, right = _key(task, policy), _key(runner_up, policy)
    if left > right:
        raise ValueError("task must precede runner_up in the requested policy")
    if left == right:
        return "排序键相同，保留输入次序"

    if policy == FCFS:
        if task.submitted_at != runner_up.submitted_at:
            return f"到达更早（{task.submitted_at} < {runner_up.submitted_at}）"
        return f"同到达时间，按任务编号先后（{task.task_id} < {runner_up.task_id}）"

    # 理由只描述实际决定顺序的字段（priority / deadline / submitted_at / task_id）。
    # urgent 不在排序键里，不能出现在理由中，否则会让人误以为它影响排序。
    if task.priority != runner_up.priority:
        return f"优先级更高（{task.priority} > {runner_up.priority}）"
    if task.deadline != runner_up.deadline:
        return f"同优先级，截止时间更早（{task.deadline} < {runner_up.deadline}）"
    if task.submitted_at != runner_up.submitted_at:
        return f"同优先级、同截止时间，到达更早（{task.submitted_at} < {runner_up.submitted_at}）"
    return f"同优先级、同截止时间、同到达时间，按任务编号（{task.task_id} < {runner_up.task_id}）"


def rank_tasks(tasks: list[Task], policy: str) -> list[tuple[Task, str]]:
    # 与 order_tasks 完全同一套键，额外给出每个位置的排序理由，供事件日志引用。
    ordered = order_tasks(tasks, policy)
    ranked: list[tuple[Task, str]] = []
    for index, task in enumerate(ordered):
        runner_up = ordered[index + 1] if index + 1 < len(ordered) else None
        ranked.append((task, explain(task, runner_up, policy)))
    return ranked


def format_ranking(tasks: list[Task], policy: str) -> str:
    # 一行摘要，便于演示脚本和日志直接打印。
    return " -> ".join(task.task_id for task in order_tasks(tasks, policy))


def selection_reason(policy: str) -> str:
    # 保留原接口：说明该策略整体的排序依据，写入运行配置或报告。
    _validate_policy(policy)
    if policy == FCFS:
        return "FCFS: arrival, task id"
    if policy == PRIORITY:
        return "priority: higher priority, earlier deadline, arrival, task id"
    raise ValueError(f"unknown ordering policy: {policy}")
