import unittest

from tea_break_scheduler.deadlock import BankerState, build_wait_for_graph, find_cycles, is_safe, request_is_safe
from tea_break_scheduler.models import Resource, SchedulerConfig, Task
from tea_break_scheduler.resources import ResourceManager
from tea_break_scheduler.scenarios import build_scheduler


class DeadlockTests(unittest.TestCase):
    def test_banker_safe_state(self):
        state = BankerState(
            available={"A": 1, "B": 1},
            allocation={"T1": {"A": 1}, "T2": {"B": 1}},
            maximum={"T1": {"A": 1, "B": 1}, "T2": {"A": 1, "B": 1}},
        )
        self.assertTrue(is_safe(state)[0])
        self.assertTrue(request_is_safe(state, "T1", {"B": 1}))

    def test_wait_for_cycle(self):
        graph = build_wait_for_graph(
            {"A": {"tea_table": 1}, "B": {"return_station": 1}},
            {"A": {"return_station": 1}, "B": {"tea_table": 1}},
        )
        self.assertEqual(find_cycles(graph), [["A", "B"]])


class SchedulerTests(unittest.TestCase):
    def test_baseline_finishes_tasks(self):
        result = build_scheduler("baseline").run()
        self.assertGreater(result["metrics"]["completed_tasks"], 0)
        self.assertIn("completion_rate", result["metrics"])
        self.assertTrue(result["trace"])

    def test_conflict_is_recorded(self):
        resources = {"table": Resource("table", capacity=1)}
        tasks = [
            Task("A", "A", 1, 20, 3, resources={"table": 1}),
            Task("B", "B", 1, 20, 3, resources={"table": 1}),
        ]
        manager = ResourceManager(resources)
        self.assertTrue(manager.try_acquire(tasks[0], {t.task_id: t for t in tasks}, 0).granted)
        self.assertFalse(manager.try_acquire(tasks[1], {t.task_id: t for t in tasks}, 0).granted)


if __name__ == "__main__":
    unittest.main()
