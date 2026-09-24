from fastapi import FastAPI

from app.config import Settings
from app.microservices.factory import build_app


def create_app() -> FastAPI:
    return build_app(Settings())
