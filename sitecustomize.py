"""
Skill bootstrap for subprocesses (notably `pysonar`).

`pysonar` uses `requests` which, on Windows, does not automatically use the
system (corporate) trust store and may fail with CERTIFICATE_VERIFY_FAILED.
Inject `truststore` early so HTTPS validation succeeds using the OS trust.
"""

from __future__ import annotations

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

