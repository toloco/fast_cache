"""Small dependency-free timing helpers shared by benchmark workloads."""

import random
import time


def zipf_keys(n: int, num_keys: int, *, seed: int = 42) -> list[int]:
    rng = random.Random(seed)
    weights = [1.0 / (i + 1) for i in range(num_keys)]
    return rng.choices(range(num_keys), weights=weights, k=n)


def time_loop(fn, keys: list[int]) -> float:
    started = time.perf_counter()
    for key in keys:
        fn(key)
    return time.perf_counter() - started


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
