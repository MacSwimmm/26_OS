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
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InterruptType(str, Enum):
    URGENT = "urgent"
    ENVIRONMENT = "environment"
    FAULT = "fault"
    RESTORE = "restore"


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

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("resource capacity must be positive")


@dataclass
class TaskStage:
    """One execution stage and its incremental resource claim."""

    name: str
    duration: int
    resources: dict[str, int] = field(default_factory=dict)
    release_resources: list[str] = field(default_factory=list)
    preemptible: bool = True

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("stage duration must be positive")
        if any(amount <= 0 for amount in self.resources.values()):
            raise ValueError("stage resource claims must be positive")


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
    stages: list[TaskStage] = field(default_factory=list)
    max_claim: dict[str, int] = field(default_factory=dict)
    rollback_allowed: bool = False
    checkpoint: int = 0
    retry_count: int = 0
    max_retries: int = 3
    arrival_time: int | None = None
    completed_work: int = 0
    rolled_back_work: int = 0
    stage_index: int = 0

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("duration must be positive")
        if self.deadline < 0:
            raise ValueError("deadline must be non-negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.checkpoint < 0:
            raise ValueError("checkpoint must be non-negative")
        if self.remaining is None:
            self.remaining = self.duration
        if self.arrival_time is None:
            self.arrival_time = self.submitted_at
        if any(dep == self.task_id for dep in self.dependencies):
            raise ValueError("task cannot depend on itself")
        if not self.max_claim:
            self.max_claim = dict(self.resources)
            for stage in self.stages:
                for resource, amount in stage.resources.items():
                    self.max_claim[resource] = max(self.max_claim.get(resource, 0), amount)
        for resource, amount in self.resources.items():
            if amount < 0 or self.max_claim.get(resource, 0) < amount:
                raise ValueError("max_claim must cover task resource requirements")
        for stage in self.stages:
            if any(self.max_claim.get(resource, 0) < amount
                   for resource, amount in stage.resources.items()):
                raise ValueError("max_claim must cover every stage resource request")
        if self.stages:
            self.remaining = self.stages[0].duration
            if self.checkpoint < 0 or self.checkpoint > len(self.stages):
                raise ValueError("checkpoint must be a valid completed-stage index")

    @property
    def is_finished(self) -> bool:
        return self.state in (TaskState.COMPLETED, TaskState.CANCELLED)

    @property
    def completion_delay(self) -> int:
        if self.finished_at is None:
            return 0
        return max(0, self.finished_at - self.deadline)

    @property
    def current_stage(self) -> TaskStage | None:
        if not self.stages or self.stage_index >= len(self.stages):
            return None
        return self.stages[self.stage_index]

    @property
    def response_time(self) -> int | None:
        if self.finished_at is None:
            return None
        return self.finished_at - int(self.arrival_time or 0)


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
    end_at: int | None = None


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
    safety_rejections: int = 0
    rollback_count: int = 0
    rollback_work: int = 0
    resource_busy_ticks: dict[str, int] = field(default_factory=dict)
    resource_available_ticks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, float | int]:
        completion_rate = self.completed_tasks / self.total_tasks if self.total_tasks else 0.0
        average_delay = self.total_delay / self.completed_tasks if self.completed_tasks else None
        utilization = self.busy_ticks / self.resource_capacity_ticks if self.resource_capacity_ticks else None
        urgent_miss_rate = self.urgent_missed / self.urgent_tasks if self.urgent_tasks else None
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "completion_rate": round(completion_rate, 4),
            "average_completion_delay": round(average_delay, 4) if average_delay is not None else None,
            "average_lateness": round(self.total_delay / self.completed_tasks, 4) if self.completed_tasks else None,
            "resource_utilization": round(utilization, 4) if utilization is not None else None,
            "deadlock_count": self.deadlocks,
            "conflict_count": self.conflicts,
            "urgent_task_miss_rate": round(urgent_miss_rate, 4) if urgent_miss_rate is not None else None,
            "recoveries": self.recoveries,
            "preemptions": self.preemptions,
            "safety_rejection_count": self.safety_rejections,
            "rollback_count": self.rollback_count,
            "rollback_work": self.rollback_work,
            "resource_utilization_by_resource": {
                name: round(self.resource_busy_ticks.get(name, 0) / available, 4) if available else None
                for name, available in self.resource_available_ticks.items()
            },
        }


def task_from_dict(data: dict[str, Any]) -> Task:
    """Small helper for loading a task list from JSON in future extensions."""

    return Task(**data)
