# 本模块只产生候选任务的排序视图，不修改任务状态、资源账本或事件队列。
from .models import Task


def order_tasks(tasks: list[Task], policy: str) -> list[Task]:
    # 返回 sorted 新列表，避免策略函数改变调用者持有的任务顺序。
    if policy == "fcfs":
        # 同一到达时刻按 ID 稳定排序，保证重复运行结果一致。
        return sorted(tasks, key=lambda t: (t.submitted_at, t.task_id))
    if policy == "priority":
        # priority 越大越靠前；其余键依次用截止时间、到达时刻和 ID 打破平局。
        return sorted(tasks, key=lambda t: (-t.priority, t.deadline, t.submitted_at, t.task_id))
    raise ValueError(f"unknown ordering policy: {policy}")


def selection_reason(policy: str) -> str:
    # 将排序依据写入事件日志，方便复核调度器选择顺序。
    return ("FCFS: arrival, task id" if policy == "fcfs" else
            "priority: higher priority, earlier deadline, arrival, task id")
