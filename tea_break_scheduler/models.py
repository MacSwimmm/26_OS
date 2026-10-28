"""Data models used by the tea-break scheduling simulator.

The dataclasses deliberately keep the same fields that are required in the
course rubric, so they can be copied directly into the mathematical model in
the paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InterruptType(str, Enum):
    URGENT = "urgent"
    ENVIRONMENT = "environment"
    FAULT = "fault"


@dataclass
class Resource:
    """A shared or mutex resource.

    ``capacity`` is normally one for the tea table and corridor.  A capacity
    greater than one can model several identical trays or collection slots.
    """

    name: str
    capacity: int = 1
    shared: bool = False
    blocked_until: int = 0


@dataclass
class Task:
    """A schedulable service request."""

    task_id: str
    name: str
    priority: int
    deadline: int
    duration: int
    dependencies: list[str] = field(default_factory=list)
    resources: dict[str, int] = field(default_factory=dict)
    preemptible: bool = True
    urgent: bool = False
    submitted_at: int = 0
    state: TaskState = TaskState.PENDING
    remaining: int | None = None
    started_at: int | None = None
    finished_at: int | None = None
    preemptions: int = 0
    saved_remaining: int | None = None

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("duration must be positive")
        if self.deadline < 0:
            raise ValueError("deadline must be non-negative")
        if self.remaining is None:
            self.remaining = self.duration

    @property
    def is_finished(self) -> bool:
        return self.state in (TaskState.COMPLETED, TaskState.CANCELLED)

    @property
    def completion_delay(self) -> int:
        if self.finished_at is None:
            return 0
        return max(0, self.finished_at - self.deadline)


@dataclass(frozen=True)
class Interrupt:
    """An event that forces a scheduling decision at a simulation time."""

    at: int
    kind: InterruptType
    description: str
    task: Task | None = None
    resource: str | None = None
    duration: int = 0
    target_task_id: str | None = None


@dataclass
class SchedulerConfig:
    workers: int = 2
    dynamic_rescheduling: bool = True
    preemptive: bool = True
    banker_enabled: bool = True
    deadlock_detection: bool = True
    deadlock_recovery: bool = True
    max_time: int = 100
    detection_period: int = 1


@dataclass
class Metrics:
    """Aggregated measurements used in the report."""

    total_tasks: int = 0
    completed_tasks: int = 0
    cancelled_tasks: int = 0
    urgent_tasks: int = 0
    urgent_missed: int = 0
    total_delay: int = 0
    busy_ticks: int = 0
    resource_capacity_ticks: int = 0
    conflicts: int = 0
    deadlocks: int = 0
    recoveries: int = 0
    preemptions: int = 0

    def as_dict(self) -> dict[str, float | int]:
        completion_rate = self.completed_tasks / self.total_tasks if self.total_tasks else 0.0
        average_delay = self.total_delay / self.completed_tasks if self.completed_tasks else 0.0
        utilization = self.busy_ticks / self.resource_capacity_ticks if self.resource_capacity_ticks else 0.0
        urgent_miss_rate = self.urgent_missed / self.urgent_tasks if self.urgent_tasks else 0.0
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "completion_rate": round(completion_rate, 4),
            "average_completion_delay": round(average_delay, 4),
            "resource_utilization": round(utilization, 4),
            "deadlock_count": self.deadlocks,
            "conflict_count": self.conflicts,
            "urgent_task_miss_rate": round(urgent_miss_rate, 4),
            "recoveries": self.recoveries,
            "preemptions": self.preemptions,
        }


def task_from_dict(data: dict[str, Any]) -> Task:
    """Small helper for loading a task list from JSON in future extensions."""

    return Task(**data)
