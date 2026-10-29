"""Discrete-time scheduler with staged resource requests and recovery."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Iterable

from .deadlock import build_wait_for_graph, choose_recovery_victim, find_cycles
from .models import Interrupt, InterruptType, Metrics, SchedulerConfig, Task, TaskState
from .resources import ResourceManager


class Scheduler:
    def __init__(self, tasks: Iterable[Task], resources, config: SchedulerConfig | None = None,
                 interrupts: Iterable[Interrupt] = ()) -> None:
        task_list = list(tasks)
        self.tasks: dict[str, Task] = {task.task_id: task for task in task_list}
        if len(self.tasks) != len(task_list):
            raise ValueError("task ids must be unique")
        self._validate_dependencies()
        self.config = config or SchedulerConfig()
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
        self._active_cycles: set[tuple[str, ...]] = set()
        self._paused_until: dict[str, int] = {}
        self._response_times: list[int] = []
        self._initial_order = {task_id: index for index, task_id in enumerate(self.static_schedule())}
        if self.config.max_time <= 0 or self.config.detection_period <= 0:
            raise ValueError("max_time and detection_period must be positive")
        if self.config.workers <= 0:
            raise ValueError("workers must be positive")

    def _validate_dependencies(self) -> None:
        for task in self.tasks.values():
            unknown = set(task.dependencies) - self.tasks.keys()
            if unknown:
                raise ValueError(f"task {task.task_id} has unknown dependencies: {sorted(unknown)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task dependency graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dep in self.tasks[task_id].dependencies:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self.tasks:
            visit(task_id)

    def static_schedule(self) -> list[str]:
        return [task.task_id for task in sorted(
            (t for t in self.tasks.values() if t.submitted_at == 0),
            key=lambda task: (-task.priority, task.deadline, task.submitted_at, task.task_id),
        )]

    def _dependencies_ready(self, task: Task) -> bool:
        return all(self.tasks[dep].state == TaskState.COMPLETED for dep in task.dependencies)

    def _ready_tasks(self) -> list[Task]:
        candidates = [task for task in self.tasks.values()
                     if task.state in (TaskState.PENDING, TaskState.READY, TaskState.BLOCKED)
                     and task.submitted_at <= self.time and self._dependencies_ready(task)]
        if not self.config.dynamic_rescheduling:
            return sorted(candidates, key=lambda task: (
                self._initial_order.get(task.task_id, len(self._initial_order) + task.submitted_at),
                task.submitted_at, task.task_id,
            ))
        return sorted(
            candidates,
            key=lambda task: (-int(task.urgent), -task.priority, task.deadline,
                              task.submitted_at, task.task_id),
        )

    def _record(self, event: str, **data) -> None:
        self.trace.append({"time": self.time, "event": event, **data})

    def _pause(self, task: Task, reason: str, resume_at: int) -> None:
        if task.task_id in self.running:
            self.running.remove(task.task_id)
        task.saved_remaining = task.remaining
        task.state = TaskState.PAUSED
        self.resource_manager.release(task.task_id)
        self.waiting_requests.pop(task.task_id, None)
        self._paused_until[task.task_id] = resume_at
        self._record("pause", task_id=task.task_id, reason=reason,
                     remaining=task.remaining, resume_at=resume_at)

    def _preempt_for_urgent(self, urgent: Task) -> None:
        stage = urgent.current_stage
        desired = stage.resources if stage is not None else urgent.resources
        occupied = self.resource_manager.allocation
        candidates = [self.tasks[tid] for tid in self.running
                      if self.tasks[tid].preemptible and
                      (self.tasks[tid].current_stage is None or self.tasks[tid].current_stage.preemptible)
                      and (len(self.running) >= self.config.workers or any(
                          amount > 0 and occupied.get(tid, {}).get(resource, 0) > 0
                          for resource, amount in desired.items()))]
        if not candidates:
            return
        victim = min(candidates, key=lambda task: (task.priority, task.urgent, -int(task.remaining or 0)))
        if (len(self.running) >= self.config.workers or any(
            amount > 0 and occupied.get(victim.task_id, {}).get(resource, 0) > 0
            for resource, amount in desired.items())) and (victim.priority < urgent.priority or not victim.urgent):
            self._preempt(victim, f"preempted by {urgent.task_id}")

    def _preempt(self, task: Task, reason: str) -> None:
        if task.task_id not in self.running:
            return
        self._pause(task, reason, self.time)
        task.state = TaskState.READY
        task.preemptions += 1
        self.metrics.preemptions += 1
        self._paused_until.pop(task.task_id, None)
        self._record("preempt", task_id=task.task_id, reason=reason,
                     remaining=task.remaining, progress_preserved=True)

    def _resume_ready_tasks(self) -> None:
        for task_id, resume_at in list(self._paused_until.items()):
            task = self.tasks[task_id]
            stage = task.current_stage
            resources = stage.resources if stage is not None else task.resources
            resources_ready = all(
                self.time >= self.resource_manager.resources[name].blocked_until
                for name in resources if name in self.resource_manager.resources
            )
            if self.time >= resume_at and resources_ready:
                task.state = TaskState.READY
                self._paused_until.pop(task_id)
                self._record("resume_ready", task_id=task_id,
                             remaining=task.remaining, stage_index=task.stage_index)

    def _apply_interrupts(self) -> None:
        while self.interrupt_index < len(self.interrupts) and self.interrupts[self.interrupt_index].at <= self.time:
            event = self.interrupts[self.interrupt_index]
            self.interrupt_index += 1
            self._record("interrupt", kind=event.kind.value, description=event.description)
            if event.kind == InterruptType.URGENT and event.task is not None:
                if event.task.task_id in self.tasks:
                    raise ValueError(f"duplicate task id from interrupt: {event.task.task_id}")
                event.task.submitted_at = self.time
                event.task.arrival_time = self.time
                event.task.urgent = True
                self.tasks[event.task.task_id] = event.task
                self.metrics.total_tasks += 1
                self.metrics.urgent_tasks += 1
                self._record("urgent_submitted", task_id=event.task.task_id)
                if self.config.dynamic_rescheduling and self.config.preemptive:
                    self._preempt_for_urgent(event.task)
            elif event.kind in (InterruptType.ENVIRONMENT, InterruptType.FAULT):
                resume_at = event.end_at if event.end_at is not None else self.time + max(1, event.duration)
                resource_name = event.resource
                if resource_name:
                    if resource_name not in self.resource_manager.resources:
                        raise ValueError(f"unknown interrupted resource: {resource_name}")
                    resource = self.resource_manager.resources[resource_name]
                    resource.blocked_until = max(resource.blocked_until, resume_at)
                    self._record("resource_blocked", resource=resource_name, until=resource.blocked_until)
                    affected = [task for task in self.tasks.values()
                                if task.state == TaskState.RUNNING
                                and resource_name in (task.current_stage.resources if task.current_stage else task.resources)]
                else:
                    target = self.tasks.get(event.target_task_id or "")
                    affected = [target] if target is not None and target.task_id in self.running else []
                for task in affected:
                    self._pause(task, "fault interruption" if event.kind == InterruptType.FAULT
                                else "environment interruption", resume_at)
            elif event.kind == InterruptType.RESTORE and event.resource:
                if event.resource not in self.resource_manager.resources:
                    raise ValueError(f"unknown restored resource: {event.resource}")
                resource = self.resource_manager.resources[event.resource]
                resource.blocked_until = min(resource.blocked_until, self.time)
                for task_id in self._paused_until:
                    task = self.tasks[task_id]
                    stage = task.current_stage
                    needed = stage.resources if stage is not None else task.resources
                    if event.resource in needed:
                        self._paused_until[task_id] = min(self._paused_until[task_id], self.time)
                self._record("resource_restored", resource=event.resource)

    def _requested_resources(self, task: Task) -> dict[str, int]:
        stage = task.current_stage
        desired = stage.resources if stage is not None else task.resources
        held = self.resource_manager.allocation.get(task.task_id, {})
        return {name: amount - held.get(name, 0)
                for name, amount in desired.items() if amount > held.get(name, 0)}

    def _start_tasks(self) -> None:
        for task in self._ready_tasks():
            if len(self.running) >= self.config.workers:
                break
            request = self._requested_resources(task)
            result = self.resource_manager.try_acquire(task, self.tasks, self.time, request)
            if not result.granted:
                task.state = TaskState.BLOCKED
                previous_request = self.waiting_requests.get(task.task_id)
                self.waiting_requests[task.task_id] = request
                new_wait = previous_request != request
                self.metrics.conflicts += int(new_wait and result.reason == "resource unavailable")
                self.metrics.safety_rejections += int(new_wait and "safety" in result.reason.lower())
                self._record("resource_wait", task_id=task.task_id,
                             reason=result.reason, request=request)
                continue
            task.state = TaskState.RUNNING
            task.started_at = self.time if task.started_at is None else task.started_at
            self.running.append(task.task_id)
            self.waiting_requests.pop(task.task_id, None)
            self._record("start" if task.stage_index == 0 else "stage_start",
                         task_id=task.task_id,
                         stage=task.current_stage.name if task.current_stage else task.name,
                         stage_index=task.stage_index,
                         acquired=request)

    def _finish_tasks(self) -> None:
        for task_id in list(self.running):
            task = self.tasks[task_id]
            task.remaining = int(task.remaining or 0) - 1
            task.completed_work += 1
            stage = task.current_stage
            if task.remaining > 0:
                continue
            if stage is None:
                self._complete_task(task)
                continue
            for name in stage.release_resources:
                held = self.resource_manager.allocation.get(task_id, {})
                if name in held:
                    held.pop(name)
            if not self.resource_manager.allocation.get(task_id):
                self.resource_manager.release(task_id)
            task.stage_index += 1
            if task.stage_index >= len(task.stages):
                self._complete_task(task)
            else:
                task.remaining = task.current_stage.duration
                task.state = TaskState.READY
                self.running.remove(task_id)
                self._record("stage_complete", task_id=task_id,
                             completed_stage=stage.name, next_stage=task.current_stage.name)

    def _complete_task(self, task: Task) -> None:
        task.state = TaskState.COMPLETED
        task.finished_at = self.time + 1
        if task.task_id in self.running:
            self.running.remove(task.task_id)
        self.resource_manager.release(task.task_id)
        self.waiting_requests.pop(task.task_id, None)
        self.metrics.completed_tasks += 1
        self.metrics.total_delay += task.completion_delay
        self._response_times.append(int(task.response_time or 0))
        self._record("complete", task_id=task.task_id,
                     response_time=task.response_time, lateness=task.completion_delay)

    def _detect_and_recover(self) -> None:
        if not self.config.deadlock_detection or self.time % self.config.detection_period:
            return
        graph = build_wait_for_graph(self.resource_manager.allocation, self.waiting_requests)
        cycles = find_cycles(graph)
        current = {tuple(cycle) for cycle in cycles}
        self._active_cycles.intersection_update(current)
        new_cycles = [cycle for cycle in cycles if tuple(cycle) not in self._active_cycles]
        if not cycles:
            return
        if new_cycles:
            self.metrics.deadlocks += len(new_cycles)
            self._record("deadlock_detected", cycles=new_cycles)
            self._active_cycles.update(tuple(cycle) for cycle in new_cycles)
        if not self.config.deadlock_recovery:
            return
        for cycle in new_cycles:
            eligible = [tid for tid in cycle if self.tasks[tid].rollback_allowed]
            if not eligible:
                self._record("deadlock_unresolved", cycle=cycle, reason="no rollback-eligible task")
                continue
            victim_id = choose_recovery_victim(self.tasks, eligible)
            victim = self.tasks[victim_id]
            if victim.retry_count >= victim.max_retries:
                self._cancel_task(victim_id, "maximum rollback retries exceeded")
                self.metrics.recoveries += 1
                self._record("rollback_limit", task_id=victim_id,
                             retry_count=victim.retry_count)
                continue
            released = dict(self.resource_manager.allocation.get(victim_id, {}))
            if victim.task_id in self.running:
                self.running.remove(victim.task_id)
            self.resource_manager.release(victim_id)
            self.waiting_requests.pop(victim_id, None)
            checkpoint_work = sum(stage.duration for stage in victim.stages[:victim.checkpoint])
            lost_work = max(0, victim.completed_work - checkpoint_work)
            victim.rolled_back_work += lost_work
            self.metrics.rollback_work += lost_work
            self.metrics.rollback_count += 1
            victim.retry_count += 1
            victim.completed_work = checkpoint_work
            victim.stage_index = victim.checkpoint if victim.stages else 0
            victim.remaining = (victim.current_stage.duration if victim.current_stage
                                else victim.duration - checkpoint_work)
            victim.state = TaskState.READY
            self.metrics.recoveries += 1
            self._active_cycles.discard(tuple(cycle))
            self._record("rollback", task_id=victim_id, reason="lowest-priority rollback-eligible task",
                         lost_work=lost_work, retry_count=victim.retry_count,
                         released=released)

    def _account_resources(self) -> None:
        busy_count = 0
        capacity_count = 0
        for name, resource in self.resource_manager.resources.items():
            if self.time >= resource.blocked_until:
                self.metrics.resource_available_ticks[name] = self.metrics.resource_available_ticks.get(name, 0) + resource.capacity
                capacity_count += resource.capacity
            active = any(task_id in self.running and amount > 0
                         for task_id, held in self.resource_manager.allocation.items()
                         for held_name, amount in held.items() if held_name == name)
            if active:
                self.metrics.resource_busy_ticks[name] = self.metrics.resource_busy_ticks.get(name, 0) + 1
                busy_count += 1
        self.metrics.busy_ticks += busy_count
        self.metrics.resource_capacity_ticks += capacity_count

    def run(self, progress_callback: Callable[[int, dict[str, Task], list[dict]], None] | None = None) -> dict:
        self._record("static_order", order=self.static_schedule())
        for task in self.tasks.values():
            if task.submitted_at == 0:
                task.state = TaskState.READY
        reported_events = len(self.trace)
        while self.time < self.config.max_time:
            self._apply_interrupts()
            self._resume_ready_tasks()
            self._start_tasks()
            self._account_resources()
            self._detect_and_recover()
            self._finish_tasks()
            if progress_callback is not None:
                new_events = self.trace[reported_events:]
                progress_callback(self.time, self.tasks, new_events)
                reported_events = len(self.trace)
            all_finished = all(task.is_finished for task in self.tasks.values())
            no_future_events = self.interrupt_index >= len(self.interrupts)
            if all_finished and no_future_events:
                break
            self.time += 1
        for task in self.tasks.values():
            if task.urgent and task.deadline <= self.config.max_time and (
                task.state != TaskState.COMPLETED or task.finished_at is None or task.finished_at > task.deadline
            ):
                self.metrics.urgent_missed += 1
        self.metrics.total_tasks = sum(
            task.submitted_at <= self.config.max_time for task in self.tasks.values()
        )
        self.metrics.urgent_tasks = sum(
            task.urgent and task.submitted_at <= self.config.max_time for task in self.tasks.values()
        )
        stop_reason = "all tasks finished" if all(t.is_finished for t in self.tasks.values()) else "max_time"
        self._record("stop", reason=stop_reason)
        result_metrics = self.metrics.as_dict()
        average_response = (
            round(sum(self._response_times) / len(self._response_times), 4)
            if self._response_times else None
        )
        result_metrics["average_response_time"] = average_response
        result_metrics["average_completion_delay"] = average_response
        return {
            "metrics": result_metrics,
            "tasks": {task_id: asdict(task) for task_id, task in self.tasks.items()},
            "trace": self.trace,
            "config": asdict(self.config),
            "stop_reason": stop_reason,
        }

    def _cancel_task(self, task_id: str, reason: str) -> None:
        task = self.tasks.get(task_id)
        if not task or task.is_finished:
            return
        if task_id in self.running:
            self.running.remove(task_id)
        self.resource_manager.release(task_id)
        self.waiting_requests.pop(task_id, None)
        task.state = TaskState.CANCELLED
        task.finished_at = self.time
        self.metrics.cancelled_tasks += 1
        self._record("cancel", task_id=task_id, reason=reason)
