from fastapi import FastAPI

from app.api.factory import build_app
from app.config import Settings


def create_app() -> FastAPI:
    return build_app(Settings())
