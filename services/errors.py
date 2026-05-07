"""
Domain / service-layer errors.

Services may raise fastapi.HTTPException directly for parity with legacy routers.
This module provides optional structured errors when you want to map outside HTTP.
"""

from fastapi import HTTPException


class ServiceError(Exception):
    """Raised from services when routers should translate to HTTP."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def to_http(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)
