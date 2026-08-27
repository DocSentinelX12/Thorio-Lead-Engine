from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable


class LeadSource(ABC):
    """
    Standard interface for a lead-discovery source.

    Source adapters discover signals.
    They do not qualify leads.
    """

    name = "unknown"

    @abstractmethod
    def collect(self) -> Iterable[Dict[str, Any]]:
        """
        Return discovered leads in the standard input format.
        """
        raise NotImplementedError


class StaticLeadSource(LeadSource):
    """
    Simple source adapter for already-discovered leads.

    Useful for testing and for importing leads from external
    collection tools later.
    """

    name = "static"

    def __init__(self, leads):
        self.leads = list(leads)

    def collect(self) -> Iterable[Dict[str, Any]]:
        return self.leads


def collect_from_source(
    source: LeadSource,
) -> Iterable[Dict[str, Any]]:
    """
    Collect leads from a source adapter.
    """

    return source.collect()


if __name__ == "__main__":
    print(
        "Lead source interface loaded. "
        "Source adapters can now feed standardized leads "
        "into the collector."
    )
