"""
Routes fraude — architecture BLOC B → BLOC C.

Lecture  : features_fraude   (inputs ML pré-calculés par triggers PostgreSQL)
Écriture : prediction_fraude  (outputs ML avec historique + is_latest)

GET  /api/fraude/stats              — KPIs depuis prediction_fraude (is_latest)
GET  /api/fraude/predictions        — Alertes actives paginées (is_latest=TRUE)
GET  /api/fraude/transaction/{id}   — Prédiction active d'une transaction
GET  /api/fraude/pending-count      — Nb transactions sans prédiction is_latest
GET  /api/fraude/history/{id}       — Historique complet d'une transaction
POST /api/fraude/run                — Inférence sur features_fraude non traitées
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.ml.model_loader import ml_models
from app.config import settings
from app.utils import clean_row, clean_rows

router = APIRouter(prefix="/api/fraude", tags=["Fraude"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_TX_LABELS = {0: "Recharge crédit", 1: "Transfert P2P", 2: "Cash-out Flooz", 3: "Cash-in Flooz", 4: "Achat forfait"}
TYPE_AGENT_LABELS = {0: "Détaillant", 1: "Master", 2: "Sous-distributeur"}


@router.get("/stats")
async def get_fraude_stats(db: AsyncSession = Depends(get_db)):
    """KPIs depuis prediction_fraude (is_latest=TRUE)."""
    result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                 AS total,
                SUM(CASE WHEN fraude_flag = 1 THEN 1 ELSE 0 END)        AS frauduleuses,
                SUM(CASE WHEN fraude_flag = 0 THEN 1 ELSE 0 END)        AS normales,
                ROUND(AVG(score_fraude)::numeric, 4)                    AS score_moyen
            FROM prediction_fraude
            WHERE is_latest = TRUE
        """)
    )
    row = result.mappings().one_or_none()
    if not row:
        r2 = await db.execute(text("""
            SELECT COUNT(*) FROM features_fraude ff
            WHERE NOT EXISTS (
                SELECT 1 FROM prediction_fraude pf
                WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
            )
        """))
        return {"total": 0, "frauduleuses": 0, "normales": 0,
                "score_moyen": 0, "taux_fraude_pct": 0,
                "pending_predictions": r2.scalar() or 0}

    data = dict(row)
    total = data.get("total") or 0
    data["taux_fraude_pct"] = round(((data.get("frauduleuses") or 0) / total * 100), 2) if total > 0 else 0

    pending = await db.execute(text("""
        SELECT COUNT(*) FROM features_fraude ff
        WHERE NOT EXISTS (
            SELECT 1 FROM prediction_fraude pf
            WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
        )
    """))
    data["pending_predictions"] = pending.scalar() or 0
    return data


@router.get("/pending-count")
async def get_pending_count(db: AsyncSession = Depends(get_db)):
    """Nombre de transactions dans features_fraude sans prédiction active."""
    result = await db.execute(text("""
        SELECT COUNT(*) FROM features_fraude ff
        WHERE NOT EXISTS (
            SELECT 1 FROM prediction_fraude pf
            WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
        )
    """))
    return {"pending": result.scalar() or 0}


@router.get("/predictions")
async def get_fraude_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    fraude_flag: int | None = Query(None, description="0=Normale | 1=Frauduleuse"),
    db: AsyncSession = Depends(get_db),
):
    """Prédictions actives (is_latest=TRUE) paginées, avec contexte agent."""
    offset = (page - 1) * size
    conditions = ["pf.is_latest = TRUE"]
    if fraude_flag is not None:
        conditions.append(f"pf.fraude_flag = {fraude_flag}")
    where = "WHERE " + " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT pf.id, pf.transaction_id, pf.score_fraude, pf.fraude_flag,
                   pf.predicted_at, pf.model_run_id,
                   ff.agent_id, ff.type_transaction, ff.montant_fcfa,
                   ff.region, ff.nb_tx_24h, ff.ecart_zone_habituelle,
                   ff.ratio_montant_plafond, ff.agent_recent,
                   ff.depassement_plafond, ff.variation_solde, ff.zone_logique
            FROM prediction_fraude pf
            JOIN features_fraude ff ON pf.transaction_id = ff.transaction_id
            {where}
            ORDER BY pf.score_fraude DESC
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [clean_row(dict(r)) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r.get("region"), str(r.get("region")))
        r["type_label"] = TYPE_TX_LABELS.get(r.get("type_transaction"), str(r.get("type_transaction")))

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM prediction_fraude pf {where}")
    )
    return {"data": rows, "total": count_result.scalar() or 0, "page": page, "size": size}


@router.get("/transaction/{transaction_id}")
async def get_transaction_fraude(transaction_id: int, db: AsyncSession = Depends(get_db)):
    """Prédiction active + features complètes d'une transaction."""
    result = await db.execute(
        text("""
            SELECT pf.id, pf.transaction_id, pf.score_fraude, pf.fraude_flag,
                   pf.predicted_at, pf.is_latest, pf.model_run_id,
                   ff.agent_id, ff.type_transaction, ff.montant_fcfa,
                   ff.region, ff.zone_logique, ff.canal, ff.nb_tx_24h,
                   ff.ecart_zone_habituelle, ff.type_agent,
                   ff.plafond_journalier_fcfa, ff.anciennete_mois,
                   ff.depassement_plafond, ff.ratio_montant_plafond,
                   ff.ratio_montant_solde, ff.variation_solde, ff.agent_recent
            FROM prediction_fraude pf
            JOIN features_fraude ff ON pf.transaction_id = ff.transaction_id
            WHERE pf.transaction_id = :id AND pf.is_latest = TRUE
        """),
        {"id": transaction_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Aucune prédiction active pour la transaction {transaction_id}")
    data = clean_row(dict(row))
    data["region_label"] = REGION_LABELS.get(data.get("region"), str(data.get("region")))
    data["type_label"] = TYPE_TX_LABELS.get(data.get("type_transaction"), str(data.get("type_transaction")))
    data["type_agent_label"] = TYPE_AGENT_LABELS.get(data.get("type_agent"), str(data.get("type_agent")))
    return data


@router.get("/history/{transaction_id}")
async def get_fraude_history(transaction_id: int, db: AsyncSession = Depends(get_db)):
    """Historique complet des prédictions d'une transaction."""
    result = await db.execute(
        text("""
            SELECT id, score_fraude, fraude_flag, predicted_at, is_latest, model_run_id
            FROM prediction_fraude
            WHERE transaction_id = :id
            ORDER BY predicted_at DESC
        """),
        {"id": transaction_id},
    )
    return clean_rows([dict(r) for r in result.mappings()])


@router.post("/run")
async def run_fraude_detection(db: AsyncSession = Depends(get_db)):
    """
    Inférence fraude sur features_fraude non encore traitées :
    1. Lit features_fraude WHERE transaction_id NOT IN (prediction_fraude is_latest)
    2. Applique scaler + model
    3. Passe is_latest=FALSE sur les anciennes prédictions
    4. Insère les nouvelles dans prediction_fraude
    5. Crée un enregistrement model_run
    """
    if ml_models.fraude_model is None:
        raise HTTPException(503, f"Modèle fraude indisponible. {ml_models.fraude_load_error or ''}")

    import pandas as pd

    result = await db.execute(text("""
        SELECT ff.*
        FROM features_fraude ff
        WHERE NOT EXISTS (
            SELECT 1 FROM prediction_fraude pf
            WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
        )
    """))
    rows = clean_rows([dict(r) for r in result.mappings()])

    if not rows:
        return {"message": "Toutes les transactions ont déjà une prédiction active", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.fraude_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans features_fraude : {missing}")

    run_result = await db.execute(
        text("""
            INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
            VALUES ('fraude', 'v1.0', 'models/fraude/model.pkl', 'system')
            RETURNING id
        """)
    )
    run_id = run_result.scalar()

    X = ml_models.fraude_scaler.transform(df[feature_cols])
    scores = ml_models.fraude_model.predict_proba(X)[:, 1]
    flags = (scores >= settings.SCORE_THRESHOLD_FRAUDE).astype(int)

    inserted = 0
    for tx_id, score, flag in zip(df["transaction_id"], scores, flags):
        await db.execute(
            text("UPDATE prediction_fraude SET is_latest = FALSE WHERE transaction_id = :id AND is_latest = TRUE"),
            {"id": int(tx_id)},
        )
        await db.execute(
            text("""
                INSERT INTO prediction_fraude
                    (transaction_id, model_run_id, score_fraude, fraude_flag, is_latest)
                VALUES (:tx_id, :run_id, :score, :flag, TRUE)
            """),
            {"tx_id": int(tx_id), "run_id": run_id, "score": float(score), "flag": int(flag)},
        )
        inserted += 1

    await db.execute(
        text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"),
        {"nb": inserted, "id": run_id},
    )
    await db.commit()
    return {"message": f"{inserted} prédictions fraude insérées (run #{run_id})", "count": inserted, "run_id": run_id}
