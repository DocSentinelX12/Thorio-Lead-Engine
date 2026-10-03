        if not provider_id:
            raise ValueError("provider_id is required")
        domain_id = ""
        domain_method = getattr(provider, "_domain_id", None)
        if callable(domain_method):
            try:
                domain_id = str(domain_method()).strip()
            except Exception:
                domain_id = ""
        config = getattr(provider, "config", None)
        if not domain_id and config is not None:
            username = str(getattr(config, "username", "")).strip()
            kernel_slug = str(getattr(config, "kernel_slug", "")).strip()
            if username and kernel_slug:
                domain_id = f"{provider_id}:{username}:{kernel_slug}"
        if not domain_id:
            return provider_id
        return f"{provider_id}:{domain_id}"

    def register(self, provider: FreeComputeProvider) -> None:
        key = self._provider_key(provider)
        if key in self._providers:
            raise ValueError(f"free compute provider already registered: {key}")
        self._providers[key] = provider

    def providers(self) -> tuple[FreeComputeProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))
