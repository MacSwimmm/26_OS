# 基于 PR #3 补齐排序、理由、验证入口和真实调度日志的契约检查。

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from tea_break_scheduler.models import Interrupt, InterruptType, Resource, SchedulerConfig, Task, TaskState, task_from_dict
from tea_break_scheduler.scheduler import Scheduler
from tea_break_scheduler.policies import (
    FCFS,
    PRIORITY,
    explain,
    format_ranking,
    order_tasks,
    rank_tasks,
    selection_reason,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "policies" / "cases.json"


def make(task_id: str, priority: int = 1, deadline: int = 20, submitted: int = 0, urgent: bool = False) -> Task:
    # duration 固定为 1：本文件只验证排序，不关心工作量。
    return Task(task_id, task_id, priority, deadline, 1, submitted_at=submitted, urgent=urgent)


class ArrivalOrderTests(unittest.TestCase):
    """C1：FCFS 只看到达时刻，看不到达的高优先级任务不得插队。"""

    def test_order_by_arrival(self) -> None:
        tasks = [make("T3", submitted=4), make("T1", submitted=0), make("T2", submitted=2)]
        self.assertEqual(["T1", "T2", "T3"], [t.task_id for t in order_tasks(tasks, FCFS)])

    def test_late_urgent_task_does_not_jump_queue(self) -> None:
        tasks = [make("low", priority=1, submitted=0), make("urgent", priority=3, submitted=1, urgent=True)]
        self.assertEqual(["low", "urgent"], [t.task_id for t in order_tasks(tasks, FCFS)])

    def test_same_arrival_breaks_by_task_id(self) -> None:
        tasks = [make("T10", submitted=0), make("T9", submitted=0), make("T2", submitted=0)]
        self.assertEqual(["T10", "T2", "T9"], [t.task_id for t in order_tasks(tasks, FCFS)])


class PriorityOrderTests(unittest.TestCase):
    """C2：优先级数值大者先执行，与到达时刻无关。"""

    def test_priority_desc(self) -> None:
        tasks = [make("biz", priority=2), make("maint", priority=1), make("urgent", priority=3, submitted=5)]
        self.assertEqual(["urgent", "biz", "maint"], [t.task_id for t in order_tasks(tasks, PRIORITY)])


class TieBreakTests(unittest.TestCase):
    """C3/C4：优先级相同后，依次比截止时间、到达时刻、任务编号。"""

    def test_deadline_then_arrival_then_id(self) -> None:
        tasks = [
            make("no-tie", priority=2, deadline=50, submitted=1),
            make("early-deadline", priority=2, deadline=20, submitted=9),
            make("late-arrive", priority=2, deadline=30, submitted=5),
            make("early-arrive", priority=2, deadline=30, submitted=3),
            make("id-b", priority=2, deadline=40, submitted=30),
            make("id-a", priority=2, deadline=40, submitted=30),
        ]
        expected = ["early-deadline", "early-arrive", "late-arrive", "id-a", "id-b", "no-tie"]
        self.assertEqual(expected, [t.task_id for t in order_tasks(tasks, PRIORITY)])

    def test_all_tied_falls_back_to_task_id(self) -> None:
        tasks = [make("t3"), make("t1"), make("t2")]
        self.assertEqual(["t1", "t2", "t3"], [t.task_id for t in order_tasks(tasks, PRIORITY)])


class InterfaceTests(unittest.TestCase):
    def test_empty_candidate_list(self) -> None:
        self.assertEqual([], order_tasks([], PRIORITY))
        self.assertEqual([], rank_tasks([], PRIORITY))
        self.assertEqual("", format_ranking([], PRIORITY))

    def test_order_tasks_does_not_mutate_input(self) -> None:
        tasks = [make("T2", submitted=2), make("T1", submitted=1)]
        tasks[0].state = TaskState.BLOCKED
        tasks[0].waiting_reason = "resource occupied"
        snapshot = [asdict(t) for t in tasks]
        for policy in (FCFS, PRIORITY):
            ordered = order_tasks(tasks, policy)
            self.assertIsNot(ordered, tasks)
            self.assertEqual({id(t) for t in ordered}, {id(t) for t in tasks})
            rank_tasks(tasks, policy)
            format_ranking(tasks, policy)
            self.assertEqual(snapshot, [asdict(t) for t in tasks])

    def test_rank_matches_order_and_covers_every_task(self) -> None:
        tasks = [make("T1", priority=2), make("T2", priority=3), make("T3", priority=1)]
        ranked = rank_tasks(tasks, PRIORITY)
        self.assertEqual([t.task_id for t in order_tasks(tasks, PRIORITY)], [t.task_id for t, _ in ranked])
        self.assertEqual(len(tasks), len(ranked))

    def test_reason_explains_actual_priority(self) -> None:
        tasks = [make("a", priority=2, deadline=10), make("b", priority=3, deadline=10, urgent=True)]
        ranked = rank_tasks(tasks, PRIORITY)
        self.assertEqual("b", ranked[0][0].task_id)
        self.assertNotIn("紧急", ranked[0][1])
        self.assertIn("优先级更高", ranked[0][1])

    def test_urgent_flag_does_not_change_order_or_reason(self) -> None:
        tasks = [make("a", deadline=30), make("b", deadline=10)]
        for policy in (FCFS, PRIORITY):
            before = [(t.task_id, r) for t, r in rank_tasks(tasks, policy)]
            for task in tasks:
                task.urgent = not task.urgent
            self.assertEqual(before, [(t.task_id, r) for t, r in rank_tasks(tasks, policy)])

    def test_reason_for_tied_priority_mentions_deadline(self) -> None:
        earlier = make("early", priority=1, deadline=20)
        later = make("late", priority=1, deadline=30)
        self.assertIn("截止时间更早", explain(earlier, later, PRIORITY))

    def test_unknown_policy_raises(self) -> None:
        for function in (order_tasks, rank_tasks, format_ranking):
            for tasks in ([], [make("A")]):
                with self.subTest(function=function.__name__, empty=not tasks), self.assertRaises(ValueError):
                    function(tasks, "sjf")
        with self.assertRaises(ValueError):
            selection_reason("sjf")
        for other in (None, make("B")):
            with self.subTest(other=other), self.assertRaises(ValueError):
                explain(make("A"), other, "sjf")

    def test_reversed_pair_cannot_produce_false_comparison(self) -> None:
        for policy in (FCFS, PRIORITY):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                explain(make("B"), make("A"), policy)

    def test_equal_keys_do_not_claim_strict_inequality(self) -> None:
        for policy in (FCFS, PRIORITY):
            self.assertEqual(explain(make("A"), make("A"), policy), "排序键相同，保留输入次序")

    def test_selection_reason_known_policies(self) -> None:
        self.assertIn("FCFS", selection_reason(FCFS))
        self.assertIn("priority", selection_reason(PRIORITY))

    def test_deterministic_repeated_calls(self) -> None:
        tasks = [make("T%d" % i, priority=(i % 2) + 1, deadline=10, submitted=i % 3) for i in range(1, 8)]
        first = [t.task_id for t in order_tasks(tasks, PRIORITY)]
        for _ in range(5):
            self.assertEqual(first, [t.task_id for t in order_tasks(tasks, PRIORITY)])


class CaseFileTests(unittest.TestCase):

    def test_all_cases(self) -> None:
        with CASES_PATH.open("r", encoding="utf-8") as handle:
            cases = json.load(handle)["cases"]
        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            with self.subTest(case=case["case_id"]):
                tasks = [task_from_dict(item) for item in case["tasks"]]
                actual = [t.task_id for t in order_tasks(tasks, case["policy"])]
                self.assertEqual(case["expected"], actual)

    def test_reason_names_first_decisive_key(self) -> None:
        pairs = [
            (FCFS, make("Z", submitted=0), make("A", submitted=2), "到达更早"),
            (FCFS, make("A", priority=1), make("B", priority=9), "任务编号"),
            (PRIORITY, make("Z", priority=3, deadline=30), make("A", priority=1, deadline=1), "优先级更高"),
            (PRIORITY, make("Z", deadline=10, submitted=5), make("A", deadline=20), "截止时间更早"),
            (PRIORITY, make("Z", submitted=1), make("A", submitted=5), "到达更早"),
            (PRIORITY, make("A"), make("B"), "任务编号"),
        ]
        for policy, first, second, label in pairs:
            with self.subTest(policy=policy, label=label):
                self.assertIn(label, explain(first, second, policy))


class ValidationCommandTests(unittest.TestCase):
    def command(self, *args, cwd):
        return subprocess.run([sys.executable, str(ROOT / "scripts/check_policies.py"), *args],
                              cwd=cwd, capture_output=True, text=True, timeout=10)

    def test_command_works_outside_repo_and_archives_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "record.json"
            result = self.command("--json-out", str(archive), cwd=folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(archive.read_text())
            self.assertEqual(record["summary"], {"total": 10, "passed": 10, "failed": 0})
            self.assertEqual(record["cases"][0]["tasks"], json.loads(CASES_PATH.read_text())["cases"][0]["tasks"])
            self.assertEqual(len(record["meta"]["cases_sha256"]), 64)
            self.assertEqual(len(record["meta"]["source_sha256"]), 64)

    def test_wrong_expected_fails_without_rewriting_case(self):
        document = json.loads(CASES_PATH.read_text())
        document["cases"][0]["expected"].reverse()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            path.write_text(json.dumps(document))
            before = path.read_bytes()
            result = self.command("--cases", str(path), "--no-archive", cwd=folder)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("不通过", result.stdout)
            self.assertEqual(before, path.read_bytes())

    def test_archive_cannot_overwrite_case_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            path.write_bytes(CASES_PATH.read_bytes())
            before = path.read_bytes()
            result = self.command("--cases", str(path), "--json-out", str(path), cwd=folder)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_case_sets_do_not_silently_pass(self):
        valid = json.loads(CASES_PATH.read_text())
        invalid = []
        empty = deepcopy(valid)
        empty["cases"] = []
        invalid.append(empty)
        for field, value in (("policy", "sjf"), ("observed_at", 0), ("expected", [])):
            doc = deepcopy(valid)
            doc["cases"][0][field] = value
            invalid.append(doc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            for doc in invalid:
                with self.subTest(doc=doc["cases"][:1]):
                    path.write_text(json.dumps(doc))
                    result = self.command("--cases", str(path), "--no-archive", cwd=folder)
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn("Traceback", result.stderr)


class SchedulingLogTests(unittest.TestCase):
    def run_tasks(self, tasks, events=(), **config):
        return Scheduler(tasks, {"x": Resource("x"), "y": Resource("y")},
                         SchedulerConfig(max_time=15, **config), events).run()

    def starts(self, result):
        return [e for e in result["trace"] if e["event"] in ("start", "resume", "stage_start")]

    def test_actual_start_records_priority_and_tie_break(self):
        for policy, label in ((FCFS, "任务编号"), (PRIORITY, "截止时间更早")):
            result = self.run_tasks([make("A", deadline=10), make("B", deadline=20)],
                                    policy=policy, workers=1, preemptive=False)
            first = self.starts(result)[0]
            self.assertEqual(first["task_id"], "A")
            self.assertIn(label, first["reason"])
            self.assertEqual(first["ordering"]["compared_to"], "B")
            self.assertEqual(first["ordering"]["rank"], 1)

    def test_future_and_dependency_blocked_tasks_are_not_candidates(self):
        current, future, dependent = make("A"), make("F", priority=9, submitted=3), make("D", priority=8)
        dependent.dependencies = ["A"]
        result = self.run_tasks([future, dependent, current])
        initial = [e for e in self.starts(result) if e["time"] == 0]
        self.assertEqual([e["task_id"] for e in initial], ["A"])
        self.assertEqual(initial[0]["ordering"]["candidate_count"], 1)
        self.assertIsNone(initial[0]["ordering"]["compared_to"])
        self.assertEqual(result["tasks"]["F"]["started_at"], 3)

    def test_blocked_head_can_be_skipped_without_claiming_first_rank(self):
        holder = Task("H", "holder", 9, 20, 3, resources={"x": 1})
        blocked = Task("B", "blocked", 2, 20, 1, resources={"x": 1}, submitted_at=1)
        runnable = Task("C", "runnable", 1, 20, 1, resources={"y": 1}, submitted_at=1)
        result = self.run_tasks([holder, blocked, runnable], preemptive=False, banker_enabled=False)
        event = next(e for e in self.starts(result) if e["task_id"] == "C")
        self.assertEqual(event["time"], 1)
        self.assertEqual(event["ordering"]["rank"], 2)
        self.assertEqual(event["ordering"]["candidate_count"], 2)
        self.assertTrue(any(e["event"] == "resource_wait" and e["task_id"] == "B" for e in result["trace"]))

    def test_static_queue_keeps_initial_and_appended_order(self):
        tasks = [Task("A", "A", 1, 20, 3, resources={"x": 1}),
                 Task("B", "B", 1, 20, 1, resources={"x": 1})]
        events = [Interrupt(1, InterruptType.REQUEST, "later", task=Task("C", "C", 1, 20, 1, resources={"x": 1})),
                  Interrupt(2, InterruptType.URGENT, "urgent", task=Task("U", "U", 9, 20, 1, resources={"x": 1}))]
        static = self.run_tasks(tasks, events, dynamic_rescheduling=False)
        starts = self.starts(static)
        self.assertEqual([e["task_id"] for e in starts], ["A", "B", "C", "U"])
        self.assertIn("保持 t=0 初始队列次序", starts[0]["reason"])
        self.assertIn("初始队列任务先于后续到达任务", starts[1]["reason"])
        self.assertIn("到达时间、任务编号追加", starts[2]["reason"])
        self.assertTrue(all(e["ordering"]["mode"] == "static" for e in starts))
        dynamic = self.run_tasks(tasks, events)
        self.assertLess(dynamic["tasks"]["U"]["started_at"], dynamic["tasks"]["B"]["started_at"])

    def test_resume_and_stage_events_keep_explanations(self):
        from tea_break_scheduler.scenarios import build_scheduler
        result = build_scheduler("baseline").run()
        events = self.starts(result)
        self.assertTrue(any(e["event"] == "resume" for e in events))
        self.assertTrue(any(e["event"] == "stage_start" for e in events))
        self.assertTrue(all("ordering" in e and "资源检查通过" in e["reason"] for e in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
