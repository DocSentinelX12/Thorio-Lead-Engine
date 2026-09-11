__version__ = "0.1.0"

# Install the conservative HTML fallback after the existing adapter module
# has loaded. This preserves the established JSON-LD path and only runs the
# fallback when an HTML source returned no records.
from .html_fallback import install as _install_html_fallback

_install_html_fallback()
del _install_html_fallback
