# 对比两个工作区的真实引擎行为；只排除本次有意变化的日志说明和来源元数据。
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def capture(root: Path) -> dict:
    # 基线与当前版本分别在独立 Python 进程导入，避免 sys.modules 混用源码。
    sys.path.insert(0, str(root))
    from dataclasses import asdict
    from tea_break_scheduler.models import Resource, SchedulerConfig
    from tea_break_scheduler.scenario_io import load_scenario, provenance, scenario_from_dict
    from tea_break_scheduler.scenarios import VARIANTS, build_scheduler, config_for, deadlock_tasks
    from tea_break_scheduler.scheduler import Scheduler
    from scripts.verify_workloads import workload

    records = {}

    def run(name, scheduler):
        snapshots = []

        def snapshot(t, tasks, events):
            snapshots.append({"time": t, "tasks": {k: asdict(v) for k, v in tasks.items()},
                              "running": list(scheduler.running),
                              "allocation": {k: dict(v) for k, v in scheduler.resource_manager.allocation.items()},
                              "resources": {k: asdict(v) for k, v in scheduler.resource_manager.resources.items()},
                              "waiting_requests": {k: dict(v) for k, v in scheduler.waiting_requests.items()},
                              "metrics": scheduler.metrics.as_dict()})

        result = scheduler.run(snapshot)
        for event in result["trace"]:
            if event["event"] in ("start", "resume", "stage_start"):
                event.pop("ordering", None)
                event.pop("reason", None)
        result.pop("metadata")
        records[name] = {"result_sha256": digest(result), "snapshots_sha256": digest(snapshots),
                         "snapshots": len(snapshots), "events": len(result["trace"])}

    for variant in VARIANTS:
        run("fixed/" + variant, build_scheduler(variant))
    for name, banker, recovery in (("avoidance", True, False), ("detection_only", False, False),
                                   ("detection_and_recovery", False, True)):
        run("deadlock/" + name, Scheduler(deadlock_tasks(),
            {r: Resource(r) for r in ("tea_table", "return_station")},
            SchedulerConfig(max_time=20, banker_enabled=banker, deadlock_recovery=recovery)))
    for path in sorted((root / "data/demos").glob("*.json")):
        run("demo/" + path.name, load_scenario(path))
    for seed in range(1, 21):
        document = workload(seed)
        for variant in VARIANTS:
            configured = {**document, "config": asdict(config_for(variant, SchedulerConfig(max_time=120)))}
            run(f"seed/{seed}/{variant}", scenario_from_dict(configured))
    return {"provenance": provenance(), "records": records}


def main() -> int:
    parser = argparse.ArgumentParser(description="对比排序修复前后的完整结果与每步资源/任务状态")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline-root", type=Path, help="待比较的原始版本工作区")
    group.add_argument("--capture-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=ROOT / "results/policies/compatibility.json")
    args = parser.parse_args()
    if args.capture_root:
        print(json.dumps(capture(args.capture_root.resolve()), ensure_ascii=False))
        return 0
    baseline = args.baseline_root.resolve()
    if baseline == ROOT:
        parser.error("baseline must be a separate checkout")
    captures = []
    for root in (baseline, ROOT):
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                    "--capture-root", str(root)], cwd=root,
                                   capture_output=True, text=True, timeout=120)
        if completed.returncode:
            parser.exit(2, completed.stderr)
        captures.append(json.loads(completed.stdout))
    left, right = [value["records"] for value in captures]
    differences = [name for name in sorted(left.keys() | right.keys()) if left.get(name) != right.get(name)]
    summary = {"baseline": captures[0]["provenance"], "current": captures[1]["provenance"],
               "runs": len(right), "snapshots": sum(v["snapshots"] for v in right.values()),
               "all_equal": not differences, "differences": differences,
               "excluded": ["metadata", "start/resume/stage_start.reason", "start/resume/stage_start.ordering"],
               "records": right}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, ensure_ascii=False, indent=2))
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
