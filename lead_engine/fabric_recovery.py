from __future__ import annotations

from collections.abc import Mapping, Sequence

from .physical_fabric import AdaptiveFabricRouteSelector


def failover_after_exact_path_failure(
    paths: Sequence[Mapping[str, object]],
    route_health: Mapping[str, Mapping[str, object]],
    *,
    failed_path_id: str,
    gpu_pair: tuple[str, str],
) -> dict[str, object]:
    """Choose a measured standby only after an exact physical path failure."""
    source_gpu, destination_gpu = gpu_pair
    pair_paths = tuple(
        path
        for path in paths
        if str(path.get("source_gpu") or "") == str(source_gpu)
        and str(path.get("destination_gpu") or "") == str(destination_gpu)
    )
    failed_path = next(
        (path for path in pair_paths if str(path.get("path_id") or "") == str(failed_path_id)),
        None,
    )
    if not isinstance(failed_path, Mapping):
        return {"migrate": False, "from_path_id": str(failed_path_id), "to_path_id": None, "reason": "failed_path_not_found"}

    candidates = AdaptiveFabricRouteSelector._candidates(pair_paths, route_health)
    path_by_id = {str(path.get("path_id") or ""): path for path in pair_paths if str(path.get("path_id") or "")}
    independent = [
        candidate
        for candidate in candidates
        if str(candidate["path_id"]) != str(failed_path_id)
        and AdaptiveFabricRouteSelector.failure_domain_independent(failed_path, path_by_id[str(candidate["path_id"])])
    ]
    if not independent:
        return {"migrate": False, "from_path_id": str(failed_path_id), "to_path_id": None, "reason": "no_independently_verified_standby"}

    selected = min(independent, key=AdaptiveFabricRouteSelector._key)
    return {"migrate": True, "from_path_id": str(failed_path_id), "to_path_id": str(selected["path_id"]), "reason": "exact_path_failure_independent_standby"}


# Compatibility seam: preserve the established selector API while exposing the
# new recovery decision from the same authoritative selector type.
AdaptiveFabricRouteSelector.failover_after_exact_path_failure = staticmethod(failover_after_exact_path_failure)
