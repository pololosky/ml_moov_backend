"""
Routes fraude — lit/écrit directement dans la table `fraude`.
GET  /api/fraude/stats
GET  /api/fraude/predictions
GET  /api/fraude/transaction/{transaction_id}
POST /api/fraude/run
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.ml.model_loader import ml_models

router = APIRouter(prefix="/api/fraude", tags=["Fraude"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_TX_LABELS = {0: "Recharge crédit", 1: "Cash-in Flooz", 2: "Cash-out Flooz", 3: "Transfert P2P", 4: "Achat forfait"}
TYPE_AGENT_LABELS = {0: "Détaillant", 1: "Sous-distributeur", 2: "Master"}


@router.get("/stats")
async def get_fraude_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN fraude_flag = 1 THEN 1 ELSE 0 END) AS frauduleuses,
                SUM(CASE WHEN fraude_flag = 0 THEN 1 ELSE 0 END) AS normales,
                ROUND(AVG(montant_fcfa)::numeric, 2) AS montant_moyen,
                ROUND(AVG(ratio_montant_plafond)::numeric, 4) AS ratio_plafond_moyen
            FROM fraude
        """)
    )
    row = result.mappings().one_or_none()
    if not row:
        return {"total": 0, "frauduleuses": 0, "normales": 0}
    data = dict(row)
    total = data.get("total") or 0
    data["taux_fraude_pct"] = round(((data.get("frauduleuses") or 0) / total * 100), 2) if total > 0 else 0
    return data


@router.get("/by-type")
async def get_fraude_by_type(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT type_transaction,
                   COUNT(*) AS total,
                   SUM(CASE WHEN fraude_flag = 1 THEN 1 ELSE 0 END) AS frauduleuses,
                   ROUND(AVG(montant_fcfa)::numeric, 2) AS montant_moyen
            FROM fraude
            GROUP BY type_transaction
            ORDER BY frauduleuses DESC
        """)
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["type_label"] = TYPE_TX_LABELS.get(r["type_transaction"], str(r["type_transaction"]))
    return rows


@router.get("/predictions")
async def get_fraude_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    fraude_flag: int | None = Query(None, description="0=Normale | 1=Frauduleuse"),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    where = f"WHERE fraude_flag = {fraude_flag}" if fraude_flag is not None else ""

    result = await db.execute(
        text(f"""
            SELECT f.transaction_id, f.agent_id, f.fraude_flag,
                   f.type_transaction, f.montant_fcfa, f.region,
                   f.nb_tx_24h, f.ecart_zone_habituelle,
                   f.ratio_montant_plafond, f.agent_recent,
                   f.depassement_plafond, f.variation_solde
            FROM fraude f
            {where}
            ORDER BY f.fraude_flag DESC, f.ratio_montant_plafond DESC
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r["region"], str(r["region"]))
        r["type_label"] = TYPE_TX_LABELS.get(r["type_transaction"], str(r["type_transaction"]))

    count_result = await db.execute(text(f"SELECT COUNT(*) FROM fraude f {where}"))
    total = count_result.scalar()
    return {"data": rows, "total": total, "page": page, "size": size}


@router.get("/transaction/{transaction_id}")
async def get_transaction_fraude(transaction_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM fraude WHERE transaction_id = :id"),
        {"id": transaction_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Transaction {transaction_id} non trouvée")
    data = dict(row)
    data["region_label"] = REGION_LABELS.get(data["region"], str(data["region"]))
    data["type_label"] = TYPE_TX_LABELS.get(data["type_transaction"], str(data["type_transaction"]))
    return data


@router.post("/run")
async def run_fraude_detection(db: AsyncSession = Depends(get_db)):
    """Applique le modèle ML sur la table fraude et met à jour fraude_flag."""
    if ml_models.fraude_model is None:
        error_detail = ml_models.fraude_load_error or "Modèle non chargé"
        raise HTTPException(
            503,
            f"Modèle fraude indisponible. {error_detail}"
        )

    import pandas as pd
    result = await db.execute(text("SELECT * FROM fraude"))
    rows = [dict(r) for r in result.mappings()]
    if not rows:
        return {"message": "Table fraude vide", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.fraude_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans la table fraude : {missing}")

    X = ml_models.fraude_scaler.transform(df[feature_cols])
    predictions = ml_models.fraude_model.predict(X)

    updated = 0
    for tx_id, pred in zip(df["transaction_id"], predictions):
        await db.execute(
            text("UPDATE fraude SET fraude_flag = :flag WHERE transaction_id = :id"),
            {"flag": int(pred), "id": tx_id},
        )
        updated += 1

    await db.commit()
    return {"message": f"{updated} prédictions fraude appliquées", "count": updated}
