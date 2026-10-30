#!/usr/bin/env python3
"""Local HTTP API for the OS scheduling simulator control panel."""

from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from tea_break_scheduler.scenarios import build_scheduler, deadlock_demo, run_comparison


ROOT = Path(__file__).resolve().parent
SCENARIOS = {
    "baseline": "完整调度",
    "no_dynamic": "静态调度",
    "no_deadlock": "关闭死锁保护",
    "non_preemptive": "非抢占调度",
    "compare": "调度策略对比",
    "deadlock": "死锁避免与恢复",
}


def _snapshot(scheduler, now: int, events: list[dict]) -> dict:
    tasks = {}
    for task_id, task in scheduler.tasks.items():
        data = asdict(task)
        stage = task.current_stage
        data["stage_name"] = stage.name if stage else task.name
        data["held_resources"] = scheduler.resource_manager.allocation.get(task_id, {}).copy()
        tasks[task_id] = data
    resources = {}
    available = scheduler.resource_manager.available(now)
    for name, resource in scheduler.resource_manager.resources.items():
        resources[name] = {
            "capacity": resource.capacity,
            "available": available.get(name, 0),
            "blocked_until": resource.blocked_until,
            "holders": {
                task_id: held[name]
                for task_id, held in scheduler.resource_manager.allocation.items()
                if held.get(name, 0)
            },
        }
    return {
        "time": now,
        "tasks": tasks,
        "resources": resources,
        "events": events,
        "metrics": scheduler.metrics.as_dict(),
    }


def _run_single(name: str) -> dict:
    scheduler = build_scheduler(name)
    snapshots = []

    def collect(now, tasks, events):
        snapshots.append(_snapshot(scheduler, now, events))

    result = scheduler.run(progress_callback=collect)
    return {"scenario": name, "label": SCENARIOS[name], "result": result, "snapshots": snapshots}


def _run_compare() -> dict:
    results = run_comparison()
    return {
        "scenario": "compare",
        "label": SCENARIOS["compare"],
        "comparisons": [
            {"name": name, "label": SCENARIOS[name], **result["metrics"]}
            for name, result in results.items()
        ],
        "results": results,
    }


def _run_deadlock() -> dict:
    results = deadlock_demo()
    labels = {
        "avoidance": "银行家避免",
        "detection_only": "只检测，不恢复",
        "detection_and_recovery": "检测并回滚恢复",
    }
    return {
        "scenario": "deadlock",
        "label": SCENARIOS["deadlock"],
        "comparisons": [
            {"name": name, "label": labels[name], **result["metrics"]}
            for name, result in results.items()
        ],
        "results": results,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TeaBreakDashboard/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/scenarios":
            self._json({"scenarios": [{"id": key, "label": value} for key, value in SCENARIOS.items()]})
            return
        if path in ("/", "/dashboard.html"):
            content = (ROOT / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        assets = {
            "/assets/trae-pixel-map.png": "image/png",
            "/assets/dashboard-effects.css": "text/css; charset=utf-8",
            "/assets/dashboard-effects.js": "text/javascript; charset=utf-8",
        }
        if path in assets:
            content = (ROOT / path.lstrip("/")).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", assets[path])
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000:
                raise ValueError("request body must be between 1 byte and 1 MB")
            payload = json.loads(self.rfile.read(length))
            scenario = payload.get("scenario", "baseline")
            if scenario not in SCENARIOS:
                raise ValueError("unknown scenario")
            data = _run_compare() if scenario == "compare" else _run_deadlock() if scenario == "deadlock" else _run_single(scenario)
            self._json(data)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:
            self._json({"error": f"simulation failed: {error}"}, 500)

    def _json(self, data: dict, status: int = 200):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="本机茶歇任务调度上位机")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"上位机已启动: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n上位机已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
