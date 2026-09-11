"""
TLS compatibility shim for corporate SSL-inspection proxies.

Python 3.13 enables ``ssl.VERIFY_X509_STRICT`` in ``create_default_context()``
(it was off in 3.12 and earlier). Some SSL-inspection proxies mint leaf
certificates that omit the Authority Key Identifier extension, which strict
verification rejects with::

    CERTIFICATE_VERIFY_FAILED: Missing Authority Key Identifier

Clearing that one flag restores the 3.12 behaviour. The certificate chain is
still verified in full against the configured CA bundle — only the strict
RFC 5280 extension checks are relaxed — so this is materially different from
``verify=False``.

Opt-in via ``RELAX_X509_STRICT=true``; off by default.
"""
import os
import ssl


def apply() -> bool:
    """Relax VERIFY_X509_STRICT when RELAX_X509_STRICT is truthy. Returns whether applied."""
    if os.getenv("RELAX_X509_STRICT", "").strip().lower() not in ("1", "true", "yes"):
        return False
    try:
        import urllib3.util.ssl_ as _ssl_util
        import urllib3.connection as _conn
    except ImportError:
        return False

    _orig = _ssl_util.create_urllib3_context

    def _patched(*args, **kwargs):
        ctx = _orig(*args, **kwargs)
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    # urllib3.connection binds the name at import time, so patch both references.
    for _mod in (_ssl_util, _conn):
        if hasattr(_mod, "create_urllib3_context"):
            _mod.create_urllib3_context = _patched
    return True
