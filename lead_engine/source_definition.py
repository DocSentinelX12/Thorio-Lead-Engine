from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


SUPPORTED_COLLECTOR_TYPES = frozenset(
    {
        "json",
        "rss",
        "atom",
        "xml",
        "html",
    }
)

SUPPORTED_PAGINATION_TYPES = frozenset(
    {
        "none",
        "page",
        "offset",
        "cursor",
        "next_url",
    }
)


@dataclass(frozen=True)
class SourceDefinition:
    """
    Immutable contract describing how a lead source is collected.

    This object contains source configuration only. It does not
    perform network requests, pagination, normalization, scoring,
    qualification, routing, or Airtable synchronization.
    """

    name: str
    provider: str
    collector_type: str
    url: str

    enabled: bool = True

    record_path: Optional[str] = None

    title_field: str = "title"
    company_field: str = "company"
    description_field: str = "description"
    url_field: str = "url"
    source_id_field: Optional[str] = None
    location_field: Optional[str] = None

    pagination_type: str = "none"

    cursor_parameter: Optional[str] = None
    cursor_response_field: Optional[str] = None

    page_parameter: Optional[str] = None
    page_start: int = 1
    page_limit: Optional[int] = None

    offset_parameter: Optional[str] = None
    offset_start: int = 0
    offset_step: Optional[int] = None

    next_url_field: Optional[str] = None

    max_pages: int = 10
    max_requests: int = 10
    max_records: int = 5000

    poll_interval_seconds: int = 3600

    attribution_required: bool = False
    attribution_url: Optional[str] = None

    allowed_for_thorio: bool = True
    restrictions: Tuple[str, ...] = field(
        default_factory=tuple
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        name = self.name.strip()
        provider = self.provider.strip()
        collector_type = (
            self.collector_type.strip().lower()
        )
        url = self.url.strip()
        pagination_type = (
            self.pagination_type.strip().lower()
        )

        if not name:
            raise ValueError(
                "Source name is required."
            )

        if not provider:
            raise ValueError(
                "Source provider is required."
            )

        if not url:
            raise ValueError(
                "Source URL is required."
            )

        if not (
            url.startswith("http://")
            or url.startswith("https://")
        ):
            raise ValueError(
                "Source URL must use HTTP or HTTPS."
            )

        if collector_type not in SUPPORTED_COLLECTOR_TYPES:
            raise ValueError(
                "Unsupported collector type: "
                f"{self.collector_type}"
            )

        if pagination_type not in SUPPORTED_PAGINATION_TYPES:
            raise ValueError(
                "Unsupported pagination type: "
                f"{self.pagination_type}"
            )

        if self.page_start < 0:
            raise ValueError(
                "Page start cannot be negative."
            )

        if self.offset_start < 0:
            raise ValueError(
                "Offset start cannot be negative."
            )

        if (
            self.page_limit is not None
            and self.page_limit <= 0
        ):
            raise ValueError(
                "Page limit must be positive."
            )

        if (
            self.offset_step is not None
            and self.offset_step <= 0
        ):
            raise ValueError(
                "Offset step must be positive."
            )

        if self.max_pages <= 0:
            raise ValueError(
                "Maximum pages must be positive."
            )

        if self.max_requests <= 0:
            raise ValueError(
                "Maximum requests must be positive."
            )

        if self.max_records <= 0:
            raise ValueError(
                "Maximum records must be positive."
            )

        if self.poll_interval_seconds <= 0:
            raise ValueError(
                "Poll interval must be positive."
            )

        if (
            self.attribution_required
            and not self.attribution_url
        ):
            raise ValueError(
                "Attribution URL is required when "
                "attribution is required."
            )

        if (
            self.pagination_type == "cursor"
            and not self.cursor_parameter
        ):
            raise ValueError(
                "Cursor pagination requires "
                "cursor_parameter."
            )

        if (
            self.pagination_type == "page"
            and not self.page_parameter
        ):
            raise ValueError(
                "Page pagination requires "
                "page_parameter."
            )

        if (
            self.pagination_type == "offset"
            and not self.offset_parameter
        ):
            raise ValueError(
                "Offset pagination requires "
                "offset_parameter."
            )

        if (
            self.pagination_type == "next_url"
            and not self.next_url_field
        ):
            raise ValueError(
                "Next URL pagination requires "
                "next_url_field."
            )

        if not isinstance(
            self.restrictions,
            (tuple, list),
        ):
            raise ValueError(
                "Restrictions must be a sequence."
            )

        if not isinstance(
            self.metadata,
            dict,
        ):
            raise ValueError(
                "Metadata must be a dictionary."
            )

        object.__setattr__(
            self,
            "name",
            name,
        )

        object.__setattr__(
            self,
            "provider",
            provider,
        )

        object.__setattr__(
            self,
            "collector_type",
            collector_type,
        )

        object.__setattr__(
            self,
            "url",
            url,
        )

        object.__setattr__(
            self,
            "pagination_type",
            pagination_type,
        )

        object.__setattr__(
            self,
            "restrictions",
            tuple(
                str(value).strip()
                for value in self.restrictions
                if str(value).strip()
            ),
        )

        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata),
        )

    @property
    def source_key(self) -> str:
        """
        Stable identifier for the collector.
        """
        return f"{self.provider}:{self.name}"

    @property
    def uses_pagination(self) -> bool:
        return self.pagination_type != "none"

    @property
    def has_restrictions(self) -> bool:
        return bool(self.restrictions)

    def allows_thorio(self) -> bool:
        return (
            self.enabled
            and self.allowed_for_thorio
        )
