from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.api.routes import router
from app.models import db_models  # noqa: F401 (ensures models are registered)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Catalog Matcher API",
    description="Matches internal item lists against government/supplier catalogs.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
