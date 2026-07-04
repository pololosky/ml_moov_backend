"""
Routes churn — lit/écrit directement dans la table `churn`.
GET  /api/churn/stats
GET  /api/churn/predictions
GET  /api/churn/client/{client_id}
POST /api/churn/run
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.ml.model_loader import ml_models

router = APIRouter(prefix="/api/churn", tags=["Churn"])

# Décryptage region pour affichage
REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_CLIENT_LABELS = {0: "Particulier", 1: "PME", 2: "Corporate"}


@router.get("/stats")
async def get_churn_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN churn_flag = 1 THEN 1 ELSE 0 END) AS churned,
                SUM(CASE WHEN churn_flag = 0 THEN 1 ELSE 0 END) AS not_churned,
                ROUND(AVG(arpu_moyen_fcfa)::numeric, 2) AS arpu_moyen,
                ROUND(AVG(anciennete_mois)::numeric, 1) AS anciennete_moy
            FROM churn
        """)
    )
    row = result.mappings().one_or_none()
    if not row:
        return {"total": 0, "churned": 0, "not_churned": 0, "arpu_moyen": 0, "anciennete_moy": 0}

    data = dict(row)
    total = data.get("total") or 0
    churned = data.get("churned") or 0
    data["taux_churn_pct"] = round((churned / total * 100), 2) if total > 0 else 0
    return data


@router.get("/by-region")
async def get_churn_by_region(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT region,
                   COUNT(*) AS total,
                   SUM(CASE WHEN churn_flag = 1 THEN 1 ELSE 0 END) AS churned
            FROM churn
            GROUP BY region
            ORDER BY region
        """)
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r["region"], str(r["region"]))
        total = r["total"] or 1
        r["taux_churn_pct"] = round((r["churned"] / total * 100), 2)
    return rows


@router.get("/predictions")
async def get_churn_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    churn_flag: int | None = Query(None, description="0=Non churné | 1=Churné"),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    where = f"WHERE churn_flag = {churn_flag}" if churn_flag is not None else ""

    result = await db.execute(
        text(f"""
            SELECT c.client_id, c.churn_flag, c.anciennete_mois,
                   c.region, c.type_client, c.arpu_moyen_fcfa,
                   c.nb_reclamations, c.nb_demandes_resiliation,
                   c.satisfaction_moy, c.montant_recharge_moy
            FROM churn c
            {where}
            ORDER BY c.churn_flag DESC, c.nb_demandes_resiliation DESC
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r["region"], str(r["region"]))
        r["type_client_label"] = TYPE_CLIENT_LABELS.get(r["type_client"], str(r["type_client"]))

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM churn c {where}")
    )
    total = count_result.scalar()
    return {"data": rows, "total": total, "page": page, "size": size}


@router.get("/client/{client_id}")
async def get_client_churn(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM churn WHERE client_id = :id"),
        {"id": client_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Client {client_id} non trouvé dans la table churn")
    data = dict(row)
    data["region_label"] = REGION_LABELS.get(data["region"], str(data["region"]))
    return data


@router.post("/run")
async def run_churn_predictions(db: AsyncSession = Depends(get_db)):
    """Applique le modèle ML sur la table churn et met à jour churn_flag."""
    if ml_models.churn_model is None:
        error_detail = ml_models.churn_load_error or "Modèle non chargé"
        raise HTTPException(
            503,
            f"Modèle churn indisponible. {error_detail}"
        )

    import pandas as pd
    result = await db.execute(text("SELECT * FROM churn"))
    rows = [dict(r) for r in result.mappings()]
    if not rows:
        return {"message": "Table churn vide", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.churn_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans la table churn : {missing}")

    X = ml_models.churn_scaler.transform(df[feature_cols])
    predictions = ml_models.churn_model.predict(X)

    updated = 0
    for client_id, pred in zip(df["client_id"], predictions):
        await db.execute(
            text("UPDATE churn SET churn_flag = :flag WHERE client_id = :id"),
            {"flag": int(pred), "id": client_id},
        )
        updated += 1

    await db.commit()
    return {"message": f"{updated} prédictions churn appliquées", "count": updated}
