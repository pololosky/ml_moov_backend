from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.ml.model_loader import ml_models
from app.routers import churn, segmentation, fraude, import_excel, dashboard
from app import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    ml_models.load_all()
    yield


app = FastAPI(
    title="Moov Africa Togo — ML Analytics API",
    description="API FastAPI · Churn · Fraude · Segmentation · Auth JWT",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth en premier
app.include_router(auth.router)

# Routes métier (protégées par dépendances RBAC internes à chaque router)
app.include_router(dashboard.router)
app.include_router(churn.router)
app.include_router(segmentation.router)
app.include_router(fraude.router)
app.include_router(import_excel.router)


@app.get("/")
async def root():
    return {"app": "Moov Africa Togo — ML Analytics API", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health():
    import sklearn
    modeles = ml_models.status()
    return {
        "status": "ok" if all(v["loaded"] for v in modeles.values()) else "degraded",
        "sklearn_version": sklearn.__version__,
        "modeles": modeles,
    }
