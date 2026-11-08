"""Versioned JSON scenario input and result provenance."""
from __future__ import annotations
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path

from .models import Interrupt, InterruptType, Resource, SchedulerConfig, task_from_dict, TASK_INPUT_FIELDS

ROOT = Path(__file__).resolve().parent.parent


def provenance() -> dict:
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(ROOT), *args], stderr=subprocess.DEVNULL,
                                           text=True, timeout=2).strip()
        except (OSError, subprocess.SubprocessError):
            return None
    revision = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    # Hash the actual algorithm sources, so local changes are reproducible even
    # when results are produced before the implementation commit.
    sources = hashlib.sha256()
    for path in sorted((ROOT / "tea_break_scheduler").glob("*.py")):
        sources.update(path.name.encode())
        sources.update(path.read_bytes())
    return {"schema_version": 2, "git_commit": revision, "git_dirty": bool(dirty) if dirty is not None else None,
            "source_sha256": sources.hexdigest(), "python": platform.python_version(),
            "platform": platform.system(), "seed": None}


def scenario_from_dict(data: dict):
    from .scheduler import Scheduler
    if not isinstance(data, dict) or data.get("schema_version", 1) != 1:
        raise ValueError("scenario must be an object with schema_version=1")
    if not isinstance(data.get("resources"), dict):
        raise ValueError("resources must be an object")
    if any(not isinstance(value, dict) for value in data["resources"].values()):
        raise ValueError("each resource definition must be an object")
    for name in ("tasks", "events"):
        if not isinstance(data.get(name, []), list) or any(not isinstance(value, dict) for value in data.get(name, [])):
            raise ValueError(f"{name} must be a list of objects")
    if not isinstance(data.get("config", {}), dict):
        raise ValueError("config must be an object")
    seed = data.get("seed")
    if seed is not None and type(seed) is not int:
        raise ValueError("seed must be an integer or null")
    resources = {name: Resource(name=name, **value) for name, value in data["resources"].items()}
    tasks = [task_from_dict(value) for value in data.get("tasks", [])]
    events = []
    for value in data.get("events", []):
        value = dict(value)
        value["kind"] = InterruptType(value["kind"])
        if value.get("task") is not None:
            value["task"] = task_from_dict(value["task"])
        events.append(Interrupt(**value))
    scheduler = Scheduler(tasks, resources, SchedulerConfig(**data.get("config", {})), events)
    scheduler.input_document["seed"] = data.get("seed")
    return scheduler


def load_scenario(path: Path):
    return scenario_from_dict(json.loads(path.read_text(encoding="utf-8")))


def scenario_document(tasks, resources, config, events=(), seed=None) -> dict:
    def task_document(task):
        values = asdict(task)
        return {key: values[key] for key in TASK_INPUT_FIELDS}
    event_documents = []
    for event in events:
        values = asdict(event)
        values["kind"] = event.kind.value
        values["task"] = task_document(event.task) if event.task else None
        event_documents.append(values)
    return {"schema_version": 1, "seed": seed, "config": asdict(config),
            "resources": {name: {key: value for key, value in asdict(r).items() if key != "name"}
                          for name, r in resources.items()},
            "tasks": [task_document(t) for t in tasks], "events": event_documents}
