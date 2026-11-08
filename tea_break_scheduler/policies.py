"""Pure candidate ordering; this module never changes tasks or allocations."""
from .models import Task


def order_tasks(tasks: list[Task], policy: str) -> list[Task]:
    if policy == "fcfs":
        return sorted(tasks, key=lambda t: (t.submitted_at, t.task_id))
    if policy == "priority":
        return sorted(tasks, key=lambda t: (-t.priority, t.deadline, t.submitted_at, t.task_id))
    raise ValueError(f"unknown ordering policy: {policy}")


def selection_reason(policy: str) -> str:
    return ("FCFS: arrival, task id" if policy == "fcfs" else
            "priority: higher priority, earlier deadline, arrival, task id")
