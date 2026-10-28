"""Resource allocation with atomic requests and Banker checks."""

from __future__ import annotations

from dataclasses import dataclass

from .deadlock import BankerState, request_is_safe
from .models import Resource, Task


@dataclass
class AllocationResult:
    granted: bool
    reason: str = ""


class ResourceManager:
    def __init__(self, resources: dict[str, Resource], banker_enabled: bool = True) -> None:
        self.resources = resources
        self.banker_enabled = banker_enabled
        self.allocation: dict[str, dict[str, int]] = {}

    def available(self, now: int) -> dict[str, int]:
        result: dict[str, int] = {}
        for name, resource in self.resources.items():
            used = sum(values.get(name, 0) for values in self.allocation.values())
            result[name] = max(0, resource.capacity - used) if now >= resource.blocked_until else 0
        return result

    def banker_state(self, tasks: dict[str, Task], now: int) -> BankerState:
        maximum = {task_id: dict(task.resources) for task_id, task in tasks.items()}
        return BankerState(self.available(now), self.allocation, maximum)

    def try_acquire(self, task: Task, tasks: dict[str, Task], now: int) -> AllocationResult:
        if any(name not in self.resources for name in task.resources):
            return AllocationResult(False, "unknown resource")
        available = self.available(now)
        if any(amount > available.get(name, 0) for name, amount in task.resources.items()):
            return AllocationResult(False, "resource unavailable")
        if self.banker_enabled:
            state = self.banker_state(tasks, now)
            if not request_is_safe(state, task.task_id, task.resources):
                return AllocationResult(False, "Banker safety check rejected request")
        self.allocation[task.task_id] = dict(task.resources)
        return AllocationResult(True, "granted")

    def release(self, task_id: str) -> None:
        self.allocation.pop(task_id, None)

    def force_allocate(self, task_id: str, resource: str, amount: int = 1) -> None:
        """Only used by the deterministic deadlock demonstration/test."""

        self.allocation.setdefault(task_id, {})[resource] = amount

    def utilization(self, now: int) -> tuple[int, int]:
        busy = sum(sum(values.values()) for values in self.allocation.values())
        capacity = sum(resource.capacity if now >= resource.blocked_until else 0
                       for resource in self.resources.values())
        return busy, capacity
