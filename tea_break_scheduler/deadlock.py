# 这里实现 Banker 安全性检查、单实例资源等待图和恢复时的受害任务排序。

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BankerState:
    # available 是剩余量，allocation 是已分配量，maximum 是任务声明的最大总需求。
    available: dict[str, int]
    allocation: dict[str, dict[str, int]]
    maximum: dict[str, dict[str, int]]

    def clone(self) -> "BankerState":
        # 安全性试分配只修改副本；拒绝请求时，真实资源账本必须保持原样。
        return BankerState(
            dict(self.available),
            {task: dict(values) for task, values in self.allocation.items()},
            {task: dict(values) for task, values in self.maximum.items()},
        )


def _need(state: BankerState, task_id: str) -> dict[str, int]:
    # Need = max(0, Maximum - Allocation)，只计算该任务完成前尚未分配的部分。
    resources = set(state.maximum.get(task_id, {})) | set(state.allocation.get(task_id, {}))
    return {
        resource: max(0, state.maximum.get(task_id, {}).get(resource, 0)
                      - state.allocation.get(task_id, {}).get(resource, 0))
        for resource in resources
    }


def is_safe(state: BankerState) -> tuple[bool, list[str]]:
    # Work 模拟可用量；满足 Need <= Work 的任务可假设完成，并把 Allocation 归还 Work。
    work = dict(state.available)
    finish = {task_id: False for task_id in state.maximum}
    order: list[str] = []
    changed = True
    while changed:
        changed = False
        # 每轮可能多完成一个任务；直到再也找不到满足 Need 的任务才停止。
        for task_id in finish:
            if finish[task_id]:
                continue
            need = _need(state, task_id)
            if all(need.get(resource, 0) <= work.get(resource, 0) for resource in need):
                # 假设该任务完成后释放全部已分配资源，继续判断剩余任务是否可完成。
                for resource, amount in state.allocation.get(task_id, {}).items():
                    work[resource] = work.get(resource, 0) + amount
                finish[task_id] = True
                order.append(task_id)
                changed = True
    return all(finish.values()), order


def request_is_safe(state: BankerState, task_id: str, request: dict[str, int]) -> bool:
    # 先验证请求不超过 Need 和 Available，再执行副本分配并寻找安全完成顺序。
    if task_id not in state.maximum:
        return False
    need = _need(state, task_id)
    if any(amount < 0 or amount > need.get(resource, 0) for resource, amount in request.items()):
        return False
    if any(amount > state.available.get(resource, 0) for resource, amount in request.items()):
        return False
    trial = state.clone()
    for resource, amount in request.items():
        # 先扣减可用量并增加该任务占用，再对“申请后的状态”执行安全序列检查。
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
    # A -> B 表示 A 等待的互斥资源当前由 B 持有；环境故障和 Banker 拒绝不应传入。
    owners: dict[str, set[str]] = {}
    for task_id, resources in allocation.items():
        for resource, amount in resources.items():
            if amount > 0:
                owners.setdefault(resource, set()).add(task_id)
    graph: dict[str, set[str]] = {task_id: set() for task_id in set(allocation) | set(waiting)}
    for task_id, requests in waiting.items():
        for resource, amount in requests.items():
            if amount > 0:
                # 一个等待请求可能对应多个持有者；单实例互斥场景中最多只有一个。
                graph.setdefault(task_id, set()).update(owners.get(resource, set()) - {task_id})
    return graph


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    # 环按字典序规范化轮转起点，避免 [A, B] 和 [B, A] 被重复报告。
    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def visit(start: str, node: str, path: list[str], active: set[str]) -> None:
        for nxt in sorted(graph.get(node, set())):
            if nxt == start and len(path) > 1:
                # 找到回边时规范化路径，随后通过 seen_keys 去掉不同起点发现的同一环。
                cycle = path[:]
                rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
                key = min(rotations)
                if key not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(list(key))
            elif nxt not in active and len(path) < len(graph):
                visit(start, nxt, path + [nxt], active | {nxt})

    for node in sorted(graph):
        visit(node, node, [node], {node})
    return cycles


def choose_recovery_victim(tasks: dict[str, object], cycle: list[str]) -> str:
    # 选择低优先级、回滚损失较小的任务；task_id 作为最后的稳定决胜条件。

    def score(task_id: str) -> tuple[int, int, str]:
        task = tasks[task_id]
        checkpoint_work = sum(stage.duration for stage in task.stages[:task.checkpoint])
        redo_cost = max(0, task.completed_work - checkpoint_work)
        return (task.priority, redo_cost, task_id)

    return min(cycle, key=score)
