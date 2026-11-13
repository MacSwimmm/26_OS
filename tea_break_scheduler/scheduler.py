# 确定性离散事件循环：t 时刻的快照描述 [t, t+1) 执行区间开始前的状态。
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from types import MappingProxyType
from typing import Callable, Iterable

from .deadlock import build_wait_for_graph, choose_recovery_victim, find_cycles
from .models import Interrupt, InterruptType, Metrics, SchedulerConfig, Task, TaskState
from .policies import order_tasks, selection_reason
from .resources import ResourceManager


class Scheduler:
    def __init__(self, tasks: Iterable[Task], resources, config: SchedulerConfig | None = None,
                 interrupts: Iterable[Interrupt] = ()) -> None:
        # 深复制输入，隔离不同实验之间的任务状态和资源账本。
        task_list = deepcopy(list(tasks))
        self.tasks = {task.task_id: task for task in task_list}
        if len(self.tasks) != len(task_list):
            raise ValueError("task ids must be unique")
        self.config = deepcopy(config or SchedulerConfig())
        self.interrupts = sorted(deepcopy(list(interrupts)), key=lambda e: e.at)
        self.resource_manager = ResourceManager(deepcopy(resources), self.config.banker_enabled)
        self._validate_inputs()
        from .scenario_io import scenario_document
        self.input_document = scenario_document(self.tasks.values(), resources, self.config, self.interrupts)
        self.interrupt_index = 0
        self.running: list[str] = []
        self.waiting_requests: dict[str, dict[str, int]] = {}
        self.time = 0
        names = [r for r, resource in resources.items() if not resource.shared]
        self.metrics = Metrics(**{field: dict.fromkeys(names, 0) for field in (
            "resource_busy_ticks", "resource_held_ticks", "resource_available_ticks",
            "resource_outage_ticks", "resource_outage_held_ticks")})
        self.trace: list[dict] = []
        self._active_cycles: set[tuple[str, ...]] = set()
        self._paused_until: dict[str, int] = {}
        self._wait_keys: dict[str, tuple] = {}
        self._seen_cups: set[str] = set()
        self._arrived: set[str] = set()
        self._outages: set[str] = {name for name, r in resources.items() if r.blocked_until > 0}
        self._has_run = False
        self.request_board = MappingProxyType({})
        self._initial_order = {tid: i for i, tid in enumerate(self.static_schedule())}

    def _validate_inputs(self) -> None:
        # 同时检查事件中携带的未来任务，避免仿真启动后才遇到重复 ID 或无效依赖。
        resources = self.resource_manager.resources
        if any(name != resource.name for name, resource in resources.items()):
            raise ValueError("resource map key must match resource.name")
        known = dict(self.tasks)
        cups: set[str] = set()
        for event in self.interrupts:
            if event.resource and event.resource not in resources:
                raise ValueError(f"unknown interrupted resource: {event.resource}")
            if event.resource and resources[event.resource].shared:
                raise ValueError("read-only shared data is not a faultable mutex resource")
            if event.task is None:
                continue
            if event.kind == InterruptType.CUP_TAKEN and event.cup_id in cups:
                continue
            if event.kind == InterruptType.CUP_TAKEN:
                cups.add(event.cup_id)
            task = event.task
            if task.task_id in known:
                raise ValueError(f"duplicate task id from event: {task.task_id}")
            task.submitted_at = task.arrival_time = event.at
            known[task.task_id] = task
        for event in self.interrupts:
            if event.target_task_id and event.target_task_id not in known:
                raise ValueError(f"unknown interrupt target: {event.target_task_id}")
        for task in known.values():
            if task.state != TaskState.PENDING or task.stage_index or task.completed_work:
                raise ValueError("scheduler input must contain fresh tasks")
            if set(task.dependencies) - known.keys():
                raise ValueError(f"task {task.task_id} has unknown dependencies")
            for name, amount in task.max_claim.items():
                if name not in resources:
                    raise ValueError(f"unknown resource: {name}")
                if amount > resources[name].capacity:
                    raise ValueError(f"max_claim exceeds resource capacity: {name}")
            held: dict[str, int] = {}
            for stage in task.stages:
                held.update(stage.resources)
                if set(stage.release_resources) - held.keys():
                    raise ValueError("stage releases a resource it cannot hold")
                for name in stage.release_resources:
                    held.pop(name, None)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(tid: str) -> None:
            if tid in visiting:
                raise ValueError("task dependency graph contains a cycle")
            if tid in visited:
                return
            visiting.add(tid)
            for dep in known[tid].dependencies:
                visit(dep)
            visiting.remove(tid)
            visited.add(tid)
        for tid in known:
            visit(tid)

    def static_schedule(self) -> list[str]:
        # 这里只固定 t=0 已知任务；动态关闭后到达的任务会追加在初始队列之后。
        return [t.task_id for t in order_tasks(
            [t for t in self.tasks.values() if t.submitted_at == 0], self.config.policy)]

    def _dependencies_ready(self, task: Task) -> bool:
        # 依赖必须真正完成；处于运行、暂停或被取消都不能满足后续任务。
        return all(dep in self.tasks and self.tasks[dep].state == TaskState.COMPLETED
                   for dep in task.dependencies)

    def _ready_tasks(self) -> list[Task]:
        # 动态模式每个边界重排；静态模式维持初始顺序并将新到任务排在后面。
        candidates = [t for t in self.tasks.values() if t.state == TaskState.READY]
        if self.config.dynamic_rescheduling:
            return order_tasks(candidates, self.config.policy)
        return sorted(candidates, key=lambda t: (
            (0, self._initial_order[t.task_id], "") if t.task_id in self._initial_order
            else (1, t.submitted_at, t.task_id)))

    def _record(self, event: str, *, at: int | None = None, **data) -> None:
        # trace 同时供前端回放和实验复核使用；未指定时间时记录当前边界。
        self.trace.append({"time": self.time if at is None else at, "event": event, **data})

    def _desired_resources(self, task: Task) -> dict[str, int]:
        if not task.stages:
            return dict(task.resources)
        # 前序阶段未释放的资源仍属于任务需求；抢占释放后恢复时必须一起重新申请。
        desired: dict[str, int] = {}
        for stage in task.stages[:task.stage_index]:
            desired.update(stage.resources)
            for name in stage.release_resources:
                desired.pop(name, None)
        if task.current_stage:
            desired.update(task.current_stage.resources)
        if task.retry_count:
            # 回滚恢复后，以“最大需要量”的形式预留一个原子资源约束，直到任务完成。
            desired.update(task.max_claim)
        return dict(sorted(desired.items()))

    def _requested_resources(self, task: Task) -> dict[str, int]:
        # 阶段声明的是目标持有量，因此只提交目标量减去当前占用后的正差额。
        held = self.resource_manager.allocation.get(task.task_id, {})
        return {name: amount - held.get(name, 0)
                for name, amount in self._desired_resources(task).items()
                if amount > held.get(name, 0)}

    def _pause(self, task: Task, reason: str, resume_at: int, *, release: bool = False) -> None:
        # 抢占会释放资源，资源故障一般保留资源；两种暂停都保存剩余工作量。
        if task.task_id in self.running:
            self.running.remove(task.task_id)
        task.saved_remaining = task.remaining
        task.state = TaskState.PAUSED
        task.waiting_reason = reason
        saved_resources = dict(self.resource_manager.allocation.get(task.task_id, {}))
        if release:
            self.resource_manager.release(task.task_id)
        self.waiting_requests.pop(task.task_id, None)
        self._wait_keys.pop(task.task_id, None)
        self._paused_until[task.task_id] = max(self._paused_until.get(task.task_id, 0), resume_at)
        self._record("pause", task_id=task.task_id, reason=reason, remaining=task.remaining,
                     stage_index=task.stage_index, resume_at=resume_at,
                     saved_resources=saved_resources, resources_released=release)

    def _preempt_for(self, incoming: Task) -> None:
        # 只有动态优先级且开启抢占时才允许新任务主动中断当前运行任务。
        if (not self.config.dynamic_rescheduling or not self.config.preemptive
                or self.config.policy != "priority"):
            return
        desired = self._desired_resources(incoming)
        if incoming.urgent:
            desired.update(incoming.max_claim)
        if any(self.time < self.resource_manager.resources[r].blocked_until for r in desired):
            return
        owners = [self.tasks[tid] for tid, held in self.resource_manager.allocation.items()
                  if tid != incoming.task_id and set(held) & set(desired)]
        eligible = lambda t: (t.task_id in self.running and t.priority < incoming.priority
                             and t.preemptible and (t.current_stage is None or t.current_stage.preemptible))
        # 若必要资源的持有者不可抢占，就不打断其他无关任务。
        if any(not eligible(t) for t in owners):
            return
        victims = list(owners)
        if self.config.workers is not None and len(self.running) - len(victims) >= self.config.workers:
            others = [self.tasks[tid] for tid in self.running
                      if eligible(self.tasks[tid]) and self.tasks[tid] not in victims]
            if not others:
                return
            victims.append(min(others, key=lambda t: (t.priority, t.task_id)))
        for victim in victims:
            self._pause(victim, f"preempted by {incoming.task_id}", self.time, release=True)
            victim.preemptions += 1
            self.metrics.preemptions += 1
            self._record("preempt", task_id=victim.task_id, by=incoming.task_id,
                         remaining=victim.remaining, progress_preserved=True)

    def _apply_interrupts(self) -> None:
        # 事件按时间排序；同一时刻的事件会在当前边界依次处理。
        while self.interrupt_index < len(self.interrupts) and self.interrupts[self.interrupt_index].at <= self.time:
            event = self.interrupts[self.interrupt_index]
            self.interrupt_index += 1
            self._record("interrupt", kind=event.kind.value, description=event.description)
            if event.kind in (InterruptType.REQUEST, InterruptType.URGENT, InterruptType.CUP_TAKEN):
                if event.kind == InterruptType.CUP_TAKEN:
                    if event.cup_id in self._seen_cups:
                        self._record("duplicate_cup_ignored", cup_id=event.cup_id)
                        continue
                    self._seen_cups.add(event.cup_id)
                task = event.task
                if event.kind == InterruptType.URGENT:
                    task.urgent = True
                self.tasks[task.task_id] = task
                self._record("urgent_submitted" if task.urgent else "request_submitted", task_id=task.task_id)
            elif event.kind in (InterruptType.ENVIRONMENT, InterruptType.FAULT):
                until = event.end_at if event.end_at is not None else self.time + event.duration
                if event.resource:
                    resource = self.resource_manager.resources[event.resource]
                    resource.blocked_until = max(resource.blocked_until, until)
                    self._outages.add(event.resource)
                    self._record("resource_blocked", resource=event.resource, until=resource.blocked_until)
                    affected = [t for t in self.tasks.values() if t.submitted_at <= self.time and not t.is_finished
                                and (event.resource in self.resource_manager.allocation.get(t.task_id, {})
                                     or (t.task_id in self.running and event.resource in self._desired_resources(t)))]
                else:
                    target = self.tasks.get(event.target_task_id)
                    affected = [target] if target and target.submitted_at <= self.time and not target.is_finished else []
                for task in affected:
                    self._pause(task, f"{event.kind.value} interruption",
                                self.time if event.resource else until)
            elif event.kind == InterruptType.RESTORE:
                self.resource_manager.resources[event.resource].blocked_until = self.time
        for name in sorted(self._outages):
            if self.resource_manager.resources[name].blocked_until <= self.time:
                self._outages.remove(name)
                self._record("resource_restored", resource=name)

    def _update_ready(self) -> None:
        # 先过滤未到达和终态任务，再检查暂停恢复条件与依赖关系。
        for task in self.tasks.values():
            if task.submitted_at > self.time or task.is_finished or task.state == TaskState.RUNNING:
                continue
            if task.task_id not in self._arrived:
                self._arrived.add(task.task_id)
                self._record("arrival", task_id=task.task_id)
            if task.state == TaskState.PAUSED:
                names = set(self._desired_resources(task)) | set(self.resource_manager.allocation.get(task.task_id, {}))
                if self.time < self._paused_until[task.task_id] or any(
                        self.time < self.resource_manager.resources[r].blocked_until for r in names):
                    continue
                self._paused_until.pop(task.task_id)
                self._record("resume_ready", task_id=task.task_id,
                             remaining=task.remaining, stage_index=task.stage_index)
            if not self._dependencies_ready(task):
                task.state = TaskState.BLOCKED
                if task.waiting_reason != "dependency":
                    self._record("dependency_wait", task_id=task.task_id, dependencies=task.dependencies)
                task.waiting_reason = "dependency"
            else:
                task.state = TaskState.READY
        self.request_board = MappingProxyType({tid: MappingProxyType({
            "name": t.name, "state": t.state.value, "priority": t.priority})
            for tid, t in self.tasks.items() if t.submitted_at <= self.time})

    def _start_tasks(self) -> None:
        # 资源申请失败只阻塞当前任务，仍继续检查其他候选，避免无关资源空闲。
        for task in self._ready_tasks():
            self._preempt_for(task)
            if self.config.workers is not None and len(self.running) >= self.config.workers:
                task.waiting_reason = "worker capacity"
                continue
            desired = self._desired_resources(task)
            request = self._requested_resources(task)
            if any(self.time < self.resource_manager.resources[r].blocked_until for r in desired):
                granted, reason = False, "resource outage"
            else:
                result = self.resource_manager.try_acquire(task, self.tasks, self.time, request)
                granted, reason = result.granted, result.reason
            if not granted:
                task.state = TaskState.BLOCKED
                task.waiting_reason = reason
                # 只有所有权冲突才形成等待图边；故障和 Banker 拒绝不等于任务间互等。
                if reason == "resource occupied":
                    self.waiting_requests[task.task_id] = request
                else:
                    self.waiting_requests.pop(task.task_id, None)
                key = (reason, tuple(sorted(request.items())))
                if self._wait_keys.get(task.task_id) != key:
                    self.metrics.conflicts += int(reason == "resource occupied")
                    self.metrics.safety_rejections += int("safety" in reason.lower())
                    self._record("resource_wait", task_id=task.task_id, reason=reason, request=request)
                self._wait_keys[task.task_id] = key
                continue
            resumed = task.saved_remaining is not None
            task.state = TaskState.RUNNING
            task.waiting_reason = ""
            task.started_at = self.time if task.started_at is None else task.started_at
            self.running.append(task.task_id)
            self.waiting_requests.pop(task.task_id, None)
            self._wait_keys.pop(task.task_id, None)
            self._record("resume" if resumed else "start" if task.stage_index == 0 else "stage_start",
                         task_id=task.task_id, stage=task.current_stage.name if task.current_stage else task.name,
                         stage_index=task.stage_index, acquired=request,
                         remaining=task.remaining, reason=selection_reason(self.config.policy)
                         if self.config.dynamic_rescheduling else "static initial order; later arrivals appended")
            task.saved_remaining = None

    def _finish_tasks(self) -> None:
        # 仅运行任务消耗一个 tick；等待和暂停不会增加 completed_work。
        for tid in list(self.running):
            task = self.tasks[tid]
            task.remaining -= 1
            task.completed_work += 1
            if task.redo_remaining:
                task.redo_remaining -= 1
                task.redone_work += 1
                self.metrics.redo_work += 1
            if task.remaining:
                continue
            stage = task.current_stage
            if stage:
                if not task.retry_count:
                    self.resource_manager.release(tid, stage.release_resources)
                task.stage_index += 1
            if stage is None or task.stage_index == len(task.stages):
                task.state = TaskState.COMPLETED
                task.finished_at = self.time + 1
                self.running.remove(tid)
                self.resource_manager.release(tid)
                self._record("complete", at=task.finished_at, task_id=tid,
                             response_time=task.response_time, lateness=task.completion_delay)
            else:
                task.remaining = task.current_stage.duration
                task.state = TaskState.READY
                self.running.remove(tid)
                if not self.resource_manager.allocation.get(tid):
                    task.checkpoint = task.stage_index
                self._record("stage_complete", at=self.time + 1, task_id=tid,
                             completed_stage=stage.name, next_stage=task.current_stage.name,
                             released=stage.release_resources if not task.retry_count else [],
                             checkpoint=task.checkpoint)

    def _detect_and_recover(self) -> None:
        # 持续存在的同一组环只计一次；恢复后状态变化形成的新环才重新计数。
        if not self.config.deadlock_detection or self.time % self.config.detection_period:
            return
        graph = build_wait_for_graph(self.resource_manager.allocation, self.waiting_requests)
        cycles = find_cycles(graph)
        keyed = {tuple(sorted(cycle)): cycle for cycle in cycles}
        new = {key: cycle for key, cycle in keyed.items() if key not in self._active_cycles}
        self._active_cycles = set(keyed)
        if new:
            self.metrics.deadlocks += len(new)
            self._record("deadlock_detected", cycles=list(new.values()),
                         graph={tid: sorted(edges) for tid, edges in sorted(graph.items())})
        if not self.config.deadlock_recovery:
            return
        for key, cycle in sorted(new.items()):
            remaining = find_cycles(build_wait_for_graph(self.resource_manager.allocation, self.waiting_requests))
            if key not in {tuple(sorted(c)) for c in remaining}:
                continue
            # 只回滚显式声明可回滚的环内任务，保护不可逆业务步骤。
            eligible = [tid for tid in cycle if self.tasks[tid].rollback_allowed]
            if not eligible:
                self._record("deadlock_unresolved", cycle=cycle, reason="no rollback-eligible task")
                continue
            tid = choose_recovery_victim(self.tasks, eligible)
            task = self.tasks[tid]
            released = dict(self.resource_manager.allocation.get(tid, {}))
            self.resource_manager.release(tid)
            self.waiting_requests.pop(tid, None)
            self._wait_keys.pop(tid, None)
            if tid in self.running:
                self.running.remove(tid)
            self.metrics.recoveries += 1
            if task.retry_count >= task.max_retries:
                task.state = TaskState.CANCELLED
                task.finished_at = self.time
                task.waiting_reason = "maximum rollback retries exceeded"
                self._record("cancel", task_id=tid, reason=task.waiting_reason, released=released)
                continue
            checkpoint_work = sum(s.duration for s in task.stages[:task.checkpoint])
            lost = task.completed_work - checkpoint_work
            task.rolled_back_work += lost
            task.redo_remaining = lost
            task.completed_work = checkpoint_work
            task.stage_index = task.checkpoint
            task.remaining = task.current_stage.duration if task.current_stage else task.duration
            task.retry_count += 1
            task.state = TaskState.READY
            task.waiting_reason = "rollback retry: atomic ordered reservation"
            self.metrics.rollback_count += 1
            self.metrics.rollback_work += lost
            self._record("rollback", task_id=tid, lost_work=lost, released=released,
                         checkpoint=task.checkpoint, retry_count=task.retry_count,
                         reason="lowest priority, least checkpoint redo cost, task id",
                         retry_resource_order=sorted(task.max_claim))

    def _account_resources(self) -> None:
        # busy 仅统计正在使用资源的运行时间；held 也包含持有资源但等待的时间。
        for name, resource in self.resource_manager.resources.items():
            if resource.shared:
                continue
            held = any(values.get(name, 0) for values in self.resource_manager.allocation.values())
            if self.time < resource.blocked_until:
                self.metrics.resource_outage_ticks[name] += 1
                self.metrics.resource_outage_held_ticks[name] += int(held)
                continue
            self.metrics.resource_available_ticks[name] += 1
            self.metrics.resource_held_ticks[name] += int(held)
            active = any(name in (self.tasks[tid].current_stage.resources if self.tasks[tid].current_stage
                                  else self.tasks[tid].resources) for tid in self.running)
            self.metrics.resource_busy_ticks[name] += int(active)

    def _refresh_metrics(self, end: int) -> None:
        # 分母只含已经到达的任务；紧急错失率另排除观察窗口内尚未到截止时刻的任务。
        arrived = [t for t in self.tasks.values() if t.submitted_at <= self.time]
        completed = [t for t in arrived if t.state == TaskState.COMPLETED]
        self.metrics.total_tasks = len(arrived)
        self.metrics.completed_tasks = len(completed)
        self.metrics.cancelled_tasks = sum(t.state == TaskState.CANCELLED for t in arrived)
        self.metrics.total_response = sum(t.response_time for t in completed)
        self.metrics.total_delay = sum(t.completion_delay for t in completed)
        self.metrics.on_time_tasks = sum(t.finished_at <= t.deadline for t in completed)
        urgent = [t for t in arrived if t.urgent and t.deadline <= end]
        self.metrics.urgent_tasks = len(urgent)
        self.metrics.urgent_missed = sum(t.state != TaskState.COMPLETED or t.finished_at > t.deadline for t in urgent)

    def _assert_invariants(self) -> None:
        # 每个边界验证资源容量、任务状态、依赖和运行中资源需求的一致性。
        manager = self.resource_manager
        if len(self.running) != len(set(self.running)):
            raise RuntimeError("duplicate running task")
        if any(n < 0 for n in manager.physical_available().values()):
            raise RuntimeError("resource capacity exceeded")
        for tid, held in manager.allocation.items():
            task = self.tasks[tid]
            if task.is_finished or task.submitted_at > self.time:
                raise RuntimeError("finished or future task holds resources")
            if any(n <= 0 or n > task.max_claim.get(r, 0) for r, n in held.items()):
                raise RuntimeError("allocation exceeds task claim")
        for tid in self.running:
            task = self.tasks[tid]
            if task.state != TaskState.RUNNING or not self._dependencies_ready(task):
                raise RuntimeError("invalid running task")
            for r, n in self._desired_resources(task).items():
                if self.time < manager.resources[r].blocked_until:
                    raise RuntimeError("running task uses an unavailable resource")
                if not manager.resources[r].shared and manager.allocation.get(tid, {}).get(r, 0) < n:
                    raise RuntimeError("running task lacks required resources")

    def run(self, progress_callback: Callable[[int, dict[str, Task], list[dict]], None] | None = None) -> dict:
        # 每个 Scheduler 只运行一次；策略对照需分别创建新实例以隔离运行状态。
        if self._has_run:
            raise ValueError("create a new Scheduler for each run")
        self._has_run = True
        self._record("static_order", order=self.static_schedule(), policy=self.config.policy)
        reported = 0
        horizon = self.config.max_time
        stop_reason = "max_time"
        while self.time <= horizon:
            # 边界顺序决定结果语义：事件、就绪、分配、检测、快照、资源计数、执行推进。
            self._apply_interrupts()
            self._update_ready()
            relevant = [t for t in self.tasks.values() if t.submitted_at <= horizon]
            future = any(self.time < e.at <= horizon for e in self.interrupts[self.interrupt_index:])
            done = all(t.is_finished for t in relevant) and not future
            if self.time == horizon or done:
                stop_reason = "all tasks finished" if done else "max_time"
                # 即使提前结束，也保留统一的时间轴长度，方便横向比较不同场景结果。
                for name, resource in self.resource_manager.resources.items():
                    if not resource.shared:
                        idle_available = max(0, horizon - max(self.time, resource.blocked_until))
                        self.metrics.resource_available_ticks[name] += idle_available
                        self.metrics.resource_outage_ticks[name] += horizon - self.time - idle_available
                self._refresh_metrics(horizon)
                self._record("stop", reason=stop_reason, observation_horizon=horizon)
                if progress_callback:
                    progress_callback(self.time, self.tasks, self.trace[reported:])
                break
            self._start_tasks()
            self._detect_and_recover()
            self._assert_invariants()
            self._refresh_metrics(self.time)
            if progress_callback:
                progress_callback(self.time, self.tasks, self.trace[reported:])
            reported = len(self.trace)
            self._account_resources()
            self._finish_tasks()
            self.time += 1
        self._assert_invariants()
        unfinished = {t.task_id: {"age": self.time - t.submitted_at,
                                  "remaining_work": t.duration - t.completed_work,
                                  "reason": t.waiting_reason or t.state.value}
                      for t in self.tasks.values() if t.submitted_at <= horizon and not t.is_finished}
        from .scenario_io import provenance
        input_hash = hashlib.sha256(json.dumps(self.input_document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        workload = {key: self.input_document[key] for key in ("tasks", "resources", "events")}
        workload_hash = hashlib.sha256(json.dumps(workload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"metrics": self.metrics.as_dict(), "tasks": {tid: asdict(t) for tid, t in self.tasks.items()},
                "trace": self.trace, "config": asdict(self.config), "stop_reason": stop_reason,
                "unfinished": unfinished, "observation_horizon": horizon, "elapsed_time": self.time,
                "metadata": {**provenance(), "seed": self.input_document.get("seed"),
                             "input_sha256": input_hash, "workload_sha256": workload_hash},
                "input": self.input_document}
