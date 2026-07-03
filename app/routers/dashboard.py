"""
Dashboard — métriques globales pour la page d'accueil.
GET /api/dashboard/overview
GET /api/dashboard/churn-by-region
GET /api/dashboard/fraude-by-type
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_TX_LABELS = {0: "Recharge crédit", 1: "Cash-in Flooz", 2: "Cash-out Flooz", 3: "Transfert P2P", 4: "Achat forfait"}


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    queries = {
        "nb_clients": "SELECT COUNT(*) FROM dim_client",
        "nb_clients_actifs": "SELECT COUNT(*) FROM dim_client WHERE statut_ligne = 'Actif'",
        "nb_agents": "SELECT COUNT(*) FROM dim_agent",
        "nb_transactions": "SELECT COUNT(*) FROM fact_transaction_agent",
        "nb_churn_total": "SELECT COUNT(*) FROM churn",
        "nb_churned": "SELECT COUNT(*) FROM churn WHERE churn_flag = 1",
        "nb_fraude_total": "SELECT COUNT(*) FROM fraude",
        "nb_frauduleuses": "SELECT COUNT(*) FROM fraude WHERE fraude_flag = 1",
        "nb_segmentation": "SELECT COUNT(*) FROM segmentation",
    }
    result = {}
    for key, sql in queries.items():
        try:
            r = await db.execute(text(sql))
            result[key] = r.scalar() or 0
        except Exception:
            result[key] = 0

    total_churn = result["nb_churn_total"] or 1
    total_fraude = result["nb_fraude_total"] or 1
    result["taux_churn_pct"] = round((result["nb_churned"] / total_churn * 100), 1)
    result["taux_fraude_pct"] = round((result["nb_frauduleuses"] / total_fraude * 100), 1)
    return result


@router.get("/churn-by-region")
async def churn_by_region(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT region,
                   COUNT(*) AS total,
                   SUM(CASE WHEN churn_flag = 1 THEN 1 ELSE 0 END) AS churned
            FROM churn
            GROUP BY region
            ORDER BY churned DESC
        """)
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r["region"], str(r["region"]))
        r["taux_pct"] = round((r["churned"] / (r["total"] or 1) * 100), 1)
    return rows


@router.get("/fraude-by-type")
async def fraude_by_type(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT type_transaction,
                   COUNT(*) AS total,
                   SUM(CASE WHEN fraude_flag = 1 THEN 1 ELSE 0 END) AS frauduleuses
            FROM fraude
            GROUP BY type_transaction
            ORDER BY frauduleuses DESC
        """)
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["type_label"] = TYPE_TX_LABELS.get(r["type_transaction"], str(r["type_transaction"]))
        r["taux_pct"] = round((r["frauduleuses"] / (r["total"] or 1) * 100), 1)
    return rows
