"""
Avatar generation endpoint — produces placeholder images until real
StyleGAN inference is plugged in.
"""

from fastapi import APIRouter

from .schemas import GenerateRequest, GenerateResponse, Result
from .storage.local_store import save_placeholder_pngs

router = APIRouter(tags=["avatars"])


@router.post("/avatars/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    results = save_placeholder_pngs(req.count, req.seeds)
    return GenerateResponse(
        results=[Result(**r) for r in results],
        warnings=[
            "Placeholder generator in use. Replace with StyleGAN inference."
        ],
    )
