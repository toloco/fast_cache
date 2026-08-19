"""Convert a bench_<tag>.json payload into github-action-benchmark's
``customBiggerIsBetter`` format (a flat list of {name, unit, value}).

Reuses the comparison workload output; we only pull a
few headline warp_cache metrics, each tagged with the env so every matrix cell
becomes its own trend series.

Usage:
    benchmarks/run.sh action-json <bench_results.json> <out.json> --tag ubuntu-py3.13
"""

import argparse
import json
import math
import sys
from pathlib import Path

# (payload section, key, label) — headline warp_cache series to track.
# ponytail: two metrics is enough to spot trends; add more when a chart is missed.
METRICS = [
    ("throughput", "1024", "single-thread throughput (size=1024)"),
    ("threading", "8", "throughput (8 threads)"),
]


def convert(payload: dict, tag: str) -> list[dict]:
    out = []
    for section, key, label in METRICS:
        value = payload.get(section, {}).get(key, {}).get("warp_cache")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"missing or invalid required metric: {section}.{key}.warp_cache")
        out.append({"name": f"warp_cache {label} [{tag}]", "unit": "ops/s", "value": round(value)})
    return out


def _selftest() -> None:
    sample = {
        "throughput": {"1024": {"warp_cache": 1000.4}},
        "threading": {"8": {"warp_cache": 500.0}},
    }
    out = convert(sample, "x-pyY")
    assert [m["value"] for m in out] == [1000, 500], out
    assert all(m["unit"] == "ops/s" and "x-pyY" in m["name"] for m in out), out
    try:
        convert({}, "t")
    except ValueError:
        pass
    else:
        raise AssertionError("missing required metrics must fail")
    print("selftest ok")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("infile", nargs="?", help="bench_<tag>.json from the runner")
    p.add_argument("outfile", nargs="?", help="output JSON path")
    p.add_argument("--tag", default="", help="env label, e.g. ubuntu-latest-py3.13")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        _selftest()
        return
    if not (args.infile and args.outfile):
        p.error("infile and outfile are required (or pass --selftest)")

    payload = json.loads(Path(args.infile).read_text())
    metrics = convert(payload, args.tag)
    if not metrics:
        print(f"no warp_cache metrics found in {args.infile}", file=sys.stderr)
        sys.exit(1)
    Path(args.outfile).write_text(json.dumps(metrics, indent=2))
    print(f"wrote {len(metrics)} metric(s) to {args.outfile}")


if __name__ == "__main__":
    main()
