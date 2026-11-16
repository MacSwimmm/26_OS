#!/usr/bin/env python3
# 项目说明 13.3 的排序验证入口；只读预先列明的手算与预期，不回写案例。

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tea_break_scheduler.models import task_from_dict  # noqa: E402
from tea_break_scheduler.policies import rank_tasks  # noqa: E402
from tea_break_scheduler.scenario_io import provenance  # noqa: E402

CASES_PATH = ROOT / "data" / "policies" / "cases.json"


def load_cases(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or document.get("kind") != "ordering_cases"):
        raise ValueError("expected ordering_cases with schema_version=1")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be an object")
        cid = case.get("case_id")
        if not isinstance(cid, str) or not cid or cid in seen:
            raise ValueError("case_id must be a unique nonempty string")
        seen.add(cid)
        at = case.get("observed_at")
        if type(at) is not int or at < 0:
            raise ValueError(f"{cid}: observed_at must be a nonnegative integer")
        if not isinstance(case.get("tasks"), list) or any(not isinstance(t, dict) for t in case["tasks"]):
            raise ValueError(f"{cid}: tasks must be a list of objects")
        tasks = [task_from_dict(t) for t in case["tasks"]]
        ids = [task.task_id for task in tasks]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{cid}: duplicate task id")
        if any(task.submitted_at > at for task in tasks):
            raise ValueError(f"{cid}: candidate has not arrived at observed_at")
        expected = case.get("expected")
        if (not isinstance(expected, list) or any(not isinstance(tid, str) for tid in expected)
                or len(expected) != len(ids) or set(expected) != set(ids)):
            raise ValueError(f"{cid}: expected must list each task id exactly once")
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps or any(not isinstance(s, str) or not s for s in steps):
            raise ValueError(f"{cid}: steps must contain the calculation")
        rank_tasks(tasks, case.get("policy"))
    return cases, hashlib.sha256(raw).hexdigest()


def fmt(order) -> str:
    if order is None:
        return "（未登记预期顺序）"
    if not order:
        return "（空）"
    return " -> ".join(str(item) for item in order)


def run_case(case: dict) -> dict:
    policy = case["policy"]
    tasks = [task_from_dict(item) for item in case["tasks"]]
    expected = list(case["expected"]) if "expected" in case else None
    ranked = rank_tasks(tasks, policy)
    actual = [task.task_id for task, _ in ranked]

    print("=" * 66)
    print("[案例] %s %s" % (case.get("case_id", "-"), case.get("category", "")))
    print("[配置] 策略=%s，候选任务=%d 个" % (policy, len(tasks)))
    print("[观察时刻] t=%d；仅验证给定候选集的排序，不代表完整执行顺序" % case["observed_at"])
    if tasks:
        print("[输入] " + "  ".join(
            "%s(p=%d,d=%d,t=%d)" % (t.task_id, t.priority, t.deadline, t.submitted_at) for t in tasks
        ))
    for line in case.get("steps", []):
        print("[手算] %s" % line)
    print("[预期（运行前登记）] %s" % fmt(expected))
    print("[实际（程序输出）]   %s" % fmt(actual))
    for index, (task, reason) in enumerate(ranked, start=1):
        print("  %d. %-6s %s" % (index, task.task_id, reason))

    passed = expected is not None and actual == expected
    print("[判定] %s" % ("通过" if passed else "不通过"))
    return {
        "case_id": case.get("case_id"),
        "policy": policy,
        "observed_at": case["observed_at"],
        "tasks": case["tasks"],
        "steps": case["steps"],
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "reasons": [{"task_id": t.task_id, "reason": r} for t, r in ranked],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="排序验证案例")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--json-out", type=Path, default=ROOT / "results" / "policies_validation.json")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()

    if not args.no_archive and args.json_out.resolve() == args.cases.resolve():
        parser.error("archive path must not overwrite the case input")
    try:
        cases, input_hash = load_cases(args.cases)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    records = [run_case(case) for case in cases]
    passed = sum(1 for r in records if r["passed"])

    print("=" * 66)
    print("共 %d 个案例，通过 %d 个，失败 %d 个。" % (len(records), passed, len(records) - passed))

    if not args.no_archive:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "meta": {
                        "module": "tea_break_scheduler/policies.py",
                        **provenance(),
                        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "cases_path": str(args.cases.resolve()),
                        "cases_sha256": input_hash,
                        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                    },
                    "summary": {"total": len(records), "passed": passed, "failed": len(records) - passed},
                    "cases": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("结果已归档：%s" % args.json_out)

    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
