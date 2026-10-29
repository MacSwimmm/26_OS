import unittest

from tea_break_scheduler.deadlock import BankerState, build_wait_for_graph, find_cycles, is_safe, request_is_safe
from tea_break_scheduler.models import Interrupt, InterruptType, Resource, SchedulerConfig, Task, TaskStage
from tea_break_scheduler.resources import ResourceManager
from tea_break_scheduler.scheduler import Scheduler
from tea_break_scheduler.scenarios import build_scheduler, deadlock_demo


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

    def test_stage_resources_are_requested_incrementally_and_released(self):
        task = Task("A", "两步任务", 1, 20, 2, stages=[
            TaskStage("取物", 1, {"pickup": 1}, release_resources=["pickup"]),
            TaskStage("整理", 1, {"table": 1}),
        ])
        result = Scheduler([task], {"pickup": Resource("pickup"), "table": Resource("table")},
                            SchedulerConfig(max_time=5)).run()
        events = [item["event"] for item in result["trace"]]
        self.assertEqual(result["tasks"]["A"]["state"], "completed")
        self.assertIn("stage_complete", events)
        self.assertEqual(result["metrics"]["average_response_time"], 2.0)

    def test_urgent_interrupt_preempts_resource_holder_and_resumes(self):
        regular = Task("R", "普通任务", 1, 20, 4, resources={"table": 1})
        urgent = Task("U", "紧急任务", 5, 8, 1, resources={"table": 1}, urgent=True)
        scheduler = Scheduler(
            [regular], {"table": Resource("table")},
            SchedulerConfig(workers=2, preemptive=True, dynamic_rescheduling=True, max_time=10),
            [Interrupt(1, InterruptType.URGENT, "紧急请求", task=urgent)],
        )
        result = scheduler.run()
        event_names = [item["event"] for item in result["trace"]]
        self.assertIn("preempt", event_names)
        self.assertEqual(result["tasks"]["U"]["state"], "completed")
        self.assertEqual(result["tasks"]["R"]["state"], "completed")
        self.assertEqual(result["tasks"]["R"]["completed_work"], 4)

    def test_environment_pause_preserves_progress_until_restore(self):
        task = Task("A", "通道任务", 1, 20, 4, resources={"corridor": 1})
        scheduler = Scheduler(
            [task], {"corridor": Resource("corridor")},
            SchedulerConfig(max_time=10),
            [Interrupt(1, InterruptType.ENVIRONMENT, "封闭通道", resource="corridor", duration=2)],
        )
        result = scheduler.run()
        events = [item["event"] for item in result["trace"]]
        self.assertIn("pause", events)
        self.assertIn("resume_ready", events)
        self.assertEqual(result["tasks"]["A"]["completed_work"], 4)
        self.assertEqual(result["tasks"]["A"]["finished_at"], 6)

    def test_deadlock_modes_are_integrated_with_staged_tasks(self):
        result = deadlock_demo()
        self.assertEqual(result["avoidance"]["metrics"]["deadlock_count"], 0)
        self.assertGreater(result["avoidance"]["metrics"]["safety_rejection_count"], 0)
        self.assertEqual(result["detection_only"]["metrics"]["deadlock_count"], 1)
        self.assertEqual(result["detection_only"]["stop_reason"], "max_time")
        recovered = result["detection_and_recovery"]
        self.assertEqual(recovered["metrics"]["rollback_count"], 1)
        self.assertGreater(recovered["metrics"]["rollback_work"], 0)
        self.assertEqual(recovered["metrics"]["completed_tasks"], 2)


if __name__ == "__main__":
    unittest.main()
