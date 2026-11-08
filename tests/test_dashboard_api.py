"""HTTP contract checks against an actual local server (no external services)."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard_server import DashboardHandler, _run_single


class SnapshotTests(unittest.TestCase):
    def test_clock_progress_and_final_metrics_match(self):
        data = _run_single("baseline")
        initial, final = data["snapshots"][0], data["snapshots"][-1]
        self.assertEqual(initial["time"], 0)
        self.assertEqual(initial["tasks"]["T1"]["completed_work"], 0)
        self.assertNotIn("U1", initial["tasks"])
        self.assertEqual(final["time"], 14)
        self.assertEqual(final["metrics"], data["result"]["metrics"])
        for snapshot in data["snapshots"]:
            for task in snapshot["tasks"].values():
                if task["state"] == "completed":
                    self.assertLessEqual(task["finished_at"], snapshot["time"])
                    self.assertEqual(task["completed_work"], task["duration"])
            for resource in snapshot["resources"].values():
                self.assertLessEqual(sum(resource["holders"].values()), resource["capacity"])
        fault = data["snapshots"][3]
        self.assertEqual(fault["resources"]["tea_table"]["holders"], {"T2": 1})


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class QuietHandler(DashboardHandler):
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, data=None):
        request = Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        return urlopen(request, timeout=10)

    def test_health_config_and_new_scenario_are_available(self):
        with self.request("/api/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")
        with self.request("/api/config") as response:
            self.assertEqual(json.load(response)["footerText"], "TeaFlow OS")
        with self.request("/api/scenarios") as response:
            self.assertIn("fcfs", [s["id"] for s in json.load(response)["scenarios"]])

    def test_every_frontend_dependency_is_served(self):
        import re
        from dashboard_server import ROOT
        html = (ROOT / "dashboard.html").read_text()
        for path in re.findall(r'(?:src|href)="(assets/[^\"]+)"', html):
            with self.subTest(path=path), self.request("/" + path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_comparison_and_deadlock_use_engine_results(self):
        for name, count in (("compare", 5), ("deadlock", 3)):
            with self.subTest(name=name), self.request("/api/run", {"scenario": name}) as response:
                data = json.load(response)
                self.assertEqual(len(data["comparisons"]), count)
                self.assertEqual(data["comparisons"][0]["completion_rate"], 1)

    def test_malformed_json_shapes_are_400_not_server_errors(self):
        for payload in ([], None, {"scenario": []}, {"scenario": "missing"}):
            request = Request(self.base + "/api/run", data=json.dumps(payload).encode(), method="POST")
            with self.subTest(payload=payload), self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=5)
            self.assertEqual(caught.exception.code, 400)
            self.assertIn("error", json.load(caught.exception))

    def test_static_route_does_not_allow_arbitrary_files(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/assets/../tea_break_scheduler/scheduler.py")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
