"""
Health check endpoints.

Provides liveness and readiness probes for container orchestration.
"""

from fastapi import APIRouter
from .config import settings
from .models import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    description="Returns service health status and configuration info"
)
async def health() -> HealthResponse:
    """
    Basic health check endpoint.

    Used by container orchestration (Kubernetes, Docker Compose)
    to verify the service is running.

    Returns:
        HealthResponse with service status and configuration
    """
    return HealthResponse(
        status="ok",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
        store=settings.STORE,
        home_pilot_base_url=settings.HOME_PILOT_BASE_URL,
    )


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="Simple check that the service is running"
)
async def liveness():
    """
    Kubernetes liveness probe.

    Returns 200 if the service is running.
    """
    return {"status": "alive"}


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Check that the service is ready to accept requests"
)
async def readiness():
    """
    Kubernetes readiness probe.

    Checks that dependencies (HomePilot, store) are accessible.
    Returns 200 if ready, 503 if not ready.
    """
    from fastapi import HTTPException
    from .store import get_store
    from .homepilot_client import HomePilotClient

    checks = {
        "store": False,
        "homepilot": False
    }

    # Check store
    try:
        store = get_store()
        # Try a read operation to verify connectivity
        store.get("__health_check__")
        checks["store"] = True
    except Exception:
        pass

    # Check HomePilot connectivity
    try:
        client = HomePilotClient()
        checks["homepilot"] = await client.health_check()
    except Exception:
        pass

    all_healthy = all(checks.values())

    if not all_healthy:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "checks": checks
            }
        )

    return {
        "status": "ready",
        "checks": checks
    }
