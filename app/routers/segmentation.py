"""
Routes segmentation — architecture BLOC B → BLOC C.

Lecture  : features_segmentation  (inputs ML)
Écriture : prediction_segment      (outputs avec is_latest)
           segment_definition       (labels nommés par l'équipe Data)

GET  /api/segmentation/stats                   — Distribution des segments (is_latest)
GET  /api/segmentation/predictions             — Clients segmentés (is_latest=TRUE)
GET  /api/segmentation/client/{id}             — Segment actif d'un client
GET  /api/segmentation/segments                — Toutes les définitions de segments
PUT  /api/segmentation/segments/{segment_id}   — Nommer/modifier un segment
GET  /api/segmentation/pending-count           — Nb clients needs_retraining=TRUE
GET  /api/segmentation/history/{client_id}     — Historique des segments d'un client
POST /api/segmentation/run                     — Inférence clustering
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

from app.database import get_db
from app.ml.model_loader import ml_models
from app.utils import clean_row, clean_rows

router = APIRouter(prefix="/api/segmentation", tags=["Segmentation"])

REGION_LABELS = {0: "Grand Lomé", 1: "Maritime", 2: "Plateaux", 3: "Centrale", 4: "Kara", 5: "Savanes"}
TYPE_CLIENT_LABELS = {0: "Particulier", 1: "PME", 2: "Corporate"}

# Labels par défaut — écrasés dès que segment_definition est remplie
DEFAULT_SEGMENT_LABELS = {
    0: {"label": "Segment 0", "couleur_hex": "#004B8D"},
    1: {"label": "Segment 1", "couleur_hex": "#0047CC"},
    2: {"label": "Segment 2", "couleur_hex": "#10B981"},
    3: {"label": "Segment 3", "couleur_hex": "#94A3B8"},
}


class SegmentDefinitionUpdate(BaseModel):
    label: str
    description: str | None = None
    couleur_hex: str | None = None


@router.get("/stats")
async def get_segmentation_stats(db: AsyncSession = Depends(get_db)):
    """Distribution des clients par segment (is_latest=TRUE), avec labels."""
    total_result = await db.execute(
        text("SELECT COUNT(*) FROM prediction_segment WHERE is_latest = TRUE")
    )
    total = total_result.scalar() or 0

    # Distribution par segment avec label si disponible
    dist_result = await db.execute(
        text("""
            SELECT ps.segment_id,
                   COALESCE(sd.label, 'Segment ' || ps.segment_id::text) AS label,
                   COALESCE(sd.couleur_hex, '#94A3B8')                   AS couleur_hex,
                   COUNT(*)                                              AS nb_clients
            FROM prediction_segment ps
            LEFT JOIN segment_definition sd ON ps.segment_id = sd.segment_id
            WHERE ps.is_latest = TRUE
            GROUP BY ps.segment_id, sd.label, sd.couleur_hex
            ORDER BY ps.segment_id
        """)
    )
    segments = [clean_row(dict(r)) for r in dist_result.mappings()]

    # Nb clients en attente de (re)calcul
    pending = await db.execute(
        text("SELECT COUNT(*) FROM features_segmentation WHERE needs_retraining = TRUE")
    )

    return {"total": total, "segments": segments, "pending_retraining": pending.scalar() or 0}


@router.get("/segments")
async def get_segment_definitions(db: AsyncSession = Depends(get_db)):
    """Retourne toutes les définitions de segments (pour l'interface de nommage)."""
    result = await db.execute(
        text("SELECT * FROM segment_definition ORDER BY segment_id")
    )
    return clean_rows([dict(r) for r in result.mappings()])


@router.put("/segments/{segment_id}")
async def upsert_segment_definition(
    segment_id: int,
    body: SegmentDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Insère ou met à jour le label d'un segment.
    Appelé par l'équipe Data après analyse des centroides K-Means.
    """
    await db.execute(
        text("""
            INSERT INTO segment_definition (segment_id, label, description, couleur_hex, updated_at)
            VALUES (:sid, :label, :desc, :color, NOW())
            ON CONFLICT (segment_id) DO UPDATE
            SET label       = EXCLUDED.label,
                description = EXCLUDED.description,
                couleur_hex = EXCLUDED.couleur_hex,
                updated_at  = NOW()
        """),
        {"sid": segment_id, "label": body.label,
         "desc": body.description, "color": body.couleur_hex},
    )
    await db.commit()
    return {"message": f"Segment {segment_id} mis à jour", "label": body.label}


@router.get("/pending-count")
async def get_pending_count(db: AsyncSession = Depends(get_db)):
    """Nombre de clients marqués needs_retraining=TRUE."""
    result = await db.execute(
        text("SELECT COUNT(*) FROM features_segmentation WHERE needs_retraining = TRUE")
    )
    return {"pending": result.scalar() or 0}


@router.get("/predictions")
async def get_segmentation_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    segment_id: int | None = Query(None),
    region: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Clients segmentés (is_latest=TRUE), avec label de segment et features clés."""
    offset = (page - 1) * size
    conditions = ["ps.is_latest = TRUE"]
    if segment_id is not None:
        conditions.append(f"ps.segment_id = {segment_id}")
    if region is not None:
        conditions.append(f"fs.region = {region}")
    where = "WHERE " + " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT ps.id, ps.client_id, ps.segment_id, ps.predicted_at, ps.model_run_id,
                   COALESCE(sd.label, 'Segment ' || ps.segment_id::text)   AS segment_label,
                   COALESCE(sd.couleur_hex, '#94A3B8')                     AS couleur_hex,
                   fs.region, fs.type_client, fs.anciennete_mois,
                   fs.arpu_moyen_fcfa, fs.smartphone_flag,
                   fs.voix_out_moy, fs.data_moy, fs.solde_moy, fs.tx_flooz_moy
            FROM prediction_segment ps
            JOIN features_segmentation fs ON ps.client_id = fs.client_id
            LEFT JOIN segment_definition sd ON ps.segment_id = sd.segment_id
            {where}
            ORDER BY ps.segment_id, ps.client_id
            LIMIT :size OFFSET :offset
        """),
        {"size": size, "offset": offset},
    )
    rows = [clean_row(dict(r)) for r in result.mappings()]
    for r in rows:
        r["region_label"] = REGION_LABELS.get(r.get("region"), str(r.get("region")))
        r["type_client_label"] = TYPE_CLIENT_LABELS.get(r.get("type_client"), str(r.get("type_client")))

    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*) FROM prediction_segment ps
            JOIN features_segmentation fs ON ps.client_id = fs.client_id
            {where}
        """)
    )
    return {"data": rows, "total": count_result.scalar() or 0, "page": page, "size": size}


@router.get("/client/{client_id}")
async def get_client_segment(client_id: str, db: AsyncSession = Depends(get_db)):
    """Segment actif + features d'un client."""
    result = await db.execute(
        text("""
            SELECT ps.*, fs.region, fs.type_client, fs.anciennete_mois,
                   fs.arpu_moyen_fcfa, fs.needs_retraining,
                   COALESCE(sd.label, 'Segment ' || ps.segment_id::text) AS segment_label,
                   COALESCE(sd.couleur_hex, '#94A3B8')                   AS couleur_hex,
                   sd.description AS segment_description
            FROM prediction_segment ps
            JOIN features_segmentation fs ON ps.client_id = fs.client_id
            LEFT JOIN segment_definition sd ON ps.segment_id = sd.segment_id
            WHERE ps.client_id = :id AND ps.is_latest = TRUE
        """),
        {"id": client_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise HTTPException(404, f"Aucun segment actif pour le client {client_id}")
    data = clean_row(dict(row))
    data["region_label"] = REGION_LABELS.get(data.get("region"), str(data.get("region")))
    return data


@router.get("/history/{client_id}")
async def get_segmentation_history(client_id: str, db: AsyncSession = Depends(get_db)):
    """Historique complet des segments d'un client."""
    result = await db.execute(
        text("""
            SELECT ps.id, ps.segment_id, ps.predicted_at, ps.is_latest, ps.model_run_id,
                   COALESCE(sd.label, 'Segment ' || ps.segment_id::text) AS segment_label
            FROM prediction_segment ps
            LEFT JOIN segment_definition sd ON ps.segment_id = sd.segment_id
            WHERE ps.client_id = :id
            ORDER BY ps.predicted_at DESC
        """),
        {"id": client_id},
    )
    return clean_rows([dict(r) for r in result.mappings()])


@router.post("/run")
async def run_segmentation(
    only_pending: bool = Query(False, description="Traiter uniquement les clients needs_retraining=TRUE"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inférence segmentation :
    1. Lit features_segmentation (tous ou needs_retraining=TRUE)
    2. Applique scaler + model K-Means
    3. Passe is_latest=FALSE sur les anciennes prédictions
    4. Insère les nouvelles dans prediction_segment
    5. Remet needs_retraining=FALSE
    6. Crée un enregistrement model_run
    """
    if ml_models.segmentation_model is None:
        raise HTTPException(503, f"Modèle segmentation indisponible. {ml_models.segmentation_load_error or ''}")

    import pandas as pd

    where_pending = "WHERE needs_retraining = TRUE" if only_pending else ""
    result = await db.execute(text(f"SELECT * FROM features_segmentation {where_pending}"))
    rows = clean_rows([dict(r) for r in result.mappings()])

    if not rows:
        return {"message": "Aucun client à traiter", "count": 0}

    df = pd.DataFrame(rows)
    feature_cols = ml_models.segmentation_features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Colonnes manquantes dans features_segmentation : {missing}")

    # Créer un model_run
    run_result = await db.execute(
        text("""
            INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
            VALUES ('segmentation', 'v1.0', 'models/segmentation/model.pkl', 'system')
            RETURNING id
        """)
    )
    run_id = run_result.scalar()

    X = ml_models.segmentation_scaler.transform(df[feature_cols])
    clusters = ml_models.segmentation_model.predict(X)

    inserted = 0
    for client_id, cluster in zip(df["client_id"], clusters):
        segment_id = int(cluster)

        # S'assurer que segment_definition existe (insérer un placeholder si besoin)
        await db.execute(
            text("""
                INSERT INTO segment_definition (segment_id, label, model_run_id)
                VALUES (:sid, :label, :run_id)
                ON CONFLICT (segment_id) DO NOTHING
            """),
            {"sid": segment_id,
             "label": DEFAULT_SEGMENT_LABELS.get(segment_id, {}).get("label", f"Segment {segment_id}"),
             "run_id": run_id},
        )

        # Passer les anciennes prédictions à is_latest=FALSE
        await db.execute(
            text("UPDATE prediction_segment SET is_latest = FALSE WHERE client_id = :id AND is_latest = TRUE"),
            {"id": client_id},
        )
        # Insérer la nouvelle
        await db.execute(
            text("""
                INSERT INTO prediction_segment (client_id, model_run_id, segment_id, is_latest)
                VALUES (:client_id, :run_id, :segment_id, TRUE)
            """),
            {"client_id": client_id, "run_id": run_id, "segment_id": segment_id},
        )
        inserted += 1

    # Remettre needs_retraining à FALSE
    ids = [r["client_id"] for r in rows]
    await db.execute(
        text("UPDATE features_segmentation SET needs_retraining = FALSE WHERE client_id = ANY(:ids)"),
        {"ids": ids},
    )

    await db.execute(
        text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"),
        {"nb": inserted, "id": run_id},
    )

    await db.commit()
    return {
        "message": f"{inserted} clients segmentés (run #{run_id})",
        "count": inserted,
        "run_id": run_id,
    }
