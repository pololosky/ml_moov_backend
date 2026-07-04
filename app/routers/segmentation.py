"""
Routes segmentation — lit/écrit directement dans la table `segmentation`.
GET  /api/segmentation/stats
GET  /api/segmentation/predictions
GET  /api/segmentation/client/{client_id}
POST /api/segmentation/run
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.ml.model_loader import ml_models

router = APIRouter(prefix="/api/segmentation", tags=["Segmentation"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_CLIENT_LABELS = {0: "Particulier", 1: "PME", 2: "Corporate"}

# Labels des segments — à ajuster selon vos clusters réels
SEGMENT_LABELS = {0: "Premium Actif", 1: "Standard Modéré", 2: "Faible Usage", 3: "Digital Natif", 4: "Voix Intensif"}


@router.get("/stats")
async def get_segmentation_stats(db: AsyncSession = Depends(get_db)):
    """Distribution par région et type de client."""
    count_result = await db.execute(text("SELECT COUNT(*) FROM segmentation"))
    total = count_result.scalar() or 0

    by_region = await db.execute(
        text("""
            SELECT region, COUNT(*) AS nb
            FROM segmentation GROUP BY region ORDER BY region
        """)
    )
    by_type = await db.execute(
        text("""
            SELECT type_client, COUNT(*) AS nb
            FROM segmentation GROUP BY type_client ORDER BY type_client
        """)
    )

    regions = [
        {**dict(r), "region_label": REGION_LABELS.get(r["region"], str(r["region"]))}
        for r in by_region.mappings()
    ]
    types = [
        {**dict(r), "type_label": TYPE_CLIENT_LABELS.get(r["type_client"], str(r["type_client"]))}
        for r in by_type.mappings()
    ]
    return {"total": total, "by_region": regions, "by_type": types}


@router.get("/predictions")
async def get_segmentation_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    region: int | None = Query(None),
    type_client: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    conditions = []
    if region is not None:
        conditions.append(f"region = {region}")
    if type_client is not None:
        conditions.append(f"type_client = {type_client}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    result = await db.execute(
        text(f"""
            SELECT s.client_id, s.anciennete_mois, s.region, s.type_client,
                   s.mode_paiement, s.arpu_moyen_fcfa, s.smartphone_flag,
                   s.voix_out_moy, s.data_moy, s.solde_moy, s.tx_flooz_moy
            FROM segmentation s
            {where}
            ORDER BY s.arpu_moyen_fcfa DESC
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [dict(r) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r["region"], str(r["region"]))
        r["type_client_label"] = TYPE_CLIENT_LABELS.get(r["type_client"], str(r["type_client"]))

    count_result = await db.execute(text(f"SELECT COUNT(*) FROM segmentation s {where}"))
    total = count_result.scalar()
    return {"data": rows, "total": total, "page": page, "size": size}


@router.get("/client/{client_id}")
async def get_client_segment(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM segmentation WHERE client_id = :id"),
        {"id": client_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Client {client_id} non trouvé dans la table segmentation")
    data = dict(row)
    data["region_label"] = REGION_LABELS.get(data["region"], str(data["region"]))
    return data


@router.post("/run")
async def run_segmentation(db: AsyncSession = Depends(get_db)):
    """Applique le modèle de clustering et crée une colonne segment_id (si elle existe) ou retourne les clusters."""
    if ml_models.segmentation_model is None:
        error_detail = ml_models.segmentation_load_error or "Modèle non chargé"
        raise HTTPException(
            503,
            f"Modèle segmentation indisponible. {error_detail}"
        )

    import pandas as pd
    result = await db.execute(text("SELECT * FROM segmentation"))
    rows = [dict(r) for r in result.mappings()]
    if not rows:
        return {"message": "Table segmentation vide", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.segmentation_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans segmentation : {missing}")

    X = ml_models.segmentation_scaler.transform(df[feature_cols])
    clusters = ml_models.segmentation_model.predict(X)

    # Retourne les résultats (pas de colonne segment dans la table, on renvoie juste le mapping)
    results = [
        {
            "client_id": row["client_id"],
            "segment_id": int(c),
            "segment_label": SEGMENT_LABELS.get(int(c), f"Segment {c}"),
        }
        for row, c in zip(rows, clusters)
    ]
    return {"message": f"{len(results)} clients segmentés", "count": len(results), "segments": results}
