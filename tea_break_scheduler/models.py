"""Validated input models and runtime state (Python 3.10+)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def require_int(name: str, value: int, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def validate_claim(claim: dict[str, int]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("resource claims must be an object")
    for name, amount in claim.items():
        if not isinstance(name, str) or not name:
            raise ValueError("resource names must be nonempty strings")
        require_int("resource claim", amount, 1)


class TaskState(str, Enum):
    PENDING = "pending"       # NEW in the design specification
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"       # WAITING: reason distinguishes dependencies/resources
    PAUSED = "paused"
    COMPLETED = "completed"   # DONE
    CANCELLED = "cancelled"   # CANCELED


class InterruptType(str, Enum):
    REQUEST = "request"
    CUP_TAKEN = "cup_taken"
    URGENT = "urgent"
    ENVIRONMENT = "environment"
    FAULT = "fault"
    RESTORE = "restore"


@dataclass
class Resource:
    """Mutex resources have one instance; shared resources are read-only."""
    name: str
    capacity: int = 1
    shared: bool = False
    blocked_until: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("resource name is required")
        if type(self.shared) is not bool:
            raise ValueError("shared must be a boolean")
        require_int("capacity", self.capacity, 1)
        require_int("blocked_until", self.blocked_until)
        if not self.shared and self.capacity != 1:
            raise ValueError("wait-for cycle detection requires single-instance mutex resources")


@dataclass
class TaskStage:
    name: str
    duration: int
    resources: dict[str, int] = field(default_factory=dict)
    release_resources: list[str] = field(default_factory=list)
    preemptible: bool = True

    def __post_init__(self) -> None:
        if type(self.preemptible) is not bool:
            raise ValueError("preemptible must be a boolean")
        if not isinstance(self.release_resources, list) or any(not isinstance(r, str) for r in self.release_resources):
            raise ValueError("release_resources must be a list of resource names")
        require_int("stage duration", self.duration, 1)
        validate_claim(self.resources)
        if len(set(self.release_resources)) != len(self.release_resources):
            raise ValueError("duplicate resource release")


@dataclass
class Task:
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
    redo_remaining: int = 0
    redone_work: int = 0
    waiting_reason: str = ""
    task_type: str = "service"

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id is required")
        if not isinstance(self.dependencies, list) or any(not isinstance(d, str) for d in self.dependencies):
            raise ValueError("dependencies must be a list of task ids")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("dependencies must be unique")
        if not isinstance(self.stages, list) or any(not isinstance(stage, TaskStage) for stage in self.stages):
            raise ValueError("stages must contain TaskStage objects")
        for name in ("preemptible", "urgent", "rollback_allowed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        require_int("duration", self.duration, 1)
        require_int("priority", self.priority)
        require_int("deadline", self.deadline)
        require_int("submitted_at", self.submitted_at)
        require_int("max_retries", self.max_retries)
        require_int("checkpoint", self.checkpoint)
        if self.arrival_time is not None and self.arrival_time != self.submitted_at:
            raise ValueError("arrival_time and submitted_at must agree")
        self.arrival_time = self.submitted_at
        if self.task_id in self.dependencies:
            raise ValueError("task cannot depend on itself")
        validate_claim(self.resources)
        if self.stages and sum(s.duration for s in self.stages) != self.duration:
            raise ValueError("duration must equal the sum of stage durations")
        if self.stages and self.resources:
            raise ValueError("use stages or legacy resources, not both")
        if self.checkpoint > self.stage_index:
            raise ValueError("checkpoint cannot refer to future work")
        if not self.max_claim:
            self.max_claim = dict(self.resources)
            for stage in self.stages:
                for name, amount in stage.resources.items():
                    self.max_claim[name] = max(self.max_claim.get(name, 0), amount)
        validate_claim(self.max_claim)
        for claim in [self.resources] + [stage.resources for stage in self.stages]:
            if any(amount > self.max_claim.get(name, 0) for name, amount in claim.items()):
                raise ValueError("max_claim must cover every stage resource request")
        self.remaining = self.stages[0].duration if self.stages else self.duration

    @property
    def is_finished(self) -> bool:
        return self.state in (TaskState.COMPLETED, TaskState.CANCELLED)

    @property
    def completion_delay(self) -> int:
        return max(0, self.finished_at - self.deadline) if self.finished_at is not None else 0

    @property
    def current_stage(self) -> TaskStage | None:
        return self.stages[self.stage_index] if self.stage_index < len(self.stages) else None

    @property
    def response_time(self) -> int | None:
        return None if self.finished_at is None else self.finished_at - self.submitted_at


@dataclass(frozen=True)
class Interrupt:
    at: int
    kind: InterruptType
    description: str
    task: Task | None = None
    resource: str | None = None
    duration: int = 0
    target_task_id: str | None = None
    end_at: int | None = None
    cup_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", InterruptType(self.kind))
        if self.task is not None and not isinstance(self.task, Task):
            raise ValueError("event task must be a Task")
        require_int("event time", self.at)
        require_int("event duration", self.duration)
        if self.end_at is not None:
            require_int("end_at", self.end_at)
            if self.end_at <= self.at:
                raise ValueError("end_at must be after the interrupt")
        if self.kind in (InterruptType.REQUEST, InterruptType.URGENT, InterruptType.CUP_TAKEN):
            if self.task is None:
                raise ValueError("arrival events require a task")
        if self.kind == InterruptType.CUP_TAKEN and not self.cup_id:
            raise ValueError("cup_taken requires cup_id for deduplication")
        if self.kind in (InterruptType.FAULT, InterruptType.ENVIRONMENT):
            if not self.resource and not self.target_task_id:
                raise ValueError("interruption requires a resource or target task")
            if self.end_at is None and self.duration <= 0:
                raise ValueError("interruption requires a positive duration or end_at")
        if self.kind == InterruptType.RESTORE and not self.resource:
            raise ValueError("restore requires a resource")


@dataclass
class SchedulerConfig:
    workers: int | None = None  # Optional extension; default model has no staff limit.
    dynamic_rescheduling: bool = True
    preemptive: bool = True
    banker_enabled: bool = True
    deadlock_detection: bool = True
    deadlock_recovery: bool = True
    max_time: int = 200
    detection_period: int = 1
    policy: str = "priority"

    def __post_init__(self) -> None:
        for name in ("dynamic_rescheduling", "preemptive", "banker_enabled", "deadlock_detection", "deadlock_recovery"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        require_int("max_time", self.max_time, 1)
        require_int("detection_period", self.detection_period, 1)
        if self.workers is not None:
            require_int("workers", self.workers, 1)
        if self.policy not in ("priority", "fcfs"):
            raise ValueError("policy must be priority or fcfs")
        if self.deadlock_recovery and not self.deadlock_detection:
            raise ValueError("deadlock recovery requires detection")


@dataclass
class Metrics:
    total_tasks: int = 0
    completed_tasks: int = 0
    cancelled_tasks: int = 0
    urgent_tasks: int = 0
    urgent_missed: int = 0
    total_delay: int = 0
    total_response: int = 0
    on_time_tasks: int = 0
    conflicts: int = 0
    deadlocks: int = 0
    recoveries: int = 0
    preemptions: int = 0
    safety_rejections: int = 0
    rollback_count: int = 0
    rollback_work: int = 0
    redo_work: int = 0
    resource_busy_ticks: dict[str, int] = field(default_factory=dict)
    resource_held_ticks: dict[str, int] = field(default_factory=dict)
    resource_available_ticks: dict[str, int] = field(default_factory=dict)
    resource_outage_ticks: dict[str, int] = field(default_factory=dict)
    resource_outage_held_ticks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        ratio = lambda a, b: round(a / b, 4) if b else None
        util = {name: ratio(self.resource_busy_ticks.get(name, 0), ticks)
                for name, ticks in self.resource_available_ticks.items()}
        occupancy = {name: ratio(self.resource_held_ticks.get(name, 0), ticks)
                     for name, ticks in self.resource_available_ticks.items()}
        defined = [value for value in util.values() if value is not None]
        return {
            "total_tasks": self.total_tasks, "completed_tasks": self.completed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "unfinished_tasks": self.total_tasks - self.completed_tasks - self.cancelled_tasks,
            "completion_rate": ratio(self.completed_tasks, self.total_tasks),
            "on_time_completion_rate": ratio(self.on_time_tasks, self.total_tasks),
            "average_completion_delay": ratio(self.total_response, self.completed_tasks),
            "average_response_time": ratio(self.total_response, self.completed_tasks),
            "average_lateness": ratio(self.total_delay, self.completed_tasks),
            "resource_utilization": round(sum(defined) / len(defined), 4) if defined else None,
            "resource_utilization_by_resource": util,
            "resource_occupancy_by_resource": occupancy,
            "resource_busy_ticks": dict(self.resource_busy_ticks),
            "resource_held_ticks": dict(self.resource_held_ticks),
            "resource_available_ticks": dict(self.resource_available_ticks),
            "resource_outage_ticks": dict(self.resource_outage_ticks),
            "resource_outage_held_ticks": dict(self.resource_outage_held_ticks),
            "deadlock_count": self.deadlocks, "conflict_count": self.conflicts,
            "urgent_eligible_tasks": self.urgent_tasks, "urgent_missed_tasks": self.urgent_missed,
            "urgent_task_miss_rate": ratio(self.urgent_missed, self.urgent_tasks),
            "recoveries": self.recoveries, "preemptions": self.preemptions,
            "safety_rejection_count": self.safety_rejections,
            "rollback_count": self.rollback_count, "rollback_work": self.rollback_work,
            "redo_work": self.redo_work,
        }


TASK_INPUT_FIELDS = ("task_id", "name", "priority", "deadline", "duration", "dependencies",
                     "resources", "preemptible", "urgent", "submitted_at", "stages", "max_claim",
                     "rollback_allowed", "max_retries", "task_type")


def task_from_dict(data: dict[str, Any]) -> Task:
    data = dict(data)
    if set(data) - set(TASK_INPUT_FIELDS):
        raise ValueError("scenario task contains unsupported or runtime fields")
    data["stages"] = [TaskStage(**stage) for stage in data.get("stages", [])]
    return Task(**data)
