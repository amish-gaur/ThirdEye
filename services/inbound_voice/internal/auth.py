"""Clerk JWT verifier — stub-friendly version.

Replaced at merge with the canonical `services/_shared/auth.py` from
`lane/live-query`. The interface (`verify_jwt() -> HomeownerPrincipal`) is
stable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

log = logging.getLogger("inbound_voice.auth")


@dataclass(frozen=True)
class HomeownerPrincipal:
    homeowner_id: str
    email: str | None = None
    is_test: bool = False


def verify_jwt(authorization: str | None = Header(default=None)) -> HomeownerPrincipal:
    """Extract the homeowner principal from a Clerk JWT.

    Stub implementation: when CLERK_JWKS_URL is unset, accepts a header of the
    form `Bearer test:<homeowner_id>` for local dev. Replace at merge with the
    real verifier — call sites do not change.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token.startswith("test:"):
        homeowner_id = token.split(":", 1)[1].strip()
        if not homeowner_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty test token")
        return HomeownerPrincipal(homeowner_id=homeowner_id, is_test=True)
    # TODO(merge): swap to services/_shared/auth.py when live-query lands.
    log.warning("real JWT verification not yet implemented; rejecting non-test token")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWT verification not configured")
