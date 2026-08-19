import functools
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

REQUIRED_COMPARISON_PACKAGES = ("cachetools", "cachebox", "moka_py", "zoocache")


def missing_contestants(contestants) -> list[str]:
    required = set(REQUIRED_COMPARISON_PACKAGES)
    return [c.name for c in contestants if c.name in required and not c.available]


@dataclass
class Contestant:
    name: str
    make_lru: Callable[[int], Callable] | None = None
    make_ttl: Callable[[int, float], Callable] | None = None
    make_async_lru: Callable[[int], Callable] | None = None
    thread_safe: bool = False
    available: bool = False
    version: str = ""
    notes: list[str] = field(default_factory=list)


def _identity(x: int) -> int:
    return x


async def _async_identity(x: int) -> int:
    return x


def _build_contestants(warp_only: bool = False) -> list[Contestant]:
    contestants: list[Contestant] = []

    # 1. warp_cache (always available — this is the project under test)
    from warp_cache import cache

    contestants.append(
        Contestant(
            name="warp_cache",
            make_lru=lambda sz: cache(max_size=sz)(_identity),
            make_ttl=lambda sz, ttl: cache(max_size=sz, ttl=ttl)(_identity),
            make_async_lru=lambda sz: cache(max_size=sz)(_async_identity),
            thread_safe=True,
            available=True,
            version="0.1.0",
        )
    )

    # warp_only: skip the comparison libs entirely. The trend dashboard only
    # charts warp_cache, and a competitor that hangs (e.g. cachebox infinite-
    # looping on 3.10/3.11) would otherwise stall the whole CI bench job.
    if warp_only:
        return contestants

    # 2. functools.lru_cache (stdlib, always available)
    contestants.append(
        Contestant(
            name="lru_cache",
            make_lru=lambda sz: functools.lru_cache(maxsize=sz)(_identity),
            make_ttl=None,
            thread_safe=False,
            available=True,
            version=sys.version.split()[0],
        )
    )

    # 3. cachetools
    try:
        import cachetools
        from cachetools.func import lru_cache as ct_lru_cache
        from cachetools.func import ttl_cache as ct_ttl_cache

        contestants.append(
            Contestant(
                name="cachetools",
                make_lru=lambda sz: ct_lru_cache(maxsize=sz)(_identity),
                make_ttl=lambda sz, ttl: ct_ttl_cache(maxsize=sz, ttl=ttl)(_identity),
                thread_safe=False,
                available=True,
                version=cachetools.__version__,
            )
        )
    except ImportError:
        contestants.append(Contestant(name="cachetools"))

    # 4. cachebox
    try:
        import cachebox

        def _cachebox_lru(sz):
            @cachebox.cached(cachebox.LRUCache(maxsize=sz))
            def fn(x: int) -> int:
                return x

            return fn

        contestants.append(
            Contestant(
                name="cachebox",
                make_lru=_cachebox_lru,
                make_ttl=None,
                thread_safe=True,
                available=True,
                version=cachebox.__version__,
                notes=["TTL only via TTLCache (FIFO, not LRU)"],
            )
        )
    except ImportError:
        contestants.append(Contestant(name="cachebox"))

    # 5. moka-py
    try:
        import moka_py

        def _moka_lru(sz):
            @moka_py.cached(maxsize=sz)
            def fn(x: int) -> int:
                return x

            return fn

        def _moka_ttl(sz, ttl):
            @moka_py.cached(maxsize=sz, ttl=ttl)
            def fn(x: int) -> int:
                return x

            return fn

        def _moka_async_lru(sz):
            @moka_py.cached(maxsize=sz)
            async def fn(x: int) -> int:
                return x

            return fn

        contestants.append(
            Contestant(
                name="moka_py",
                make_lru=_moka_lru,
                make_ttl=_moka_ttl,
                make_async_lru=_moka_async_lru,
                thread_safe=True,
                available=True,
                version=getattr(moka_py, "VERSION", ""),
            )
        )
    except ImportError:
        contestants.append(Contestant(name="moka_py"))

    # 6. zoocache
    try:
        import zoocache

        def _zoo_lru(_sz):
            """ZooCache has no maxsize — caches everything (unbounded)."""

            @zoocache.cacheable
            def fn(x: int) -> int:
                return x

            return fn

        contestants.append(
            Contestant(
                name="zoocache",
                make_lru=_zoo_lru,
                make_ttl=None,
                thread_safe=True,
                available=True,
                version=getattr(zoocache, "__version__", ""),
                notes=["No maxsize param (unbounded cache)", "Semantic invalidation, not LRU"],
            )
        )
    except ImportError:
        contestants.append(Contestant(name="zoocache"))

    return contestants
