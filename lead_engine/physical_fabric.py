        path_id = str(raw.get("path_id") or "").strip()
        if not path_id:
            continue
        if (
            str(raw.get("source_gpu") or "").strip() != source_gpu
            or str(raw.get("destination_gpu") or "").strip() != destination_gpu
        ):
            continue
        segments = raw.get("segments")
        if not isinstance(segments, (list, tuple)):
            continue
        normalized = {str(segment).strip() for segment in segments if str(segment).strip()}
        if source_port in normalized and destination_port in normalized:
            matches.append(path_id)
    return matches[0] if len(matches) == 1 else None

class AdaptiveFabricRouteSelector:
    """Select and reselect physical routes from current, path-specific evidence."""

    _ELIGIBLE_STATES = frozenset({
        FabricPathState.VERIFIED.value,
        FabricPathState.MEASURED.value,
        FabricPathState.REVERIFIED.value,
    })

    @classmethod
    def _candidates(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for raw in paths:
            path_id = str(raw.get("path_id") or "").strip()
            state = str(raw.get("state") or "").strip()
            if not path_id or state not in cls._ELIGIBLE_STATES:
                continue
            health = route_health.get(path_id)
            if not isinstance(health, Mapping):
                continue
            if state != FabricPathState.MEASURED.value:
                continue
            measurement = raw.get("measurement")
            if not isinstance(measurement, Mapping):
                continue
            candidates.append({
                "path_id": path_id,
                "health": dict(health),
                "measurement": dict(measurement),
                "state": state,
            })
        return candidates

    @classmethod
    def _key(cls, candidate: Mapping[str, object]) -> tuple[float, float, float, float, str]:
        health = candidate["health"]
        assert isinstance(health, Mapping)
        return (
            float(health.get("failure_rate", float("inf"))),
            float(health.get("latency_delta_from_mean_ms", float("inf"))),
            float(health.get("latest_latency_ms", float("inf"))),
            -float(health.get("sample_count", 0) or 0),
            str(candidate["path_id"]),
        )

    @classmethod
    def select(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        candidates = sorted(cls._candidates(paths, route_health), key=cls._key)
        if not candidates:
            return {
                "path_id": None,
                "selection_reason": "no_current_measured_route",
                "alternatives": (),
                "evidence": (),
            }
        selected = candidates[0]
        return {
            "path_id": selected["path_id"],
            "selection_reason": "observed_route_health",
            "alternatives": tuple(str(item["path_id"]) for item in candidates[1:]),
            "evidence": tuple(
                {
                    "path_id": str(item["path_id"]),
                    "health": dict(item["health"]),
                    "measurement": dict(item["measurement"]),
                }
                for item in candidates
            ),
        }

    @classmethod
    def select_resilient_route_set(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
        gpu_pair: tuple[str, str],
        *,
        current_path_id: str | None = None,
    ) -> dict[str, object]:
        """Select one active route and all independently evidenced measured standbys."""
        source_gpu, destination_gpu = gpu_pair
        pair_paths = tuple(
            path
            for path in paths
            if str(path.get("source_gpu") or "") == str(source_gpu)
            and str(path.get("destination_gpu") or "") == str(destination_gpu)
        )
        selection = cls.select(pair_paths, route_health)
        active_path_id = str(selection["path_id"]) if selection["path_id"] is not None else None
        if active_path_id is None:
            return {
                "source_gpu": str(source_gpu),
                "destination_gpu": str(destination_gpu),
                "active_path_id": None,
                "standby_path_ids": (),
                "verified_path_ids": (),
                "selection_reason": str(selection["selection_reason"]),
                "evidence": (),
            }

        active_path = next(
            (
                path for path in pair_paths
                if str(path.get("path_id") or "") == active_path_id
            ),
            None,
        )
        if not isinstance(active_path, Mapping):
            return {
                "source_gpu": str(source_gpu),
                "destination_gpu": str(destination_gpu),
                "active_path_id": active_path_id,
                "standby_path_ids": (),
                "verified_path_ids": (active_path_id,),
                "selection_reason": str(selection["selection_reason"]),
                "evidence": tuple(selection["evidence"]),
            }

        candidates = cls._candidates(pair_paths, route_health)
        standby_ids = tuple(
            str(candidate["path_id"])
            for candidate in candidates
            if str(candidate["path_id"]) != active_path_id
            and cls.failure_domain_independent(
                active_path,
                next(
                    path for path in pair_paths
                    if str(path.get("path_id") or "") == str(candidate["path_id"])
                ),
            )
        )
        return {
            "source_gpu": str(source_gpu),
            "destination_gpu": str(destination_gpu),
            "active_path_id": active_path_id,
            "standby_path_ids": standby_ids,
            "verified_path_ids": (active_path_id, *standby_ids),
            "selection_reason": str(selection["selection_reason"]),
            "current_path_id": str(current_path_id) if current_path_id is not None else None,
            "evidence": tuple(selection["evidence"]),
        }

    @classmethod
    def select_for_gpu_pairs(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
        gpu_pairs: Sequence[tuple[str, str]],
    ) -> tuple[dict[str, str], ...]:
        """Select the observed best measured route independently for each GPU pair."""
        selected: list[dict[str, str]] = []
        for source_gpu, destination_gpu in gpu_pairs:
            pair_paths = tuple(
                path for path in paths
                if str(path.get("source_gpu") or "") == str(source_gpu)
                and str(path.get("destination_gpu") or "") == str(destination_gpu)
            )
            decision = cls.select(pair_paths, route_health)
            path_id = decision.get("path_id")
            if path_id is None:
                continue
            selected.append({
                "source_gpu": str(source_gpu),
                "destination_gpu": str(destination_gpu),
                "path_id": str(path_id),
            })
        return tuple(selected)

    @staticmethod
    def _failure_domain_components(path: Mapping[str, object]) -> frozenset[str]:
        segments = path.get("segments")
        domains = path.get("fabric_domains")
        if not isinstance(segments, (list, tuple)) or not isinstance(domains, (list, tuple)):
            return frozenset()
        normalized_segments = frozenset(str(segment).strip() for segment in segments if str(segment).strip())
        normalized_domains = frozenset(str(domain).strip() for domain in domains if str(domain).strip())
        if not normalized_domains:
            return frozenset()
        # Canonical path identities encode component classes in their identity
        # prefix. Endpoint GPUs, PCI and NUMA topology are not independent-path
        # failure domains, while NICs and RDMA devices are physical dependencies.
        components = {
            segment
            for segment in normalized_segments
            if segment.startswith("nic:") or (segment.startswith("rdma:") and segment.count(":") == 1)
        }
        components.update(normalized_domains)
        return frozenset(components)

    @classmethod
    def failure_domain_independent(
        cls,
        first: Mapping[str, object],
        second: Mapping[str, object],
    ) -> bool:
        """Return true only when canonical evidence proves physical independence."""
        first_domains = first.get("fabric_domains")
        second_domains = second.get("fabric_domains")
        if not isinstance(first_domains, (list, tuple)) or not isinstance(second_domains, (list, tuple)):
            return False
        first_domain_set = frozenset(str(item).strip() for item in first_domains if str(item).strip())
        second_domain_set = frozenset(str(item).strip() for item in second_domains if str(item).strip())
        first_components = cls._failure_domain_components(first)
        second_components = cls._failure_domain_components(second)
        if not first_domain_set or not second_domain_set or not first_components or not second_components:
            return False
        return not first_domain_set.intersection(second_domain_set) and not first_components.intersection(second_components)

    @classmethod
    def adaptive_replacement_plan(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
        current_routes: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        """Build independent replacement decisions for each active GPU-to-GPU route."""
        plan: list[dict[str, object]] = []
        for route in current_routes:
            if not isinstance(route, Mapping):
                continue
            source_gpu = str(route.get("source_gpu") or "").strip()
            destination_gpu = str(route.get("destination_gpu") or "").strip()
            current_path_id = str(route.get("current_path_id") or "").strip()
            if not source_gpu or not destination_gpu or not current_path_id:
                continue
            pair_paths = tuple(
                path for path in paths
                if str(path.get("source_gpu") or "") == source_gpu
                and str(path.get("destination_gpu") or "") == destination_gpu
            )
            current_path = next(
                (path for path in pair_paths if str(path.get("path_id") or "") == current_path_id),
                None,
            )
            if isinstance(current_path, Mapping) and current_path.get("fabric_domains") and current_path.get("segments"):
                independent_paths = tuple(
                    path
                    for path in pair_paths
                    if str(path.get("path_id") or "") == current_path_id
                    or cls.failure_domain_independent(current_path, path)
                )
                pair_paths = independent_paths
            decision = cls.migration(pair_paths, route_health, current_path_id=current_path_id)
            plan.append({
                "source_gpu": source_gpu,
                "destination_gpu": destination_gpu,
                "from_path_id": str(decision["from_path_id"]),
                "to_path_id": (
                    str(decision["to_path_id"])
                    if decision["to_path_id"] is not None
                    else None
                ),
                "migrate": bool(decision["migrate"]),
                "reason": str(decision["reason"]),
            })
        return tuple(plan)

    @classmethod
    def migration(
        cls,
        paths: Sequence[Mapping[str, object]],
        route_health: Mapping[str, Mapping[str, object]],
        *,
        current_path_id: str,
    ) -> dict[str, object]:
        selection = cls.select(paths, route_health)
        selected = selection["path_id"]
        if selected is None:
            return {
                "migrate": False,
                "from_path_id": current_path_id,
                "to_path_id": None,
                "reason": "no_verified_alternative",
            }
        if str(selected) == str(current_path_id):
            return {
                "migrate": False,
                "from_path_id": current_path_id,
                "to_path_id": current_path_id,
                "reason": "current_route_remains_selected",
            }
        return {
            "migrate": True,
            "from_path_id": current_path_id,
            "to_path_id": str(selected),
            "reason": str(selection["selection_reason"]),
        }