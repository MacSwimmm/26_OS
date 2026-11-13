# 本模块维护真实资源占用，并将物理容量、故障可用性和 Banker 安全性分层检查。
from __future__ import annotations
from dataclasses import dataclass

from .deadlock import BankerState, request_is_safe
from .models import Resource, Task, validate_claim


@dataclass
class AllocationResult:
    # reason 供调度器决定是否建立 wait-for 边；只有 resource occupied 才代表所有权等待。
    granted: bool
    reason: str = ""


class ResourceManager:
    def __init__(self, resources: dict[str, Resource], banker_enabled: bool = True) -> None:
        self.resources = resources
        self.banker_enabled = banker_enabled
        self.allocation: dict[str, dict[str, int]] = {}

    def physical_available(self) -> dict[str, int]:
        # 这里不扣除故障资源；有限故障由暂停/恢复机制处理，不应改写物理容量。
        return {name: resource.capacity - sum(held.get(name, 0) for held in self.allocation.values())
                for name, resource in self.resources.items() if not resource.shared}

    def available(self, now: int) -> dict[str, int]:
        # UI 可用量会显示故障影响，因此在物理可用量之外再应用 blocked_until。
        physical = self.physical_available()
        return {name: (physical.get(name, resource.capacity) if now >= resource.blocked_until else 0)
                for name, resource in self.resources.items()}

    def banker_state(self, tasks: dict[str, Task], now: int) -> BankerState:
        # 安全序列按物理容量计算；有限故障另由调度器暂停任务，假设其最终会恢复。
        maximum = {tid: {r: n for r, n in task.max_claim.items() if not self.resources[r].shared}
                   for tid, task in tasks.items() if not task.is_finished and task.submitted_at <= now}
        return BankerState(self.physical_available(), self.allocation, maximum)

    def try_acquire(self, task: Task, tasks: dict[str, Task], now: int,
                    request: dict[str, int] | None = None) -> AllocationResult:
        # 校验声明和容量属于输入错误；故障、占用冲突和不安全状态则是可重试的拒绝。
        request = task.resources if request is None else request
        validate_claim(request)
        held = self.allocation.get(task.task_id, {})
        if any(name not in self.resources for name in request):
            raise ValueError("unknown resource")
        if any(held.get(name, 0) + amount > task.max_claim.get(name, 0)
               or (not self.resources[name].shared and amount > self.resources[name].capacity)
               for name, amount in request.items()):
            raise ValueError("request exceeds max_claim or resource capacity")
        # 故障先于互斥与 Banker 判断，保证暂停资源不会被新任务拿到。
        if any(now < self.resources[name].blocked_until for name in request):
            return AllocationResult(False, "resource outage")
        mutex_request = {r: n for r, n in request.items() if not self.resources[r].shared}
        available = self.physical_available()
        if any(n > available[r] for r, n in mutex_request.items()):
            return AllocationResult(False, "resource occupied")
        # 先确认物理上能满足申请，再做 Banker 试分配；不安全请求不会写入 allocation。
        if mutex_request and self.banker_enabled and not request_is_safe(
                self.banker_state(tasks, now), task.task_id, mutex_request):
            return AllocationResult(False, "Banker safety check rejected request")
        if mutex_request:
            held = self.allocation.setdefault(task.task_id, {})
            for name, amount in mutex_request.items():
                held[name] = held.get(name, 0) + amount
        return AllocationResult(True, "granted")

    def release(self, task_id: str, names: list[str] | None = None) -> None:
        # names=None 表示整项释放；指定列表则只释放对应资源，供阶段边界使用。
        if names is None:
            self.allocation.pop(task_id, None)
            return
        held = self.allocation.get(task_id, {})
        for name in names:
            held.pop(name, None)
        if not held:
            self.allocation.pop(task_id, None)
