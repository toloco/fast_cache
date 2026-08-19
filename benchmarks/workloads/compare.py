import argparse
import json
import platform
import sys
import sysconfig
from pathlib import Path

from benchmarks.support.contestants import _build_contestants, missing_contestants
from benchmarks.support.schema import run_metadata, validate_ci_metrics
from benchmarks.workloads.shared import bench_multiprocess, bench_shared_throughput
from benchmarks.workloads.throughput import (
    bench_async_throughput,
    bench_sustained,
    bench_threading,
    bench_throughput,
    bench_ttl,
    verify_correctness,
)

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def python_info() -> dict:
    gil_disabled = getattr(sys.flags, "nogil", False) or sysconfig.get_config_var("Py_GIL_DISABLED")
    return {
        "version": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "build": platform.python_build()[0],
        "compiler": platform.python_compiler(),
        "arch": platform.machine(),
        "gil_disabled": bool(gil_disabled),
    }


def fmt(ops: float) -> str:
    if ops >= 1_000_000:
        return f"{ops / 1_000_000:>7.2f}M"
    if ops >= 1_000:
        return f"{ops / 1_000:>7.0f}K"
    return f"{ops:>7.0f} "


def main() -> None:
    parser = argparse.ArgumentParser(description="warp_cache benchmark runner")
    parser.add_argument("--tag", required=True, help="Label for this run (e.g. py3.12)")
    parser.add_argument("--quick", action="store_true", help="Skip sustained & TTL benchmarks")
    parser.add_argument("--rounds", type=int, default=3, help="Rounds per burst benchmark (median)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--profile", choices=("full", "smoke"), default="full")
    parser.add_argument("--require-comparison", action="store_true")
    parser.add_argument(
        "--warp-only",
        action="store_true",
        help="Benchmark only warp_cache (skip comparison libs). Used by the CI trend job.",
    )
    args = parser.parse_args()

    info = python_info()
    contestants = _build_contestants(warp_only=args.warp_only)
    missing = missing_contestants(contestants)
    if args.require_comparison and missing:
        parser.error(f"comparison dependencies unavailable: {', '.join(missing)}")
    available = [c for c in contestants if c.available]
    unavailable = [c for c in contestants if not c.available]

    total_steps = 6 if args.quick else 8

    tag_suffix = " (free-threaded)" if info["gil_disabled"] else ""
    print(f"Python {info['version']}{tag_suffix}  [{info['implementation']}]")
    print(f"{info['compiler']}")
    print(f"{info['arch']}")
    print(f"Rounds: {args.rounds} (median of {args.rounds} runs)")
    if args.quick:
        print("(--quick mode: skipping sustained & TTL benchmarks)")

    print(f"\nContestants ({len(available)} available):")
    for c in available:
        notes = f"  ({', '.join(c.notes)})" if c.notes else ""
        print(f"  {c.name} v{c.version}{notes}")
    if unavailable:
        print(f"  Skipped (not installed): {', '.join(c.name for c in unavailable)}")

    # 1. Correctness
    print(f"\n[1/{total_steps}] Correctness verification ...")
    ok = verify_correctness()
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    if not ok:
        sys.exit(1)

    # 2. Single-thread throughput
    cache_sizes = [1024] if args.profile == "smoke" else [32, 64, 128, 256, 512, 1024]
    print(f"\n[2/{total_steps}] Single-thread throughput vs cache size ...")
    tp_results = bench_throughput(contestants, cache_sizes, rounds=args.rounds)
    for sz in cache_sizes:
        parts = []
        for name, ops in tp_results[str(sz)].items():
            parts.append(f"{name}={fmt(ops)}")
        print(f"  size={sz:>5}  {' '.join(parts)}")
    if "zoocache_unbounded" in tp_results:
        ops = tp_results["zoocache_unbounded"]["zoocache"]
        print(f"  zoocache (unbounded): {fmt(ops)}")

    # 3. Multi-thread scaling
    thread_counts = [8] if args.profile == "smoke" else [1, 2, 4, 8, 16, 32]
    print(f"\n[3/{total_steps}] Multi-thread scaling ...")
    th_results = bench_threading(contestants, thread_counts, rounds=args.rounds)
    for nt in thread_counts:
        parts = []
        for name, ops in th_results[str(nt)].items():
            parts.append(f"{name}={fmt(ops)}")
        print(f"  threads={nt:>2}  {' '.join(parts)}")

    # 4. Sustained throughput
    sustained_results = None
    if not args.quick:
        print(f"\n[4/{total_steps}] Sustained throughput (~10s per impl) ...")
        sustained_results = bench_sustained(contestants)
        for label, data in sustained_results.items():
            print(f"  {label}: {data['ops_per_sec']:,.0f} ops/s ({data['elapsed']:.2f}s)")

    # 5. TTL throughput
    ttl_results = None
    if not args.quick:
        print(f"\n[5/{total_steps}] TTL throughput (~10s per TTL per impl) ...")
        ttl_results = bench_ttl(contestants)
        for ttl_label, ttl_data in ttl_results.items():
            parts = []
            for name, d in ttl_data.items():
                parts.append(f"{name}={fmt(d['ops_per_sec'])}")
            print(f"  TTL={ttl_label}: {' '.join(parts)}")

    # 6. Async throughput
    step = 4 if args.quick else 6
    async_cache_sizes = [256]
    print(f"\n[{step}/{total_steps}] Async throughput ...")
    async_results = bench_async_throughput(contestants, async_cache_sizes, rounds=args.rounds)
    for sz_label, sz_data in async_results.items():
        parts = []
        for name, ops in sz_data.items():
            parts.append(f"{name}={fmt(ops)}")
        print(f"  {sz_label}: {' '.join(parts)}")

    # 7. Shared backend single-process
    step = 5 if args.quick else 7
    print(f"\n[{step}/{total_steps}] Shared backend: memory vs shared ...")
    shared_tp_results = bench_shared_throughput(rounds=args.rounds)
    for backend, data in shared_tp_results.items():
        print(f"  {backend}: {data['ops_per_sec']:,.0f} ops/s  hit_rate={data['hit_rate']:.1%}")

    # 8. Multi-process scaling
    step = 6 if args.quick else 8
    process_counts = [1] if args.profile == "smoke" else [1, 2, 4, 8]
    print(f"\n[{step}/{total_steps}] Shared backend: multi-process scaling ...")
    mp_results = bench_multiprocess(process_counts)
    for np_str, d in mp_results.items():
        print(
            f"  procs={np_str}: total={d['total_ops_per_sec']:,.0f} ops/s"
            f"  wall={d['wall_time']:.2f}s"
        )

    # Save JSON
    contestant_info = {
        c.name: {"version": c.version, "available": c.available, "thread_safe": c.thread_safe}
        for c in contestants
    }
    payload: dict = {
        "schema_version": 1,
        "run": run_metadata(args.tag, args.profile, args.quick),
        "python": info,
        "contestants": contestant_info,
        "throughput": tp_results,
        "threading": th_results,
        "async_throughput": async_results,
        "shared_throughput": shared_tp_results,
        "multiprocess": mp_results,
    }
    if sustained_results is not None:
        payload["sustained"] = sustained_results
    if ttl_results is not None:
        payload["ttl"] = ttl_results

    validate_ci_metrics(payload)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"bench_{args.tag}.json"
    json_path.write_text(json.dumps(payload, indent=2))
    print(f"\nResults saved to {json_path}")


if __name__ == "__main__":
    main()
