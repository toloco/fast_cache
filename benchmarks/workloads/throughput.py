import asyncio
import functools
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from benchmarks.support.contestants import Contestant
from benchmarks.support.timing import median as _median
from benchmarks.support.timing import time_loop as _time_loop
from benchmarks.support.timing import zipf_keys


def verify_correctness(n_ops: int = 50_000) -> bool:
    from warp_cache import cache

    max_size = 256
    num_keys = 500

    @cache(max_size=max_size)
    def fc_fn(x: int) -> int:
        return x * 7 + 3

    @functools.lru_cache(maxsize=max_size)
    def lru_fn(x: int) -> int:
        return x * 7 + 3

    rng = random.Random(99)
    for _ in range(n_ops):
        k = rng.randint(0, num_keys - 1)
        fc_val = fc_fn(k)
        lru_val = lru_fn(k)
        if fc_val != lru_val:
            print(f"MISMATCH at key={k}: warp_cache={fc_val}, lru_cache={lru_val}")
            return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 2 — Single-thread throughput vs cache size
# ═══════════════════════════════════════════════════════════════════════════


def bench_throughput(
    contestants: list[Contestant],
    cache_sizes: list[int],
    n_ops: int = 100_000,
    rounds: int = 3,
) -> dict:
    num_keys = 2000
    keys = zipf_keys(n_ops, num_keys)
    results: dict[str, dict[str, float]] = {}

    # zoocache has no maxsize — run it once and report separately
    zoo_contestant = next((c for c in contestants if c.name == "zoocache" and c.available), None)
    regular = [c for c in contestants if c.available and c.name != "zoocache"]

    for sz in cache_sizes:
        sz_results: dict[str, float] = {}
        for c in regular:
            samples = []
            for _ in range(rounds):
                fn = c.make_lru(sz)
                elapsed = _time_loop(fn, keys)
                samples.append(n_ops / elapsed)
            sz_results[c.name] = _median(samples)
        results[str(sz)] = sz_results

    if zoo_contestant:
        samples = []
        for _ in range(rounds):
            fn = zoo_contestant.make_lru(0)
            elapsed = _time_loop(fn, keys)
            samples.append(n_ops / elapsed)
        results["zoocache_unbounded"] = {"zoocache": _median(samples)}

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 3 — Multi-thread scaling
# ═══════════════════════════════════════════════════════════════════════════


def bench_threading(
    contestants: list[Contestant],
    thread_counts: list[int],
    n_ops: int = 100_000,
    max_size: int = 256,
    rounds: int = 3,
) -> dict:
    num_keys = 2000
    results: dict[str, dict[str, float]] = {}

    active = [c for c in contestants if c.available and c.name != "zoocache"]

    for n_threads in thread_counts:
        ops_per_thread = n_ops // n_threads
        keys_per_thread = zipf_keys(ops_per_thread, num_keys)
        tc_results: dict[str, float] = {}

        for c in active:
            samples = []
            for _ in range(rounds):
                fn = c.make_lru(max_size)

                if c.thread_safe:

                    def worker(f=fn):
                        for k in keys_per_thread:
                            f(k)
                else:
                    lock = threading.Lock()

                    def worker(f=fn, lk=lock):
                        for k in keys_per_thread:
                            with lk:
                                f(k)

                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=n_threads) as pool:
                    futs = [pool.submit(worker) for _ in range(n_threads)]
                    for f in futs:
                        f.result()
                elapsed = time.perf_counter() - t0

                total_ops = ops_per_thread * n_threads
                samples.append(total_ops / elapsed)

            tc_results[c.name] = _median(samples)

        results[str(n_threads)] = tc_results

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 4 — Sustained throughput (~10s time-based)
# ═══════════════════════════════════════════════════════════════════════════


def bench_sustained(
    contestants: list[Contestant],
    duration: float = 10.0,
    max_size: int = 256,
) -> dict[str, dict[str, float]]:
    num_keys = 2000
    keys = zipf_keys(1_000_000, num_keys)
    n_keys = len(keys)
    results: dict[str, dict[str, float]] = {}

    active = [c for c in contestants if c.available and c.name != "zoocache"]

    for c in active:
        fn = c.make_lru(max_size)
        deadline = time.perf_counter() + duration
        ops = 0
        idx = 0
        t0 = time.perf_counter()
        while time.perf_counter() < deadline:
            fn(keys[idx])
            ops += 1
            idx += 1
            if idx >= n_keys:
                idx = 0
        elapsed = time.perf_counter() - t0
        results[c.name] = {"ops": ops, "elapsed": elapsed, "ops_per_sec": ops / elapsed}

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 5 — TTL throughput
# ═══════════════════════════════════════════════════════════════════════════


def bench_ttl(
    contestants: list[Contestant],
    ttl_values: list[float | None] | None = None,
    duration: float = 10.0,
    max_size: int = 256,
) -> dict[str, dict[str, dict[str, float]]]:
    if ttl_values is None:
        ttl_values = [0.001, 0.01, 0.1, 1.0, None]

    num_keys = 2000
    keys = zipf_keys(1_000_000, num_keys)
    n_keys = len(keys)
    results: dict[str, dict[str, dict[str, float]]] = {}

    ttl_contestants = [c for c in contestants if c.available and c.make_ttl is not None]

    for ttl in ttl_values:
        ttl_label = "None" if ttl is None else str(ttl)
        ttl_results: dict[str, dict[str, float]] = {}

        for c in ttl_contestants:
            fn = c.make_ttl(max_size, ttl if ttl is not None else 3600.0)

            deadline = time.perf_counter() + duration
            ops = 0
            idx = 0
            t0 = time.perf_counter()
            while time.perf_counter() < deadline:
                fn(keys[idx])
                ops += 1
                idx += 1
                if idx >= n_keys:
                    idx = 0
            elapsed = time.perf_counter() - t0

            ttl_results[c.name] = {"ops_per_sec": ops / elapsed}

        results[ttl_label] = ttl_results

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 6 — Async throughput
# ═══════════════════════════════════════════════════════════════════════════


def bench_async_throughput(
    contestants: list[Contestant],
    cache_sizes: list[int],
    n_ops: int = 100_000,
    rounds: int = 3,
) -> dict:
    """Benchmark async cached function throughput (cache hits via event loop)."""
    num_keys = 2000
    keys = zipf_keys(n_ops, num_keys)

    async_contestants = [c for c in contestants if c.available and c.make_async_lru is not None]
    results: dict[str, dict[str, float]] = {}

    for sz in cache_sizes:
        sz_results: dict[str, float] = {}
        for c in async_contestants:
            samples = []
            for _ in range(rounds):
                fn = c.make_async_lru(sz)

                async def _run(f=fn):
                    for k in keys:
                        await f(k)

                t0 = time.perf_counter()
                asyncio.run(_run())
                elapsed = time.perf_counter() - t0
                samples.append(n_ops / elapsed)
            sz_results[c.name] = _median(samples)

        results[str(sz)] = sz_results

    # Also measure sync for comparison (same contestants that have async)
    sync_results: dict[str, float] = {}
    for c in async_contestants:
        samples = []
        for _ in range(rounds):
            fn = c.make_lru(256)
            elapsed = _time_loop(fn, keys)
            samples.append(n_ops / elapsed)
        sync_results[c.name] = _median(samples)
    results["sync_256"] = sync_results

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 7 — Shared backend: single-process throughput
# ═══════════════════════════════════════════════════════════════════════════
