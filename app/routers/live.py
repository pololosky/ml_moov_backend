"""
Live dashboard — suivi temps réel du générateur de données et des modèles.

GET  /api/dashboard/live     — état complet (générateur + stats globales)
POST /api/dashboard/generator/start  — démarre le générateur
POST /api/dashboard/generator/stop   — arrête le générateur
PUT  /api/dashboard/generator/config — ajuste interval/batch/threshold
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

from app.database import get_db
from app.auth import RequireDashboard, RequireModelRun
from app.data_generator import gen_state, start_generator, stop_generator, get_state

router = APIRouter(prefix="/api/dashboard", tags=["Live"])

class GeneratorConfig(BaseModel):
    interval_seconds: int | None = None
    batch_size: int | None = None
    auto_run_threshold: int | None = None


@router.get("/live")
async def get_live(current_user: RequireDashboard, db: AsyncSession = Depends(get_db)):
    """État temps réel : générateur + compteurs globaux + runs récents."""
    gen = get_state()

    # Compteurs globaux
    queries = {
        "nb_clients": "SELECT COUNT(*) FROM dim_client",
        "nb_agents": "SELECT COUNT(*) FROM dim_agent",
        "nb_transactions": "SELECT COUNT(*) FROM fact_transaction_agent",
        "nb_conso": "SELECT COUNT(*) FROM fact_conso_mensuelle",
        "nb_evenements": "SELECT COUNT(*) FROM fact_evenement_service_client",
        "churn_pending": "SELECT COUNT(*) FROM features_churn WHERE needs_retraining = TRUE",
        "seg_pending": "SELECT COUNT(*) FROM features_segmentation WHERE needs_retraining = TRUE",
        "fraude_pending": """SELECT COUNT(*) FROM features_fraude ff
            WHERE NOT EXISTS (SELECT 1 FROM prediction_fraude pf
            WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE)""",
    }
    counts = {}
    for key, sql in queries.items():
        try:
            r = await db.execute(text(sql))
            counts[key] = r.scalar() or 0
        except Exception:
            counts[key] = 0

    # Derniers runs
    runs_result = await db.execute(text("""
        SELECT id, cas_usage, modele_version, nb_predictions, run_at, run_by
        FROM model_run ORDER BY run_at DESC LIMIT 10
    """))
    runs = []
    for r in runs_result.mappings():
        row = dict(r)
        row["run_at"] = row["run_at"].isoformat() if hasattr(row["run_at"], "isoformat") else str(row["run_at"])
        runs.append(row)

    # Derniers imports
    imports_result = await db.execute(text("""
        SELECT id, fichier_source, table_cible, nb_lignes_ok, statut, imported_at
        FROM import_log ORDER BY imported_at DESC LIMIT 5
    """))
    imports = []
    for r in imports_result.mappings():
        row = dict(r)
        row["imported_at"] = row["imported_at"].isoformat() if hasattr(row["imported_at"], "isoformat") else str(row["imported_at"])
        imports.append(row)

    return {
        "generator": gen,
        "counts": counts,
        "recent_runs": runs,
        "recent_imports": imports,
    }


@router.post("/generator/start")
async def generator_start(current_user: RequireModelRun):
    start_generator()
    return {"message": "Générateur démarré", "running": True}

@router.post("/generator/stop")
async def generator_stop(current_user: RequireModelRun):
    stop_generator()
    return {"message": "Générateur arrêté", "running": False}

@router.put("/generator/config")
async def generator_config(current_user: RequireModelRun, config: GeneratorConfig):
    if config.interval_seconds is not None:
        gen_state.interval_seconds = max(1, config.interval_seconds)
    if config.batch_size is not None:
        gen_state.batch_size = max(1, config.batch_size)
    if config.auto_run_threshold is not None:
        gen_state.auto_run_threshold = max(1, config.auto_run_threshold)
    return {"message": "Configuration mise à jour", "config": get_state()}
