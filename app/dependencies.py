import logging

from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.models.schemas import CompleteRequest, PaymentMandatePayload
from app.services import crypto

logger = logging.getLogger(__name__)


def ap2_mandate(
    request: Request,
    body: CompleteRequest,
) -> tuple[str, PaymentMandatePayload]:
    """AP2 mandate verification FastAPI Dependency.

    Call order is MANDATORY (architecture.md §Process Patterns):
    1. extract → 2. format check → 3. EdDSA verify → 4. payload validate → 5. return
    """
    raw_jwt = body.payment_mandate
    client_ip = request.client.host if request.client else "unknown"

    # Step 2: JWT format — must be exactly 3 dot-separated segments
    if raw_jwt.count(".") != 2:
        logger.error(
            "mandate_rejected",
            extra={
                "event": "mandate_rejected",
                "reason": "invalid_jwt_format",
                "ip": client_ip,
            },
        )
        raise HTTPException(status_code=401, detail={"reason": "invalid_jwt_format"})

    # Step 3: EdDSA signature verification
    try:
        public_key = request.app.state.public_key
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"reason": "service_not_ready"},
        ) from exc

    try:
        payload_dict = crypto.verify_mandate(raw_jwt, public_key)
    except crypto.MandateVerificationError as exc:
        logger.error(
            "mandate_rejected",
            extra={
                "event": "mandate_rejected",
                "reason": "invalid_signature",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=401, detail={"reason": "invalid_signature"}
        ) from exc

    # Step 4: Payload structural validation
    try:
        payload = PaymentMandatePayload.model_validate(payload_dict)
    except ValidationError as exc:
        logger.error(
            "mandate_rejected",
            extra={
                "event": "mandate_rejected",
                "reason": "missing_mandate_fields",
                "ip": client_ip,
            },
        )
        raise HTTPException(
            status_code=422, detail={"reason": "missing_mandate_fields"}
        ) from exc

    return raw_jwt, payload
