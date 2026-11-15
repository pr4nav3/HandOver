"""Offline checks for warehouse aggregation, revision safety and access control."""
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from server import lesson_insights as insights, library, routes_library


LESSON = {"steps": [{"n": 1, "title": "Align", "start": "00:00", "end": "00:04", "check_type": "camera"},
                    {"n": 2, "title": "Finish", "start": "00:04", "end": "00:08", "check_type": "manual"}]}


def events(run="real", **tags):
    return [{"event_id": f"{run}-{i}", "run_id": run, "lesson_id": "c1", **row} for i, row in enumerate([
        {"kind": "run_start", "total": 2, **tags},
        {"kind": "step_enter", "step": 0, "expert_seconds": 4},
        {"kind": "advance", "from_step": 0, "to_step": 1, "reason": "camera", "step_seconds": 6},
        {"kind": "step_enter", "step": 1, "expert_seconds": 4},
        {"kind": "advance", "from_step": 1, "to_step": 2, "reason": "button", "step_seconds": 8},
        {"kind": "run_done", "total": 2}])]


class InsightTests(unittest.TestCase):
    def setUp(self):
        insights._cache.clear()

    def test_cloud_local_duplicates_and_manual_denominators(self):
        rows = events()
        insights._cache[("c1", "")] = {"events": rows, "checked": 1, "busy": False,
            "fetched_at": "2026-11-15T00:00:00Z", "error": False}
        with patch.object(insights.db, "_enabled", return_value=False), patch.object(library, "lesson_events", return_value=rows):
            out = insights.course("c1", LESSON, None)
        self.assertEqual(out["runs"], {"started": 1, "finished": 1, "n": 1})
        self.assertEqual(out["steps"][0]["median_seconds"], {"value": 6, "n": 1})
        self.assertEqual(out["steps"][1]["manual_rate"], {"value": None, "n": 0})
        self.assertEqual(out["sync"]["source"], "databricks")
        self.assertNotIn("event_id", json.dumps(out))

    def test_mock_replay_stale_and_old_cut_never_count(self):
        rows = events() + events("mock", check_mode="mock") + events("replay", source="file")
        old = events("old", lesson_revision="previous-cut")
        rows += old + [{"kind": "check", "run_id": "real", "stale": True}]
        current, previous = insights._current_events(insights._real_events(rows), LESSON)
        self.assertEqual(previous, 1)
        self.assertEqual(len(current), 6)
        old = events("older")
        old[1]["expert_seconds"] = 15
        self.assertEqual(insights._current_events(old, LESSON), ([], 1))

    def test_failure_keeps_local_results_and_labels_unavailability(self):
        insights._cache[("c1", "")] = {"events": [], "checked": 1, "busy": False,
            "fetched_at": None, "error": True}
        with patch.object(insights.db, "_enabled", return_value=False), patch.object(library, "lesson_events", return_value=events()):
            out = insights.course("c1", LESSON, None)
        self.assertEqual(out["runs"]["finished"], 1)
        self.assertEqual(out["sync"]["state"], "unavailable")

    def test_query_uses_parameters_and_rejects_truncation(self):
        response = {"status": {"state": "SUCCEEDED"}, "manifest": {"truncated": True}}
        with patch.object(insights.db, "_request", return_value=(200, json.dumps(response).encode())) as request:
            with self.assertRaises(RuntimeError):
                insights._read("lesson'unsafe", "2026-11-15T00:00:00Z")
        body = json.loads(request.call_args.args[2])
        self.assertNotIn("lesson'unsafe", body["statement"])
        self.assertIn("events_real", body["statement"])
        self.assertEqual(body["parameters"][0]["value"], "lesson'unsafe")

    def test_permission_checked_before_any_cloud_read(self):
        app = FastAPI()
        app.include_router(routes_library.router)
        with patch.object(routes_library, "_ctx", side_effect=HTTPException(403, "not allowed")) as ctx, patch.object(insights, "course") as read:
            response = TestClient(app).get("/api/courses/c1/analytics")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ctx.call_args.args[-1], "insights")
        read.assert_not_called()

    def test_export_waits_for_pending_failure_and_reports_it(self):
        replies = [(200, json.dumps({"statement_id": "sample", "status": {"state": "PENDING"}}).encode()),
                   (200, json.dumps({"status": {"state": "FAILED", "error": {"message": "rejected"}}}).encode())]
        with patch.object(insights.db, "_request", side_effect=replies), patch.object(insights.db.time, "sleep"):
            error = insights.db._execute("SELECT 1")
        self.assertIn("FAILED", error)

    def test_export_pending_success_is_confirmed(self):
        replies = [(200, json.dumps({"statement_id": "sample", "status": {"state": "RUNNING"}}).encode()),
                   (200, json.dumps({"status": {"state": "SUCCEEDED"}}).encode())]
        with patch.object(insights.db, "_request", side_effect=replies), patch.object(insights.db.time, "sleep"):
            self.assertIsNone(insights.db._execute("SELECT 1"))


if __name__ == "__main__":
    unittest.main()
