"""
Dashboard — métriques globales pour la page d'accueil.
Lit depuis les vues SQL v_dashboard_summary, v_churn_actif, v_fraude_actif, v_segment_actif.
Si les vues ne sont pas créées, bascule sur des requêtes directes.

GET /api/dashboard/overview
GET /api/dashboard/churn-by-region
GET /api/dashboard/fraude-by-type
GET /api/dashboard/recent-runs
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.utils import clean_row, clean_rows

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_TX_LABELS = {0: "Recharge crédit", 1: "Transfert P2P", 2: "Cash-out Flooz", 3: "Cash-in Flooz", 4: "Achat forfait"}


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """
    KPIs globaux :
    - Données sources (dim_client, dim_agent, fact_transaction)
    - Prédictions actives (prediction_churn, prediction_fraude, prediction_segment)
    - Features en attente de recalcul
    """
    queries = {
        # Sources
        "nb_clients":          "SELECT COUNT(*) FROM dim_client",
        "nb_clients_actifs":   "SELECT COUNT(*) FROM dim_client WHERE statut_ligne = 'Actif'",
        "nb_agents":           "SELECT COUNT(*) FROM dim_agent",
        "nb_transactions":     "SELECT COUNT(*) FROM fact_transaction_agent",
        # Prédictions churn
        "nb_churn_analyses":   "SELECT COUNT(*) FROM prediction_churn WHERE is_latest = TRUE",
        "nb_churned":          "SELECT COUNT(*) FROM prediction_churn WHERE is_latest = TRUE AND churn_flag = 1",
        # Prédictions fraude
        "nb_fraude_analyses":  "SELECT COUNT(*) FROM prediction_fraude WHERE is_latest = TRUE",
        "nb_frauduleuses":     "SELECT COUNT(*) FROM prediction_fraude WHERE is_latest = TRUE AND fraude_flag = 1",
        # Prédictions segment
        "nb_segmentes":        "SELECT COUNT(*) FROM prediction_segment WHERE is_latest = TRUE",
        # Features en attente
        "churn_pending":       "SELECT COUNT(*) FROM features_churn WHERE needs_retraining = TRUE",
        "seg_pending":         "SELECT COUNT(*) FROM features_segmentation WHERE needs_retraining = TRUE",
        "fraude_pending":      """
            SELECT COUNT(*) FROM features_fraude ff
            WHERE NOT EXISTS (
                SELECT 1 FROM prediction_fraude pf
                WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
            )
        """,
    }

    result = {}
    for key, sql in queries.items():
        try:
            r = await db.execute(text(sql))
            result[key] = r.scalar() or 0
        except Exception:
            result[key] = 0

    # Taux calculés
    nb_c = result["nb_churn_analyses"] or 1
    nb_f = result["nb_fraude_analyses"] or 1
    result["taux_churn_pct"] = round((result["nb_churned"] / nb_c * 100), 1)
    result["taux_fraude_pct"] = round((result["nb_frauduleuses"] / nb_f * 100), 1)

    return result


@router.get("/churn-by-region")
async def churn_by_region(db: AsyncSession = Depends(get_db)):
    """Taux de churn par région (depuis prediction_churn × features_churn is_latest)."""
    result = await db.execute(
        text("""
            SELECT fc.region,
                   COUNT(*)                                                         AS total,
                   SUM(CASE WHEN pc.churn_flag = 1 THEN 1 ELSE 0 END)             AS churned,
                   ROUND(AVG(pc.score_churn)::numeric, 4)                         AS score_moyen
            FROM prediction_churn pc
            JOIN features_churn fc ON pc.client_id = fc.client_id
            WHERE pc.is_latest = TRUE
            GROUP BY fc.region
            ORDER BY churned DESC
        """)
    )
    rows = [clean_row(dict(r)) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r.get("region"), str(r.get("region")))
        r["taux_pct"] = round((r["churned"] / (r["total"] or 1) * 100), 1)
    return rows


@router.get("/fraude-by-type")
async def fraude_by_type(db: AsyncSession = Depends(get_db)):
    """Distribution des fraudes par type de transaction (is_latest)."""
    result = await db.execute(
        text("""
            SELECT ff.type_transaction,
                   COUNT(*)                                                         AS total,
                   SUM(CASE WHEN pf.fraude_flag = 1 THEN 1 ELSE 0 END)            AS frauduleuses,
                   ROUND(AVG(pf.score_fraude)::numeric, 4)                        AS score_moyen
            FROM prediction_fraude pf
            JOIN features_fraude ff ON pf.transaction_id = ff.transaction_id
            WHERE pf.is_latest = TRUE
            GROUP BY ff.type_transaction
            ORDER BY frauduleuses DESC
        """)
    )
    rows = [clean_row(dict(r)) for r in result.mappings()]
    for r in rows:
        r["type_label"] = TYPE_TX_LABELS.get(r.get("type_transaction"), str(r.get("type_transaction")))
        r["taux_pct"] = round((r["frauduleuses"] / (r["total"] or 1) * 100), 1)
    return rows


@router.get("/recent-runs")
async def recent_runs(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Derniers runs de modèles (model_run), pour l'historique du dashboard."""
    result = await db.execute(
        text("""
            SELECT id, cas_usage, modele_version, nb_predictions, run_at, run_by, metriques
            FROM model_run
            ORDER BY run_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return clean_rows([dict(r) for r in result.mappings()])


@router.get("/import-history")
async def import_history(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Historique des imports de fichiers Excel (import_log)."""
    result = await db.execute(
        text("""
            SELECT id, fichier_source, table_cible, nb_lignes_in,
                   nb_lignes_ok, nb_lignes_err, statut, imported_at, imported_by
            FROM import_log
            ORDER BY imported_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return clean_rows([dict(r) for r in result.mappings()])
