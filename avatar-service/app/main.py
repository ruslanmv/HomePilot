"""
HomePilot Avatar Service — optional StyleGAN microservice.
"""

from fastapi import FastAPI
from .router import router

app = FastAPI(title="HomePilot Avatar Service", version="0.1.0")
app.include_router(router, prefix="/v1")
