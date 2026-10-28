#!/usr/bin/env python3
"""Run a Linux-friendly demo or generate comparison results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tea_break_scheduler.scenarios import build_scheduler, deadlock_demo, run_comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="茶歇服务员任务调度仿真")
    parser.add_argument("--scenario", choices=["baseline", "no_dynamic", "no_deadlock", "non_preemptive", "compare", "deadlock"], default="baseline")
    parser.add_argument("--output", type=Path, help="write JSON results to this path")
    args = parser.parse_args()
    result = deadlock_demo() if args.scenario == "deadlock" else (
        run_comparison() if args.scenario == "compare" else build_scheduler(args.scenario).run()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
