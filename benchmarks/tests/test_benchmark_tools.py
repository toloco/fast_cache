import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks._to_action_json import convert
from benchmarks.support.schema import run_metadata, validate_ci_metrics

ROOT = Path(__file__).resolve().parents[2]


class BenchmarkToolsTest(unittest.TestCase):
    def test_schema_keeps_ci_metric_paths(self):
        payload = {
            "schema_version": 1,
            "run": run_metadata("ci", "smoke", True),
            "throughput": {"1024": {"warp_cache": 10.0}},
            "threading": {"8": {"warp_cache": 20.0}},
        }
        validate_ci_metrics(payload)
        self.assertEqual(payload["run"]["tag"], "ci")

    def test_action_metric_names_are_stable(self):
        payload = {
            "throughput": {"1024": {"warp_cache": 10.4}},
            "threading": {"8": {"warp_cache": 20.6}},
        }
        self.assertEqual(
            convert(payload, "linux"),
            [
                {
                    "name": "warp_cache single-thread throughput (size=1024) [linux]",
                    "unit": "ops/s",
                    "value": 10,
                },
                {
                    "name": "warp_cache throughput (8 threads) [linux]",
                    "unit": "ops/s",
                    "value": 21,
                },
            ],
        )

    def test_action_conversion_rejects_missing_metric(self):
        with self.assertRaises(ValueError):
            convert({"throughput": {"1024": {"warp_cache": 1.0}}}, "ci")

    def test_dispatch_rejects_unknown_command(self):
        result = subprocess.run(
            [str(ROOT / "benchmarks/run.sh"), "not-a-command"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown benchmark command", result.stderr)

    def test_action_json_dispatch_is_cwd_independent(self):
        payload = {
            "throughput": {"1024": {"warp_cache": 1.0}},
            "threading": {"8": {"warp_cache": 2.0}},
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            output = Path(directory) / "output.json"
            source.write_text(json.dumps(payload))
            result = subprocess.run(
                [str(ROOT / "benchmarks/run.sh"), "action-json", str(source), str(output)],
                cwd="/tmp",
                env={**os.environ, "BENCH_PYTHON_BIN": sys.executable},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(output.read_text())), 2)


if __name__ == "__main__":
    unittest.main()
