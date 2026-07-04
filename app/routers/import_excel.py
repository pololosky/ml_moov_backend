"""
Route d'import Excel :
  POST /api/import/{table_name}  — upload d'un fichier .xlsx et insertion en BDD

Tables supportées :
  dim_forfait, dim_client, dim_agent,
  fact_conso_mensuelle, fact_evenement_service_client, fact_transaction_agent
"""
import io
import math
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import pandas as pd

from app.database import get_db

router = APIRouter(prefix="/api/import", tags=["Import Excel"])

# Colonnes attendues par table (clé = nom en BDD)
TABLE_COLUMNS = {
    "dim_forfait": [
        "forfait_id", "nom_forfait", "type_forfait", "segment_cible",
        "prix_mensuel_fcfa", "quota_voix_min", "quota_sms", "quota_data_mo", "is_actif",
    ],
    "dim_client": [
        "client_id", "msisdn_hash", "date_activation", "anciennete_mois",
        "region", "type_client", "mode_paiement", "forfait_id",
        "canal_acquisition", "smartphone_flag", "arpu_moyen_fcfa",
        "statut_ligne", "date_reference",
    ],
    "dim_agent": [
        "agent_id", "type_agent", "region", "zone_logique",
        "date_recrutement", "plafond_journalier_fcfa", "statut", "anciennete_mois",
    ],
    "fact_conso_mensuelle": [
        "conso_id","client_id", "mois", "nb_appels_sortants", "duree_voix_out_min",
        "duree_voix_in_min", "nb_sms_envoyes", "volume_data_mo", "nb_recharges",
        "montant_recharge_fcfa", "nb_jours_actifs", "solde_moyen_fcfa",
        "nb_tx_flooz", "roaming_flag",
    ],
    "fact_evenement_service_client": [
        "evenement_id","client_id", "date_evenement", "canal", "type_evenement",
        "categorie", "statut_resolution", "delai_resolution_h", "satisfaction_score",
    ],
    "fact_transaction_agent": [
        "transaction_id", "agent_id", "date_heure", "type_transaction",
        "montant_fcfa", "msisdn_benef_hash", "zone_logique", "canal",
        "solde_avant_fcfa", "solde_apres_fcfa", "nb_tx_24h",
        "ecart_zone_habituelle", #"fraude_flag",
    ],
}

SUPPORTED_TABLES = set(TABLE_COLUMNS.keys())


def _clean_df(df: pd.DataFrame, expected_cols: list[str]) -> pd.DataFrame:
    """Normalise les noms de colonnes et sélectionne celles attendues."""
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier : {missing}")
    df = df[expected_cols].copy()
    # Remplacer NaN par None pour SQLAlchemy
    df = df.where(pd.notna(df), None)
    return df


@router.post("/{table_name}")
async def import_excel(
    table_name: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if table_name not in SUPPORTED_TABLES:
        raise HTTPException(
            400,
            f"Table '{table_name}' non supportée. Tables valides : {sorted(SUPPORTED_TABLES)}",
        )

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Format de fichier non supporté. Utilisez .xlsx ou .xls")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(400, f"Impossible de lire le fichier Excel : {e}")

    expected_cols = TABLE_COLUMNS[table_name]
    try:
        df = _clean_df(df, expected_cols)
    except ValueError as e:
        raise HTTPException(422, str(e))

    rows = df.to_dict(orient="records")
    if not rows:
        return {"message": "Fichier vide, aucune ligne insérée", "inserted": 0, "errors": 0}

    cols = ", ".join(expected_cols)
    placeholders = ", ".join([f":{c}" for c in expected_cols])

    # Stratégie ON CONFLICT DO NOTHING pour les tables avec clé primaire naturelle
    on_conflict = ""
    if table_name in ("dim_forfait", "dim_client", "dim_agent", "fact_transaction_agent"):
        on_conflict = "ON CONFLICT DO NOTHING"
    elif table_name == "fact_conso_mensuelle":
        on_conflict = "ON CONFLICT (client_id, mois) DO NOTHING"

    insert_sql = text(
        f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders}) {on_conflict}"
    )

    inserted = 0
    errors = 0
    error_details = []

    for i, row in enumerate(rows):
        try:
            await db.execute(insert_sql, row)
            inserted += 1
        except Exception as e:
            errors += 1
            error_details.append({"ligne": i + 2, "erreur": str(e)[:200]})
            await db.rollback()

    await db.commit()

    return {
        "message": f"{inserted} lignes insérées dans '{table_name}'",
        "inserted": inserted,
        "errors": errors,
        "error_details": error_details[:20],  # max 20 erreurs remontées
    }


@router.get("/template/{table_name}")
async def get_template_info(table_name: str):
    """Retourne la liste des colonnes attendues pour un template Excel."""
    if table_name not in SUPPORTED_TABLES:
        raise HTTPException(400, f"Table '{table_name}' non supportée.")
    return {
        "table": table_name,
        "colonnes": TABLE_COLUMNS[table_name],
        "nb_colonnes": len(TABLE_COLUMNS[table_name]),
    }
