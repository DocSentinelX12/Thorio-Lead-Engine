__version__ = "0.1.0"

# Install the conservative HTML fallback after the existing adapter module
# has loaded. This preserves the established JSON-LD path and only runs the
# fallback when an HTML source returned no records.
from .html_fallback import install as _install_html_fallback

_install_html_fallback()
del _install_html_fallback

# Install explicit source corrections only after the registry is available.
# This layer is intentionally source-specific so healthy sources remain
# untouched.
from .source_overrides import install as _install_source_overrides

_install_source_overrides()
del _install_source_overrides

# Install collectors only for the remaining dynamic sources whose current
# public interfaces cannot be collected by the generic adapter.
from .source_specific_collectors import install as _install_source_specific

_install_source_specific()
del _install_source_specific

# Install the research identity gate before research workers import the
# public research function. Discovery URLs remain provenance; only evidence
# tied to the target lead's company may be promoted into research facts.
from .research_integrity import install as _install_research_integrity

_install_research_integrity()
del _install_research_integrity

# The company-research queue is stateful and must use the durable canonical
# handoff handler. The advanced registry also exposes a stateless research
# handler, so install the explicit precedence rule after agent_workers loads.
from .company_research_handler_override import install as _install_company_research_override

_install_company_research_override()
del _install_company_research_override

# Airtable's configured batch size is intentionally only the size of one
# durable API batch. Install the drain wrapper before scheduler imports the
# batch-delivery function so a production cycle continues through additional
# batches until the backlog is drained or the bounded drain budget expires.
from .airtable_drain_override import install as _install_airtable_drain_override

_install_airtable_drain_override()
del _install_airtable_drain_override
