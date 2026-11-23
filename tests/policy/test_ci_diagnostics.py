"""CI observations keep queue, execution, matrix rows and attempts separate."""

from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import Mock, patch

from ci import cli, diagnostics, evidence

NOW = datetime(2026, 11, 15, 1, 10, tzinfo=timezone.utc)


def run():
    return {
        "id": 88,
        "run_attempt": 2,
        "repository": {"full_name": evidence.REPOSITORY},
        "head_repository": {"full_name": evidence.REPOSITORY},
        "path": evidence.WORKFLOW,
        "name": "CI",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "failure",
    }


def job(identifier=1, **values):
    return {
        "id": identifier,
        "run_id": 88,
        "run_attempt": 2,
        "name": f"python (Linux {identifier}/2)",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-11-15T01:00:00Z",
        "started_at": "2026-11-15T01:03:00Z",
        "completed_at": "2026-11-15T01:05:00Z",
        "steps": [],
        **values,
    }


def api(jobs, after=None):
    pages = [
        {"total_count": len(jobs), "jobs": jobs[start : start + 20]}
        for start in range(0, max(1, len(jobs)), 20)
    ]
    return Mock(spec=["get"], get=Mock(side_effect=[run(), *pages, after or run()]))


class DiagnosticsTests(unittest.TestCase):
    def test_queue_is_not_execution_and_matrix_rows_are_not_aggregated(self):
        source = api([job(), job(2, conclusion="failure")])
        report = diagnostics.inspect_run(88, source, NOW)
        self.assertEqual(report["run_attempt"], 2)
        self.assertEqual(
            [j["conclusion"] for j in report["jobs"]], ["success", "failure"]
        )
        self.assertEqual(report["jobs"][0]["queue_delay_seconds"], 180)
        self.assertEqual(report["jobs"][0]["execution_duration_seconds"], 120)
        source.get.assert_any_call("actions/runs/88/attempts/2/jobs?per_page=20&page=1")
        paths = [call.args[0] for call in source.get.call_args_list]
        self.assertEqual(paths.count("actions/runs/88"), 2)

    def test_nonterminal_and_skipped_times_do_not_claim_completion(self):
        jobs = [
            job(status="in_progress", conclusion=None, completed_at=None),
            job(
                2,
                status="queued",
                conclusion=None,
                started_at="2026-11-15T01:00:00Z",
                completed_at=None,
            ),
            job(3, conclusion="skipped"),
            job(4, conclusion="cancelled"),
            job(5, conclusion="timed_out", created_at=None),
        ]
        report = diagnostics.inspect_run(
            88, api(jobs, {**run(), "status": "in_progress", "conclusion": None}), NOW
        )
        self.assertEqual(report["status"], "in_progress")
        running, queued, skipped, cancelled, timed_out = report["jobs"]
        self.assertEqual(running["execution_elapsed_seconds"], 420)
        self.assertIsNone(running["execution_duration_seconds"])
        self.assertEqual(queued["queue_elapsed_seconds"], 600)
        self.assertIsNone(queued["execution_duration_seconds"])
        self.assertIsNone(queued["queue_delay_seconds"])
        self.assertIsNone(skipped["queue_delay_seconds"])
        self.assertIsNone(skipped["execution_duration_seconds"])
        self.assertEqual(cancelled["conclusion"], "cancelled")
        self.assertEqual(timed_out["conclusion"], "timed_out")
        self.assertIsNone(timed_out["queue_delay_seconds"])

    def test_first_failed_step_uses_step_order_and_does_not_guess_cause(self):
        steps = [
            {
                "number": number,
                "name": name,
                "status": "completed",
                "conclusion": conclusion,
            }
            for number, name, conclusion in [
                (8, "Retain native test results", "failure"),
                (3, "Test installed keyboard typing and activation", "failure"),
                (2, "Install native dependencies", "success"),
                (1, "Compile app and extensions without signing or upload", "success"),
            ]
        ]
        result = diagnostics.inspect_run(88, api([job(steps=steps)]), NOW)["jobs"][0]
        self.assertEqual(result["first_failed_step"]["number"], 3)
        self.assertEqual(
            [s["phases"] for s in result["steps"]],
            [["build"], ["setup"], ["native", "test"], []],
        )
        cancelled = [dict(step, conclusion="cancelled") for step in steps]
        self.assertIsNone(
            diagnostics.inspect_run(88, api([job(steps=cancelled)]), NOW)["jobs"][0][
                "first_failed_step"
            ]
        )

    def test_pagination_and_attempt_changes_fail_without_retry(self):
        source = api([job(i) for i in range(1, 22)])
        self.assertEqual(len(diagnostics.inspect_run(88, source, NOW)["jobs"]), 21)
        source.get.assert_any_call("actions/runs/88/attempts/2/jobs?per_page=20&page=2")
        for source in [
            api([job(run_attempt=1)]),
            api([job()], {**run(), "run_attempt": 3}),
        ]:
            with (
                self.subTest(api=source),
                self.assertRaisesRegex(ValueError, "attempt"),
            ):
                diagnostics.inspect_run(88, source, NOW)
            self.assertLessEqual(source.get.call_count, 3)

    def test_foreign_workflow_and_transport_errors_do_not_leak_metadata(self):
        source = Mock(spec=["get"])
        for head in ({"full_name": "contributor/clarify"}, None):
            source_run = {**run(), "head_repository": head}
            # A fork source is data; the canonical run remains the authority.
            source.get.side_effect = [
                source_run,
                {"total_count": 0, "jobs": []},
                source_run,
            ]
            result = diagnostics.inspect_run(88, source, NOW)
            self.assertEqual(
                result["source_repository"], head["full_name"] if head else None
            )
        source.get.side_effect = [
            {**run(), "path": ".github/workflows/ios-validation.yml"}
        ]
        with self.assertRaisesRegex(ValueError, "canonical"):
            diagnostics.inspect_run(88, source, NOW)
        source.get.side_effect = OSError("credential-and-log-body")
        with self.assertRaisesRegex(ValueError, "^Cannot read CI run metadata$"):
            diagnostics.inspect_run(88, source, NOW)

    def test_cli_inspection_never_runs_local_checks(self):
        output = io.StringIO()
        with (
            patch.object(
                diagnostics, "inspect_run", return_value={"run_id": 88}
            ) as inspect,
            patch.object(cli, "run_plan") as execute,
            patch("sys.stdout", output),
        ):
            self.assertEqual(cli.main(["--inspect-run", "88"]), 0)
        inspect.assert_called_once_with(88)
        execute.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {"run_id": 88})
