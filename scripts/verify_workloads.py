"""Seeded integration stress checks; these loads are not a validated course experiment."""
from __future__ import annotations
import argparse
import csv
import json
import random
from pathlib import Path

from tea_break_scheduler.models import Interrupt, InterruptType, SchedulerConfig, Task
from tea_break_scheduler.scenario_io import scenario_document, scenario_from_dict
from tea_break_scheduler.scenarios import VARIANTS, config_for, delivery, recycle, resources


def workload(seed: int) -> dict:
    rng = random.Random(seed)
    tasks = []
    for index in range(16):
        tid, at = f"T{index:02}", rng.randrange(15)
        kind = rng.randrange(3)
        if kind == 0:
            t = delivery(tid, at)
        elif kind == 1:
            t = recycle(tid, at)
        else:
            t = Task(tid, "整理", 1, at + 20, rng.randrange(1, 6), submitted_at=at,
                     resources={"tea_table": 1}, task_type="maintenance")
        tasks.append(t)
    events = [Interrupt(at, InterruptType.URGENT, "回归紧急请求", task=delivery(f"U{index}", at, True))
              for index, at in enumerate(sorted(rng.sample(range(2, 25), 3)))]
    events += [Interrupt(8, InterruptType.FAULT, "回归故障", resource="tea_table", duration=3),
               Interrupt(12, InterruptType.ENVIRONMENT, "回归关闭", resource="corridor", duration=2)]
    return scenario_document(tasks, resources(), SchedulerConfig(max_time=120), events, seed=seed)


def verify(seeds=range(1, 21), output: Path | None = None) -> dict:
    rows = []
    for seed in seeds:
        document = workload(seed)
        hashes = set()
        if output:
            (output / "inputs").mkdir(parents=True, exist_ok=True)
            (output / "inputs" / f"seed-{seed}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        for variant in VARIANTS:
            from dataclasses import asdict
            configured = {**document, "config": asdict(config_for(variant, SchedulerConfig(max_time=120)))}
            result = scenario_from_dict(configured).run()
            hashes.add(result["metadata"]["workload_sha256"])
            for t in result["tasks"].values():
                assert 0 <= t["completed_work"] <= t["duration"]
                if t["state"] == "completed":
                    assert t["completed_work"] == t["duration"]
                    assert t["submitted_at"] <= t["started_at"] < t["finished_at"] <= 120
            assert result["metrics"]["total_tasks"] == 19
            assert result["metrics"]["resource_available_ticks"]["tea_table"] == 117
            assert result["metrics"]["resource_available_ticks"]["corridor"] == 118
            rows.append({"seed": seed, "variant": variant,
                         "workload_sha256": result["metadata"]["workload_sha256"],
                         **{k: v for k, v in result["metrics"].items() if not isinstance(v, dict)}})
            if output:
                (output / f"seed-{seed}-{variant}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        assert len(hashes) == 1, "comparison variants must reuse the same workload"
    summary = {"kind": "integration_regression", "runs": len(rows),
               "seeds": sorted({row["seed"] for row in rows}), "variants": list(VARIANTS),
               "checks": ["runtime ownership invariants", "preserved completed work", "common horizon",
                          "same workload hash within seed", "no work after H"]}
    if output:
        with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        (output / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("results/regression"))
    args = parser.parse_args()
    if not 1 <= args.seeds <= 100:
        parser.error("--seeds must be between 1 and 100")
    print(json.dumps(verify(range(1, args.seeds + 1), args.output), indent=2))
