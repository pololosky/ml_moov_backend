"""
Routes churn.
Lit features_churn (BLOC B), écrit prediction_churn (BLOC C).

GET  /api/churn/stats              — KPIs globaux depuis prediction_churn
GET  /api/churn/predictions        — Liste paginée (is_latest=TRUE)
GET  /api/churn/client/{id}        — Prédiction active + features d'un client
GET  /api/churn/pending-count      — Nb clients needs_retraining=TRUE
POST /api/churn/run                — Inférence sur features_churn, écrit prediction_churn
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.ml.model_loader import ml_models
from app.config import settings
from app.utils import clean_row, clean_rows

router = APIRouter(prefix="/api/churn", tags=["Churn"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_CLIENT_LABELS = {0: "Particulier", 1: "PME", 2: "Corporate"}


@router.get("/stats")
async def get_churn_stats(db: AsyncSession = Depends(get_db)):
    """KPIs depuis prediction_churn (is_latest=TRUE) + moyennes features_churn."""
    result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                     AS total,
                SUM(CASE WHEN pc.churn_flag = 1 THEN 1 ELSE 0 END)         AS churned,
                SUM(CASE WHEN pc.churn_flag = 0 THEN 1 ELSE 0 END)         AS not_churned,
                ROUND(AVG(pc.score_churn)::numeric, 4)                     AS score_moyen,
                ROUND(AVG(fc.arpu_moyen_fcfa)::numeric, 2)                 AS arpu_moyen,
                ROUND(AVG(fc.anciennete_mois)::numeric, 1)                 AS anciennete_moy
            FROM prediction_churn pc
            JOIN features_churn fc ON pc.client_id = fc.client_id
            WHERE pc.is_latest = TRUE
        """)
    )
    row = result.mappings().one_or_none()
    if not row:
        # Fallback sur features_churn si aucune prédiction encore
        r2 = await db.execute(text("""
            SELECT COUNT(*) AS total,
                   ROUND(AVG(arpu_moyen_fcfa)::numeric, 2) AS arpu_moyen,
                   ROUND(AVG(anciennete_mois)::numeric, 1) AS anciennete_moy
            FROM features_churn
        """))
        fb = dict(r2.mappings().one_or_none() or {})
        return {
            "total": fb.get("total") or 0,
            "churned": 0, "not_churned": 0,
            "score_moyen": 0, "taux_churn_pct": 0,
            "arpu_moyen": fb.get("arpu_moyen") or 0,
            "anciennete_moy": fb.get("anciennete_moy") or 0,
            "pending_retraining": 0,
        }

    data = dict(row)
    total = data.get("total") or 0
    data["taux_churn_pct"] = round(((data.get("churned") or 0) / total * 100), 2) if total > 0 else 0

    pending = await db.execute(
        text("SELECT COUNT(*) FROM features_churn WHERE needs_retraining = TRUE")
    )
    data["pending_retraining"] = pending.scalar() or 0
    return data


@router.get("/pending-count")
async def get_pending_count(db: AsyncSession = Depends(get_db)):
    """Nombre de clients marqués needs_retraining=TRUE."""
    result = await db.execute(
        text("SELECT COUNT(*) FROM features_churn WHERE needs_retraining = TRUE")
    )
    return {"pending": result.scalar() or 0}


@router.get("/predictions")
async def get_churn_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    churn_flag: int | None = Query(None, description="0=Non churné | 1=Churné"),
    db: AsyncSession = Depends(get_db),
):
    """Dernières prédictions actives (is_latest=TRUE), paginées."""
    offset = (page - 1) * size
    flag_filter = f"AND pc.churn_flag = {churn_flag}" if churn_flag is not None else ""

    result = await db.execute(
        text(f"""
            SELECT pc.id, pc.client_id, pc.score_churn, pc.churn_flag,
                   pc.horizon_jours, pc.predicted_at, pc.model_run_id,
                   fc.region, fc.type_client, fc.anciennete_mois,
                   fc.arpu_moyen_fcfa, fc.nb_reclamations,
                   fc.nb_demandes_resiliation, fc.satisfaction_moy
            FROM prediction_churn pc
            JOIN features_churn fc ON pc.client_id = fc.client_id
            WHERE pc.is_latest = TRUE {flag_filter}
            ORDER BY pc.score_churn DESC
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [clean_row(dict(r)) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r.get("region"), str(r.get("region")))
        r["type_client_label"] = TYPE_CLIENT_LABELS.get(r.get("type_client"), str(r.get("type_client")))

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_churn pc WHERE pc.is_latest = TRUE {flag_filter}")
    )
    return {"data": rows, "total": count_result.scalar() or 0, "page": page, "size": size}


@router.get("/client/{client_id}")
async def get_client_churn(client_id: str, db: AsyncSession = Depends(get_db)):
    """Prédiction active + features d'un client."""
    result = await db.execute(
        text("""
            SELECT pc.*, fc.region, fc.type_client, fc.anciennete_mois,
                   fc.arpu_moyen_fcfa, fc.nb_reclamations, fc.satisfaction_moy,
                   fc.needs_retraining
            FROM prediction_churn pc
            JOIN features_churn fc ON pc.client_id = fc.client_id
            WHERE pc.client_id = :id AND pc.is_latest = TRUE
        """),
        {"id": client_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Aucune prédiction active pour le client {client_id}")
    data = clean_row(dict(row))
    data["region_label"] = REGION_LABELS.get(data.get("region", -1), str(data.get("region")))
    return data


@router.post("/run")
async def run_churn_predictions(
    horizon_jours: int = Query(30, ge=1, description="Horizon de prédiction en jours"),
    only_pending: bool = Query(False, description="Traiter uniquement les clients needs_retraining=TRUE"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inférence churn :
    1. Lit features_churn (tous ou seulement needs_retraining=TRUE)
    2. Applique scaler + model
    3. Passe is_latest=FALSE sur les anciennes prédictions
    4. Insère les nouvelles prédictions dans prediction_churn
    5. Remet needs_retraining=FALSE
    6. Crée un enregistrement model_run
    """
    if ml_models.churn_model is None:
        raise HTTPException(503, f"Modèle churn indisponible. {ml_models.churn_load_error or ''}")

    import pandas as pd

    where_pending = "WHERE needs_retraining = TRUE" if only_pending else ""
    result = await db.execute(text(f"SELECT * FROM features_churn {where_pending}"))
    rows = [dict(r) for r in result.mappings()]

    if not rows:
        return {"message": "Aucun client à traiter", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.churn_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans features_churn : {missing}")

    # Créer un model_run
    run_result = await db.execute(
        text("""
            INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
            VALUES ('churn', 'v1.0', 'models/churn/model.pkl', 'system')
            RETURNING id
        """)
    )
    run_id = run_result.scalar()

    X = ml_models.churn_scaler.transform(df[feature_cols])
    scores = ml_models.churn_model.predict_proba(X)[:, 1]
    flags = (scores >= settings.SCORE_THRESHOLD_CHURN).astype(int)

    inserted = 0
    for client_id, score, flag in zip(df["client_id"], scores, flags):
        # Passer les anciennes prédictions à is_latest=FALSE
        await db.execute(
            text("UPDATE prediction_churn SET is_latest = FALSE WHERE client_id = :id AND is_latest = TRUE"),
            {"id": client_id},
        )
        # Insérer la nouvelle prédiction
        await db.execute(
            text("""
                INSERT INTO prediction_churn
                    (client_id, model_run_id, score_churn, churn_flag, horizon_jours, is_latest)
                VALUES (:client_id, :run_id, :score, :flag, :horizon, TRUE)
            """),
            {"client_id": client_id, "run_id": run_id, "score": float(score),
             "flag": int(flag), "horizon": horizon_jours},
        )
        inserted += 1

    # Remettre needs_retraining à FALSE pour les clients traités
    ids = [r["client_id"] for r in rows]
    await db.execute(
        text("UPDATE features_churn SET needs_retraining = FALSE WHERE client_id = ANY(:ids)"),
        {"ids": ids},
    )

    # Mettre à jour le model_run
    await db.execute(
        text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"),
        {"nb": inserted, "id": run_id},
    )

    await db.commit()
    return {"message": f"{inserted} prédictions churn insérées (run #{run_id})", "count": inserted, "run_id": run_id}


@router.get("/history/{client_id}")
async def get_churn_history(client_id: str, db: AsyncSession = Depends(get_db)):
    """Historique complet des prédictions d'un client."""
    result = await db.execute(
        text("""
            SELECT pc.id, pc.score_churn, pc.churn_flag, pc.horizon_jours,
                   pc.predicted_at, pc.is_latest, pc.model_run_id
            FROM prediction_churn pc
            WHERE pc.client_id = :id
            ORDER BY pc.predicted_at DESC
        """),
        {"id": client_id},
    )
    return clean_rows([dict(r) for r in result.mappings()])
