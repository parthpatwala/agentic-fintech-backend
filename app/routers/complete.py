from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import ap2_mandate
from app.models.schemas import PaymentMandatePayload

router = APIRouter()


@router.post("/api/complete")
def complete(
    mandate: Annotated[tuple[str, PaymentMandatePayload], Depends(ap2_mandate)],
) -> dict[str, str]:
    """Stub handler — AP2 dependency guard only. Full settlement in Story 4.2."""
    return {"status": "stub"}
