"""Result schema construction and the small compatibility contract used by CI."""

from datetime import datetime, timezone


def run_metadata(tag: str, profile: str, quick: bool) -> dict:
    return {
        "tag": tag,
        "profile": profile,
        "quick": quick,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_ci_metrics(payload: dict) -> None:
    """Raise when the two stable github-action-benchmark inputs are absent."""
    payload["throughput"]["1024"]["warp_cache"]
    payload["threading"]["8"]["warp_cache"]
