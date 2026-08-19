import os
import tempfile
import time
import uuid

from benchmarks.support.timing import median as _median
from benchmarks.support.timing import zipf_keys


def bench_shared_throughput(
    n_ops: int = 100_000, max_size: int = 256, rounds: int = 3
) -> dict[str, dict[str, float]]:
    from warp_cache import cache

    num_keys = 2000
    keys = zipf_keys(n_ops, num_keys)
    results: dict[str, dict[str, float]] = {}

    for backend in ("memory", "shared"):
        samples = []
        for _ in range(rounds):

            @cache(max_size=max_size, backend=backend)
            def fn(x: int) -> int:
                return x

            t0 = time.perf_counter()
            for k in keys:
                fn(k)
            elapsed = time.perf_counter() - t0
            samples.append(n_ops / elapsed)

        # Hit rate from last round (deterministic with same keys)
        info = fn.cache_info()
        total = info.hits + info.misses
        hit_rate = info.hits / total if total else 0.0

        results[backend] = {"ops_per_sec": _median(samples), "hit_rate": hit_rate}

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 7 — Shared backend: multi-process scaling
# ═══════════════════════════════════════════════════════════════════════════


def _mp_worker(args):
    """Worker for multiprocess benchmark. Runs in a forked child."""
    shm_name, n_ops, num_keys, seed = args
    from warp_cache._warp_cache_rs import SharedCachedFunction

    fn = SharedCachedFunction(
        lambda x: x,
        512,
        None,
        512,
        4096,
        shm_name,
    )
    keys = zipf_keys(n_ops, num_keys, seed=seed)
    t0 = time.perf_counter()
    for k in keys:
        fn(k)
    elapsed = time.perf_counter() - t0
    return n_ops / elapsed


def bench_multiprocess(
    process_counts: list[int], n_ops: int = 500_000, max_size: int = 512
) -> dict[str, dict[str, float]]:
    import multiprocessing

    num_keys = 2000
    results: dict[str, dict[str, float]] = {}

    for n_procs in process_counts:
        shm_name = f"bench_multiproc_{n_procs}_{uuid.uuid4().hex}"
        tmpdir = tempfile.gettempdir()
        shm_dir = os.path.join(tmpdir, "warp_cache")
        for suffix in (".data", ".lock"):
            p = os.path.join(shm_dir, f"{shm_name}{suffix}")
            if os.path.exists(p):
                os.unlink(p)

        from warp_cache._warp_cache_rs import SharedCachedFunction

        _init_fn = SharedCachedFunction(
            lambda x: x,
            max_size,
            None,
            512,
            4096,
            shm_name,
        )
        del _init_fn

        ops_per_proc = n_ops // n_procs
        worker_args = [(shm_name, ops_per_proc, num_keys, 42 + i) for i in range(n_procs)]

        ctx = multiprocessing.get_context("fork")
        t0 = time.perf_counter()
        with ctx.Pool(n_procs) as pool:
            per_proc_rates = pool.map(_mp_worker, worker_args)
        wall_elapsed = time.perf_counter() - t0

        total_ops = ops_per_proc * n_procs
        results[str(n_procs)] = {
            "total_ops_per_sec": total_ops / wall_elapsed,
            "per_process_avg_ops_per_sec": sum(per_proc_rates) / len(per_proc_rates),
            "wall_time": wall_elapsed,
        }

        for suffix in (".data", ".lock"):
            p = os.path.join(shm_dir, f"{shm_name}{suffix}")
            if os.path.exists(p):
                os.unlink(p)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
