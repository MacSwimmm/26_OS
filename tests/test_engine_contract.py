"""Hand-calculated regressions for the course specification and audit defects."""
import unittest
from dataclasses import replace

from tea_break_scheduler.deadlock import BankerState, choose_recovery_victim, request_is_safe
from tea_break_scheduler.models import Interrupt, InterruptType as Kind, Resource, SchedulerConfig, Task, TaskStage
from tea_break_scheduler.resources import ResourceManager
from tea_break_scheduler.scenarios import build_scheduler, config_for, deadlock_tasks
from tea_break_scheduler.scheduler import Scheduler
from tea_break_scheduler.scenario_io import scenario_document, scenario_from_dict


def task(tid="A", duration=2, **kwargs):
    return Task(tid, tid, kwargs.pop("priority", 1), kwargs.pop("deadline", 20), duration, **kwargs)


def run(tasks, events=(), **config):
    return Scheduler(tasks, {r: Resource(r) for r in ("x", "y", "z")},
                     SchedulerConfig(max_time=10, **config), events).run()


class InputTests(unittest.TestCase):
    def test_reject_unknown_resource_before_simulation(self):
        with self.assertRaisesRegex(ValueError, "unknown resource"):
            run([task(resources={"missing": 1})])

    def test_reject_unknown_and_cyclic_dependencies(self):
        for tasks in ([task(dependencies=["B"])],
                      [task("A", dependencies=["B"]), task("B", dependencies=["A"])]):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                run(tasks)

    def test_event_task_dependencies_are_validated_up_front(self):
        with self.assertRaises(ValueError):
            run([], [Interrupt(2, Kind.URGENT, "bad", task=task(dependencies=["missing"]))])

    def test_duplicate_ids_including_future_events(self):
        for events in ([], [Interrupt(2, Kind.REQUEST, "duplicate", task=task())]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                run([task(), task()] if not events else [task()], events)

    def test_fractional_negative_or_zero_times_are_invalid(self):
        for duration in (-1, 0, 1.5, True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                task(duration=duration)
        with self.assertRaises(ValueError):
            Interrupt(-1, Kind.REQUEST, "bad", task=task())
        with self.assertRaises(ValueError):
            Interrupt(1, Kind.FAULT, "no duration", resource="x")

    def test_stage_duration_and_claims_are_consistent(self):
        with self.assertRaises(ValueError):
            task(duration=2, stages=[TaskStage("one", 1)])
        with self.assertRaises(ValueError):
            task(stages=[TaskStage("one", 2, {"x": 1})], max_claim={"y": 1})
        with self.assertRaises(ValueError):
            run([task(stages=[TaskStage("one", 2, release_resources=["x"])])])

    def test_single_instance_scope_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "single-instance"):
            Resource("x", capacity=2)

    def test_no_banker_bypass_of_claim_validation(self):
        t = task(resources={"x": 1})
        manager = ResourceManager({"x": Resource("x")}, banker_enabled=False)
        for request in ({"x": 2}, {"x": -1}, {"missing": 1}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                manager.try_acquire(t, {"A": t}, 0, request)
        self.assertEqual(manager.allocation, {})

    def test_json_roundtrip_preserves_nested_stages_and_event_enums(self):
        scheduler = build_scheduler()
        result = scenario_from_dict(scheduler.input_document).run()
        self.assertEqual(result["metrics"], scheduler.run()["metrics"])
        self.assertIn("input_sha256", result["metadata"])
        for malformed in ({"resources": []}, {"resources": {"x": []}},
                          {"resources": {}, "tasks": {}}, {"resources": {}, "events": [1]},
                          {"resources": {}, "config": []}, {"resources": {}, "seed": "one"}):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                scenario_from_dict(malformed)

    def test_inputs_are_reusable_and_scheduler_runs_once(self):
        original = task(resources={"x": 1})
        first = run([original])
        self.assertEqual(original.completed_work, 0)
        self.assertEqual(first["metrics"], run([original])["metrics"])
        scheduler = Scheduler([original], {"x": Resource("x")})
        scheduler.run()
        with self.assertRaises(ValueError):
            scheduler.run()


class OrderingTests(unittest.TestCase):
    def test_fcfs_and_priority_have_real_different_orders(self):
        tasks = [task("A", resources={"x": 1}), task("B", priority=3, resources={"x": 1})]
        self.assertEqual(run(tasks, policy="fcfs")["tasks"]["A"]["finished_at"], 2)
        self.assertEqual(run(tasks)["tasks"]["B"]["finished_at"], 2)

    def test_priority_ties_use_deadline_then_id(self):
        tasks = [task("Z", deadline=15, resources={"x": 1}),
                 task("B", deadline=10, resources={"x": 1}),
                 task("A", deadline=10, resources={"x": 1})]
        starts = [e["task_id"] for e in run(tasks)["trace"] if e["event"] == "start"]
        self.assertEqual(starts, ["A", "B", "Z"])

    def test_blocked_head_does_not_idle_other_resources(self):
        result = run([task("A", priority=3, resources={"x": 1}),
                      task("B", priority=2, resources={"x": 1}), task("C", resources={"y": 1})])
        self.assertEqual(result["tasks"]["C"]["started_at"], 0)

    def test_static_appends_future_urgent_dynamic_reorders(self):
        tasks = [task("A", duration=3, resources={"x": 1}), task("B", resources={"x": 1})]
        events = [Interrupt(1, Kind.URGENT, "arrival", task=task("U", priority=9, resources={"x": 1}))]
        static = run(tasks, events, dynamic_rescheduling=False)
        dynamic = run(tasks, events)
        self.assertGreater(static["tasks"]["U"]["started_at"], static["tasks"]["B"]["started_at"])
        self.assertEqual(dynamic["tasks"]["U"]["started_at"], 1)
        self.assertEqual(dynamic["tasks"]["A"]["completed_work"], 3)

    def test_nonpreemptible_step_and_dependency_block_urgent(self):
        initial = task(duration=4, resources={"x": 1}, preemptible=False)
        urgent = task("U", duration=1, priority=9, resources={"x": 1})
        result = run([initial], [Interrupt(1, Kind.URGENT, "arrival", task=urgent)])
        self.assertEqual(result["metrics"]["preemptions"], 0)
        self.assertEqual(result["tasks"]["U"]["started_at"], 4)
        urgent.dependencies = ["A"]
        result = run([replace(initial, preemptible=True)], [Interrupt(1, Kind.URGENT, "dependent", task=urgent)])
        self.assertEqual(result["metrics"]["preemptions"], 0)

    def test_default_concurrency_has_no_hidden_staff_limit(self):
        result = run([task("A", resources={"x": 1}), task("B", resources={"y": 1}),
                      task("C", resources={"z": 1}), task("D")])
        self.assertTrue(all(t["started_at"] == 0 for t in result["tasks"].values()))

    def test_stage_flag_blocks_preemption_even_if_task_allows_it(self):
        staged = task(duration=3, stages=[TaskStage("atomic", 3, {"x": 1}, preemptible=False)])
        result = run([staged], [Interrupt(1, Kind.URGENT, "urgent", task=task("U", priority=9, resources={"x": 1}))])
        self.assertEqual(result["metrics"]["preemptions"], 0)
        self.assertEqual(result["tasks"]["U"]["started_at"], 3)

    def test_comparisons_change_only_the_declared_settings(self):
        base = SchedulerConfig()
        self.assertEqual(config_for("no_dynamic"), replace(base, dynamic_rescheduling=False))
        self.assertEqual(config_for("non_preemptive"), replace(base, preemptive=False))
        self.assertTrue(config_for("no_deadlock").deadlock_detection)


class InterruptTests(unittest.TestCase):
    def test_fault_keeps_ownership_without_advancing_work(self):
        scheduler = Scheduler([task(duration=4, resources={"x": 1})], {"x": Resource("x")},
                              SchedulerConfig(max_time=10), [Interrupt(1, Kind.FAULT, "fault", resource="x", duration=2)])
        states = {}
        def collect(now, tasks, events):
            states[now] = (dict(scheduler.resource_manager.allocation.get("A", {})), tasks["A"].completed_work)
        result = scheduler.run(collect)
        self.assertEqual(states[1], ({"x": 1}, 1))
        self.assertEqual(states[2], ({"x": 1}, 1))
        self.assertEqual(result["tasks"]["A"]["finished_at"], 6)
        self.assertEqual(result["metrics"]["resource_outage_held_ticks"]["x"], 2)

    def test_fault_on_retained_resource_pauses_next_stage(self):
        staged = task(duration=4, stages=[TaskStage("reserve", 1, {"x": 1}), TaskStage("transfer", 3, {"y": 1})])
        result = run([staged], [Interrupt(2, Kind.FAULT, "retained", resource="x", duration=2)])
        self.assertEqual(result["tasks"]["A"]["finished_at"], 6)
        self.assertEqual(result["tasks"]["A"]["completed_work"], 4)

    def test_preemption_reacquires_all_retained_resources(self):
        staged = task(duration=4, stages=[TaskStage("reserve", 1, {"x": 1}), TaskStage("transfer", 3, {"y": 1})])
        urgent = task("U", duration=1, priority=9, resources={"y": 1})
        result = run([staged], [Interrupt(2, Kind.URGENT, "urgent", task=urgent)])
        resume = next(e for e in result["trace"] if e["event"] == "resume")
        self.assertEqual(resume["acquired"], {"x": 1, "y": 1})
        self.assertEqual(result["tasks"]["A"]["completed_work"], 4)

    def test_overlapping_outages_wait_for_every_resource(self):
        events = [Interrupt(1, Kind.FAULT, "x", resource="x", duration=2),
                  Interrupt(2, Kind.ENVIRONMENT, "y", resource="y", duration=3)]
        result = run([task(duration=3, resources={"x": 1, "y": 1})], events)
        self.assertEqual(result["tasks"]["A"]["finished_at"], 7)

    def test_explicit_restore_can_resume_early(self):
        events = [Interrupt(1, Kind.FAULT, "x", resource="x", duration=8),
                  Interrupt(3, Kind.RESTORE, "repaired", resource="x")]
        result = run([task(duration=3, resources={"x": 1})], events)
        self.assertEqual(result["tasks"]["A"]["finished_at"], 5)

    def test_cup_events_create_one_recycle_task(self):
        events = [Interrupt(1, Kind.CUP_TAKEN, "cup", task=task("R"), cup_id="cup-1"),
                  Interrupt(2, Kind.CUP_TAKEN, "duplicate", task=task("R"), cup_id="cup-1")]
        result = run([], events)
        self.assertEqual(result["metrics"]["total_tasks"], 1)
        self.assertEqual(sum(e["event"] == "duplicate_cup_ignored" for e in result["trace"]), 1)

    def test_baseline_actually_demonstrates_three_interrupts(self):
        result = build_scheduler().run()
        reasons = [e["reason"] for e in result["trace"] if e["event"] == "pause"]
        self.assertIn("fault interruption", reasons)
        self.assertIn("environment interruption", reasons)
        self.assertEqual(result["metrics"]["preemptions"], 1)


class DeadlockContractTests(unittest.TestCase):
    def test_failed_banker_trial_is_atomic(self):
        state = BankerState({"x": 1, "y": 0}, {"B": {"y": 1}},
                            {"A": {"x": 1, "y": 1}, "B": {"x": 1, "y": 1}})
        original = state.clone()
        self.assertFalse(request_is_safe(state, "A", {"x": 1}))
        self.assertEqual(state, original)
        self.assertFalse(request_is_safe(state, "missing", {}))

    def test_recovery_tie_prefers_less_redo_work(self):
        a, b = task("A"), task("B")
        a.completed_work, b.completed_work = 2, 1
        self.assertEqual(choose_recovery_victim({"A": a, "B": b}, ["A", "B"]), "B")

    def test_unrecoverable_cycle_is_reported_once(self):
        tasks = [replace(t, rollback_allowed=False) for t in deadlock_tasks()]
        result = Scheduler(tasks, {r: Resource(r) for r in ("tea_table", "return_station")},
                           SchedulerConfig(banker_enabled=False, max_time=10)).run()
        self.assertEqual(result["metrics"]["deadlock_count"], 1)
        self.assertEqual(sum(e["event"] == "deadlock_unresolved" for e in result["trace"]), 1)
        self.assertEqual(len(result["unfinished"]), 2)

    def test_checkpoint_preserves_completed_prefix_during_rollback(self):
        tasks = [task("A", duration=3, priority=2, rollback_allowed=True, stages=[
                    TaskStage("committed prefix", 1), TaskStage("hold x", 1, {"x": 1}, preemptible=False),
                    TaskStage("need y", 1, {"y": 1}, preemptible=False)]),
                 task("B", duration=3, rollback_allowed=True, stages=[
                    TaskStage("committed prefix", 1), TaskStage("hold y", 1, {"y": 1}, preemptible=False),
                    TaskStage("need x", 1, {"x": 1}, preemptible=False)])]
        result = run(tasks, banker_enabled=False)
        rollback = next(e for e in result["trace"] if e["event"] == "rollback")
        self.assertEqual(rollback["checkpoint"], 1)
        self.assertEqual(rollback["lost_work"], 1)
        self.assertEqual(result["tasks"]["B"]["completed_work"], 3)
        self.assertEqual(result["metrics"]["redo_work"], 1)

    def test_busy_time_is_distinct_from_holding_while_deadlocked(self):
        tasks = deadlock_tasks()
        result = Scheduler(tasks, {r: Resource(r) for r in ("tea_table", "return_station")},
                           SchedulerConfig(banker_enabled=False, deadlock_recovery=False, max_time=20)).run()
        self.assertEqual(result["metrics"]["resource_utilization_by_resource"]["tea_table"], .05)
        self.assertEqual(result["metrics"]["resource_occupancy_by_resource"]["tea_table"], 1)

    def test_retry_limit_cancels_and_releases(self):
        tasks = [replace(t, max_retries=0) for t in deadlock_tasks()]
        result = Scheduler(tasks, {r: Resource(r) for r in ("tea_table", "return_station")},
                           SchedulerConfig(banker_enabled=False, max_time=10)).run()
        self.assertEqual(result["metrics"]["cancelled_tasks"], 1)
        self.assertEqual(result["metrics"]["completed_tasks"], 1)


class MetricBoundaryTests(unittest.TestCase):
    def test_idle_tail_stays_in_denominator(self):
        metrics = run([task(duration=2, resources={"x": 1})])["metrics"]
        self.assertEqual(metrics["resource_utilization_by_resource"]["x"], .2)
        self.assertEqual(metrics["resource_available_ticks"]["x"], 10)

    def test_h_completion_counts_but_h_arrival_does_not_execute(self):
        tasks = [task(duration=10, resources={"x": 1}), task("future", submitted_at=11)]
        result = run(tasks, [Interrupt(10, Kind.URGENT, "at H", task=task("U", duration=1, deadline=10))])
        self.assertEqual(result["metrics"]["total_tasks"], 2)
        self.assertEqual(result["metrics"]["completed_tasks"], 1)
        self.assertEqual(result["tasks"]["A"]["finished_at"], 10)
        self.assertEqual(result["tasks"]["U"]["completed_work"], 0)
        self.assertEqual(result["metrics"]["urgent_task_miss_rate"], 1)

    def test_urgent_denominator_excludes_deadlines_beyond_h(self):
        metrics = run([task("miss", duration=20, urgent=True, deadline=2),
                       task("later", duration=20, urgent=True, deadline=15)])["metrics"]
        self.assertEqual(metrics["urgent_eligible_tasks"], 1)
        self.assertEqual(metrics["urgent_task_miss_rate"], 1)
        self.assertIsNone(metrics["average_completion_delay"])

    def test_outage_wait_is_not_an_ownership_conflict(self):
        result = run([task(resources={"x": 1})], [Interrupt(0, Kind.FAULT, "closed", resource="x", duration=2)])
        self.assertEqual(result["metrics"]["conflict_count"], 0)
        self.assertEqual(result["metrics"]["resource_available_ticks"]["x"], 8)

    def test_continuous_wait_counts_once(self):
        metrics = run([task("A", duration=4, resources={"x": 1}), task("B", resources={"x": 1})])["metrics"]
        self.assertEqual(metrics["conflict_count"], 1)

    def test_shared_board_is_read_only_and_not_a_mutex(self):
        board = Resource("board", shared=True)
        scheduler = Scheduler([task("A", resources={"board": 1}), task("B", resources={"board": 1})], {"board": board})
        result = scheduler.run()
        self.assertEqual(result["tasks"]["A"]["started_at"], 0)
        self.assertEqual(result["tasks"]["B"]["started_at"], 0)
        self.assertEqual(result["metrics"]["resource_available_ticks"], {})
        with self.assertRaises(TypeError):
            scheduler.request_board["A"]["priority"] = 100

    def test_empty_denominators_are_null(self):
        result = run([])
        self.assertIsNone(result["metrics"]["completion_rate"])
        self.assertIsNone(result["metrics"]["urgent_task_miss_rate"])
        metrics = run([task()], [Interrupt(0, Kind.FAULT, "all window", resource="x", duration=10)])["metrics"]
        self.assertIsNone(metrics["resource_utilization_by_resource"]["x"])


if __name__ == "__main__":
    unittest.main()
