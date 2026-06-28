import logging

from fastapi import APIRouter, Request

from app.models.schemas import JWK, UCPDiscoveryProfile, UCPProfile, UCPRoutes

router = APIRouter()
logger = logging.getLogger(__name__)

UCP_VERSION = "2026-04-08"
SUPPORTED_CAPABILITIES: tuple[str, ...] = (
    "dev.ucp.shopping.checkout",
    "dev.ucp.shopping.ap2_mandate",
)


@router.get("/.well-known/ucp", response_model=UCPDiscoveryProfile)
def get_ucp_profile(request: Request) -> UCPDiscoveryProfile:
    """Return the UCP machine-readable discovery profile.

    Reads catalog and JWK from app.state (populated at startup by the lifespan handler).
    No authentication required — endpoint is public by spec.
    """
    logger.info("discovery_served", extra={"event": "discovery_served"})
    return UCPDiscoveryProfile(
        ucp=UCPProfile(
            version=UCP_VERSION,
            capabilities=SUPPORTED_CAPABILITIES,
            routes=UCPRoutes(checkout="/api/checkout", complete="/api/complete"),
            signing_keys=[JWK.model_validate(request.app.state.jwk)],
            catalog=request.app.state.catalog,
        )
    )
