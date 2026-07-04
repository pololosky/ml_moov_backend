from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.ml.model_loader import ml_models
from app.routers import churn, segmentation, fraude, import_excel, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chargement des modèles ML au démarrage
    ml_models.load_all()
    yield


app = FastAPI(
    title="Moov Africa Togo — ML Analytics API",
    description="API FastAPI pour la prédiction du churn, la segmentation client et la détection de fraude.",
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

app.include_router(dashboard.router)
app.include_router(churn.router)
app.include_router(segmentation.router)
app.include_router(fraude.router)
app.include_router(import_excel.router)


@app.get("/")
async def root():
    return {
        "app": "Moov Africa Togo — ML Analytics API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    import sklearn
    modeles = ml_models.status()
    all_loaded = all(v["loaded"] for v in modeles.values())
    return {
        "status": "ok" if all_loaded else "degraded",
        "sklearn_version": sklearn.__version__,
        "modeles": modeles,
    }
