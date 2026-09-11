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
