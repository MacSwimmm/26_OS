"""Discrete-event scheduler for the tea-break service scenario."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .deadlock import build_wait_for_graph, choose_recovery_victim, find_cycles
from .models import Interrupt, InterruptType, Metrics, SchedulerConfig, Task, TaskState
from .resources import ResourceManager


class Scheduler:
    def __init__(self, tasks: Iterable[Task], resources, config: SchedulerConfig | None = None,
                 interrupts: Iterable[Interrupt] = ()) -> None:
        self.config = config or SchedulerConfig()
        self.tasks: dict[str, Task] = {task.task_id: task for task in tasks}
        self.resource_manager = ResourceManager(resources, self.config.banker_enabled)
        self.interrupts = sorted(interrupts, key=lambda event: event.at)
        self.interrupt_index = 0
        self.running: list[str] = []
        self.waiting_requests: dict[str, dict[str, int]] = {}
        self.time = 0
        self.metrics = Metrics(
            total_tasks=len(self.tasks),
            urgent_tasks=sum(1 for task in self.tasks.values() if task.urgent),
        )
        self.trace: list[dict] = []
        self._busy_tick_count = 0

    def static_schedule(self) -> list[str]:
        """Return the initial priority/deadline order used by the paper."""

        return [task.task_id for task in sorted(
            self.tasks.values(), key=lambda task: (-task.priority, task.deadline, task.submitted_at)
        )]

    def _dependencies_ready(self, task: Task) -> bool:
        return all(self.tasks.get(dep) and self.tasks[dep].state == TaskState.COMPLETED
                   for dep in task.dependencies)

    def _ready_tasks(self) -> list[Task]:
        return sorted(
            (task for task in self.tasks.values()
             if task.state in (TaskState.PENDING, TaskState.READY, TaskState.BLOCKED)
             and task.submitted_at <= self.time and self._dependencies_ready(task)),
            key=lambda task: (-int(task.urgent), -task.priority, task.deadline, task.submitted_at),
        )

    def _record(self, event: str, **data) -> None:
        self.trace.append({"time": self.time, "event": event, **data})

    def _apply_interrupts(self) -> None:
        while self.interrupt_index < len(self.interrupts) and self.interrupts[self.interrupt_index].at <= self.time:
            event = self.interrupts[self.interrupt_index]
            self.interrupt_index += 1
            self._record("interrupt", kind=event.kind.value, description=event.description)
            if event.kind == InterruptType.URGENT and event.task is not None:
                event.task.submitted_at = self.time
                event.task.urgent = True
                self.tasks[event.task.task_id] = event.task
                self.metrics.total_tasks += 1
                self.metrics.urgent_tasks += 1
                self._record("urgent_submitted", task_id=event.task.task_id)
                if self.config.dynamic_rescheduling and self.config.preemptive:
                    self._preempt_for_urgent(event.task)
            elif event.kind == InterruptType.ENVIRONMENT and event.resource:
                resource = self.resource_manager.resources[event.resource]
                resource.blocked_until = max(resource.blocked_until, self.time + event.duration)
                self._record("resource_blocked", resource=event.resource, until=resource.blocked_until)
                if self.config.dynamic_rescheduling:
                    for task_id in list(self.running):
                        task = self.tasks[task_id]
                        if event.resource in task.resources and task.preemptible and self.config.preemptive:
                            self._preempt(task, "environment interruption")
            elif event.kind == InterruptType.FAULT and event.target_task_id:
                self._cancel_task(event.target_task_id, "fault interruption")

    def _preempt_for_urgent(self, urgent: Task) -> None:
        if len(self.running) < self.config.workers:
            return
        candidates = [self.tasks[task_id] for task_id in self.running if self.tasks[task_id].preemptible]
        if not candidates:
            return
        victim = min(candidates, key=lambda task: (task.priority, task.urgent, -task.remaining))
        if victim.priority < urgent.priority or not victim.urgent:
            self._preempt(victim, f"preempted by {urgent.task_id}")

    def _preempt(self, task: Task, reason: str) -> None:
        if task.task_id not in self.running:
            return
        task.saved_remaining = task.remaining
        task.preemptions += 1
        self.metrics.preemptions += 1
        self.running.remove(task.task_id)
        self.resource_manager.release(task.task_id)
        task.state = TaskState.READY
        self._record("preempt", task_id=task.task_id, reason=reason, remaining=task.remaining)

    def _cancel_task(self, task_id: str, reason: str) -> None:
        task = self.tasks.get(task_id)
        if not task or task.is_finished:
            return
        if task_id in self.running:
            self.running.remove(task_id)
        self.resource_manager.release(task_id)
        task.state = TaskState.CANCELLED
        task.finished_at = self.time
        self.metrics.cancelled_tasks += 1
        self._record("cancel", task_id=task_id, reason=reason)

    def _start_tasks(self) -> None:
        for task in self._ready_tasks():
            if len(self.running) >= self.config.workers:
                break
            if task.task_id in self.running:
                continue
            result = self.resource_manager.try_acquire(task, self.tasks, self.time)
            if not result.granted:
                task.state = TaskState.BLOCKED
                self.waiting_requests[task.task_id] = dict(task.resources)
                self.metrics.conflicts += 1
                self._record("resource_wait", task_id=task.task_id, reason=result.reason)
                continue
            task.state = TaskState.RUNNING
            task.started_at = self.time if task.started_at is None else task.started_at
            self.running.append(task.task_id)
            self.waiting_requests.pop(task.task_id, None)
            self._record("start", task_id=task.task_id, name=task.name)

    def _finish_tasks(self) -> None:
        for task_id in list(self.running):
            task = self.tasks[task_id]
            task.remaining -= 1
            if task.remaining > 0:
                continue
            task.state = TaskState.COMPLETED
            task.finished_at = self.time + 1
            self.running.remove(task_id)
            self.resource_manager.release(task_id)
            self.waiting_requests.pop(task_id, None)
            self.metrics.completed_tasks += 1
            self.metrics.total_delay += task.completion_delay
            self._record("complete", task_id=task_id, delay=task.completion_delay)

    def _detect_and_recover(self) -> None:
        if not self.config.deadlock_detection or self.time % self.config.detection_period:
            return
        graph = build_wait_for_graph(self.resource_manager.allocation, self.waiting_requests)
        cycles = find_cycles(graph)
        if not cycles:
            return
        self.metrics.deadlocks += len(cycles)
        self._record("deadlock_detected", cycles=cycles)
        if not self.config.deadlock_recovery:
            return
        for cycle in cycles:
            victim_id = choose_recovery_victim(self.tasks, cycle)
            victim = self.tasks[victim_id]
            if victim.preemptible and victim.remaining < victim.duration:
                self._preempt(victim, "deadlock rollback")
                victim.remaining = victim.duration
                self.metrics.recoveries += 1
                self._record("rollback", task_id=victim_id)
            else:
                self._cancel_task(victim_id, "deadlock recovery cancellation")
                self.metrics.recoveries += 1

    def run(self) -> dict:
        self._record("static_order", order=self.static_schedule())
        for task in self.tasks.values():
            if task.submitted_at == 0:
                task.state = TaskState.READY
        while self.time < self.config.max_time:
            self._apply_interrupts()
            self._start_tasks()
            busy, capacity = self.resource_manager.utilization(self.time)
            self._busy_tick_count += int(bool(self.running))
            self.metrics.resource_capacity_ticks += capacity
            self.metrics.busy_ticks += busy
            self._detect_and_recover()
            self._finish_tasks()
            if all(task.is_finished for task in self.tasks.values()):
                break
            self.time += 1
        for task in self.tasks.values():
            if task.urgent and task.finished_at is None or (task.urgent and task.finished_at and task.finished_at > task.deadline):
                self.metrics.urgent_missed += 1
        self._record("stop", reason="all tasks finished" if all(t.is_finished for t in self.tasks.values()) else "max_time")
        return {
            "metrics": self.metrics.as_dict(),
            "tasks": {task_id: asdict(task) for task_id, task in self.tasks.items()},
            "trace": self.trace,
            "config": asdict(self.config),
        }
