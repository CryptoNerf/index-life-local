# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""One SSL context for every HTTPS call the app makes through urllib.

A frozen build has no usable system CA store: PyInstaller doesn't ship
OpenSSL's certificate directory, so `urllib.request.urlopen` fails with
CERTIFICATE_VERIFY_FAILED on any https URL. It works perfectly from a source
checkout, which is what makes it easy to miss — and what it looks like to the
user is never "certificates": it is "couldn't sign in to Google", "WebDAV
unreachable", "no weather".

certifi ships the bundle and is already a dependency (and a PyInstaller
hidden import); this module is the single place that wires it in. Anything
here that reaches the network over urllib must pass this context.
"""

import ssl

_ctx = None


def ssl_context() -> ssl.SSLContext:
    """A context that can verify certificates in a frozen build too.

    Falls back to the platform default when certifi is unavailable — better a
    context that works where the system store exists than no request at all.
    """
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ctx = ssl.create_default_context()
    return _ctx
