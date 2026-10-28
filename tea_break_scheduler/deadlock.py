"""Deadlock avoidance, detection and recovery algorithms.

The implementation is intentionally independent from the event loop.  This
makes the formulas easy to test and lets the paper show the same state tables
used by the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BankerState:
    available: dict[str, int]
    allocation: dict[str, dict[str, int]]
    maximum: dict[str, dict[str, int]]

    def clone(self) -> "BankerState":
        return BankerState(
            dict(self.available),
            {task: dict(values) for task, values in self.allocation.items()},
            {task: dict(values) for task, values in self.maximum.items()},
        )


def _need(state: BankerState, task_id: str) -> dict[str, int]:
    resources = set(state.maximum.get(task_id, {})) | set(state.allocation.get(task_id, {}))
    return {
        resource: max(0, state.maximum.get(task_id, {}).get(resource, 0)
                      - state.allocation.get(task_id, {}).get(resource, 0))
        for resource in resources
    }


def is_safe(state: BankerState) -> tuple[bool, list[str]]:
    """Return whether the current allocation has a safe completion order."""

    work = dict(state.available)
    finish = {task_id: False for task_id in state.maximum}
    order: list[str] = []
    changed = True
    while changed:
        changed = False
        for task_id in finish:
            if finish[task_id]:
                continue
            need = _need(state, task_id)
            if all(need.get(resource, 0) <= work.get(resource, 0) for resource in need):
                for resource, amount in state.allocation.get(task_id, {}).items():
                    work[resource] = work.get(resource, 0) + amount
                finish[task_id] = True
                order.append(task_id)
                changed = True
    return all(finish.values()), order


def request_is_safe(state: BankerState, task_id: str, request: dict[str, int]) -> bool:
    """Banker's pre-allocation check for one resource request."""

    need = _need(state, task_id)
    if any(amount < 0 or amount > need.get(resource, 0) for resource, amount in request.items()):
        return False
    if any(amount > state.available.get(resource, 0) for resource, amount in request.items()):
        return False
    trial = state.clone()
    for resource, amount in request.items():
        trial.available[resource] = trial.available.get(resource, 0) - amount
        trial.allocation.setdefault(task_id, {})[resource] = (
            trial.allocation.setdefault(task_id, {}).get(resource, 0) + amount
        )
    safe, _ = is_safe(trial)
    return safe


def build_wait_for_graph(
    allocation: dict[str, dict[str, int]],
    waiting: dict[str, dict[str, int]],
) -> dict[str, set[str]]:
    """Build a task wait-for graph from resource ownership and requests."""

    owners: dict[str, set[str]] = {}
    for task_id, resources in allocation.items():
        for resource, amount in resources.items():
            if amount > 0:
                owners.setdefault(resource, set()).add(task_id)
    graph: dict[str, set[str]] = {task_id: set() for task_id in set(allocation) | set(waiting)}
    for task_id, requests in waiting.items():
        for resource, amount in requests.items():
            if amount > 0:
                graph.setdefault(task_id, set()).update(owners.get(resource, set()) - {task_id})
    return graph


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find simple cycles in a directed wait-for graph."""

    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def visit(start: str, node: str, path: list[str], active: set[str]) -> None:
        for nxt in graph.get(node, set()):
            if nxt == start and len(path) > 1:
                cycle = path[:]
                rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
                key = min(rotations)
                if key not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(list(key))
            elif nxt not in active and len(path) < len(graph):
                visit(start, nxt, path + [nxt], active | {nxt})

    for node in graph:
        visit(node, node, [node], {node})
    return cycles


def choose_recovery_victim(tasks: dict[str, object], cycle: list[str]) -> str:
    """Select the least important task in a cycle for rollback/cancellation."""

    def score(task_id: str) -> tuple[int, int, str]:
        task = tasks[task_id]
        return (getattr(task, "priority", 0), -getattr(task, "remaining", 0), task_id)

    return min(cycle, key=score)
