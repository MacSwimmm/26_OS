"""Atomic resource ownership. Finite outages and Banker safety are distinct checks."""
from __future__ import annotations
from dataclasses import dataclass

from .deadlock import BankerState, request_is_safe
from .models import Resource, Task, validate_claim


@dataclass
class AllocationResult:
    granted: bool
    reason: str = ""


class ResourceManager:
    def __init__(self, resources: dict[str, Resource], banker_enabled: bool = True) -> None:
        self.resources = resources
        self.banker_enabled = banker_enabled
        self.allocation: dict[str, dict[str, int]] = {}

    def physical_available(self) -> dict[str, int]:
        return {name: resource.capacity - sum(held.get(name, 0) for held in self.allocation.values())
                for name, resource in self.resources.items() if not resource.shared}

    def available(self, now: int) -> dict[str, int]:
        physical = self.physical_available()
        return {name: (physical.get(name, resource.capacity) if now >= resource.blocked_until else 0)
                for name, resource in self.resources.items()}

    def banker_state(self, tasks: dict[str, Task], now: int) -> BankerState:
        # Finite outages are handled by pause/resume. The safe sequence assumes
        # the documented eventual restoration of physical resource capacity.
        maximum = {tid: {r: n for r, n in task.max_claim.items() if not self.resources[r].shared}
                   for tid, task in tasks.items() if not task.is_finished and task.submitted_at <= now}
        return BankerState(self.physical_available(), self.allocation, maximum)

    def try_acquire(self, task: Task, tasks: dict[str, Task], now: int,
                    request: dict[str, int] | None = None) -> AllocationResult:
        request = task.resources if request is None else request
        validate_claim(request)
        held = self.allocation.get(task.task_id, {})
        if any(name not in self.resources for name in request):
            raise ValueError("unknown resource")
        if any(held.get(name, 0) + amount > task.max_claim.get(name, 0)
               or (not self.resources[name].shared and amount > self.resources[name].capacity)
               for name, amount in request.items()):
            raise ValueError("request exceeds max_claim or resource capacity")
        if any(now < self.resources[name].blocked_until for name in request):
            return AllocationResult(False, "resource outage")
        mutex_request = {r: n for r, n in request.items() if not self.resources[r].shared}
        available = self.physical_available()
        if any(n > available[r] for r, n in mutex_request.items()):
            return AllocationResult(False, "resource occupied")
        if mutex_request and self.banker_enabled and not request_is_safe(
                self.banker_state(tasks, now), task.task_id, mutex_request):
            return AllocationResult(False, "Banker safety check rejected request")
        if mutex_request:
            held = self.allocation.setdefault(task.task_id, {})
            for name, amount in mutex_request.items():
                held[name] = held.get(name, 0) + amount
        return AllocationResult(True, "granted")

    def release(self, task_id: str, names: list[str] | None = None) -> None:
        if names is None:
            self.allocation.pop(task_id, None)
            return
        held = self.allocation.get(task_id, {})
        for name in names:
            held.pop(name, None)
        if not held:
            self.allocation.pop(task_id, None)
