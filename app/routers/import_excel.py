"""
Import Excel — POST /api/import/upload

Flux (conforme à la documentation) :
1. Front envoie POST /import/upload (multipart)
2. FastAPI détecte la table cible depuis le nom du fichier
3. Lecture pandas → validation des colonnes obligatoires → nettoyage (.strip())
4. INSERT ... ON CONFLICT DO UPDATE par chunks de 500 lignes (upsert)
5. Écriture dans import_log (nb_lignes_ok, nb_lignes_err, statut)
6. Les triggers PostgreSQL se déclenchent automatiquement
7. Réponse JSON avec le résumé

Fichiers acceptés :
  dim_client*.xlsx    → dim_client
  dim_forfait*.xlsx   → dim_forfait
  dim_agent*.xlsx     → dim_agent
  conso_mensuel*.xlsx → fact_conso_mensuelle
  evenement*.xlsx     → fact_evenement_service_client
  transaction*.xlsx   → fact_transaction_agent
"""
import io
import re
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import pandas as pd

from app.database import get_db

router = APIRouter(prefix="/api/import", tags=["Import Excel"])

CHUNK_SIZE = 500  # lignes par batch d'insertion

# ─── Mapping nom de fichier → table cible ──────────────────────────────────────
FILE_PATTERN_TO_TABLE = [
    (r"dim_forfait",              "dim_forfait"),
    (r"dim_client",               "dim_client"),
    (r"dim_agent",                "dim_agent"),
    (r"conso_mensuel|fact_conso", "fact_conso_mensuelle"),
    (r"evenement|fact_evt",       "fact_evenement_service_client"),
    (r"transaction|fact_tx",      "fact_transaction_agent"),
]

# ─── Colonnes attendues par table ─────────────────────────────────────────────
TABLE_COLUMNS: dict[str, list[str]] = {
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
        "conso_id", "client_id", "mois", "nb_appels_sortants", "duree_voix_out_min",
        "duree_voix_in_min", "nb_sms_envoyes", "volume_data_mo", "nb_recharges",
        "montant_recharge_fcfa", "nb_jours_actifs", "solde_moyen_fcfa",
        "nb_tx_flooz", "roaming_flag",
    ],
    "fact_evenement_service_client": [
        "evenement_id", "client_id", "date_evenement", "canal", "type_evenement",
        "categorie", "statut_resolution", "delai_resolution_h", "satisfaction_score",
    ],
    "fact_transaction_agent": [
        "transaction_id", "agent_id", "date_heure", "type_transaction",
        "montant_fcfa", "msisdn_benef_hash", "zone_logique", "canal",
        "solde_avant_fcfa", "solde_apres_fcfa", "nb_tx_24h", "ecart_zone_habituelle",
    ],
}

# ─── Colonnes de clé primaire naturelle (upsert ON CONFLICT) ──────────────────
UPSERT_CONFLICT: dict[str, str] = {
    "dim_forfait":                  "forfait_id",
    "dim_client":                   "client_id",
    "dim_agent":                    "agent_id",
    "fact_conso_mensuelle":         "client_id, mois",
    "fact_evenement_service_client": "evenement_id",
    "fact_transaction_agent":       "transaction_id",
}


def _detect_table(filename: str) -> str | None:
    name = filename.lower()
    for pattern, table in FILE_PATTERN_TO_TABLE:
        if re.search(pattern, name):
            return table
    return None


def _clean_df(df: pd.DataFrame, expected_cols: list[str]) -> pd.DataFrame:
    """Normalise les noms de colonnes (.strip() + lowercase) et sélectionne celles attendues."""
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier : {missing}")
    df = df[expected_cols].copy()
    # Nettoyer les chaînes (strip) et remplacer NaN par None
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip() if hasattr(df[col], "str") else df[col]
    return df.where(pd.notna(df), None)


async def _write_import_log(
    db: AsyncSession,
    filename: str,
    table: str,
    nb_in: int,
    nb_ok: int,
    nb_err: int,
    statut: str,
    details: str | None = None,
) -> int:
    result = await db.execute(
        text("""
            INSERT INTO import_log
                (fichier_source, table_cible, nb_lignes_in, nb_lignes_ok, nb_lignes_err, statut, details_erreur, imported_by)
            VALUES (:src, :tbl, :nin, :nok, :nerr, :statut, :details, 'system')
            RETURNING id
        """),
        {"src": filename, "tbl": table, "nin": nb_in,
         "nok": nb_ok, "nerr": nb_err, "statut": statut, "details": details},
    )
    return result.scalar()


@router.post("/upload")
async def import_upload(
    file: UploadFile = File(...),
    table_override: str | None = Form(None, description="Forcer la table cible (optionnel)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload principal — détecte la table depuis le nom de fichier,
    insère par chunks de 500 lignes avec upsert, écrit dans import_log.
    """
    filename = file.filename or "inconnu.xlsx"

    # 1. Déterminer la table cible
    table = table_override or _detect_table(filename)
    if not table or table not in TABLE_COLUMNS:
        supported = [t for _, t in FILE_PATTERN_TO_TABLE]
        raise HTTPException(
            400,
            f"Impossible de détecter la table depuis '{filename}'. "
            f"Renommez votre fichier ou utilisez table_override. "
            f"Tables valides : {supported}",
        )

    if not filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Format non supporté. Utilisez .xlsx ou .xls")

    # 2. Lire le fichier
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(400, f"Impossible de lire le fichier Excel : {e}")

    nb_in = len(df)

    # 3. Valider et nettoyer les colonnes
    expected_cols = TABLE_COLUMNS[table]
    try:
        df = _clean_df(df, expected_cols)
    except ValueError as e:
        log_id = await _write_import_log(db, filename, table, nb_in, 0, nb_in, "Erreur", str(e))
        await db.commit()
        raise HTTPException(422, str(e))

    rows = df.to_dict(orient="records")
    if not rows:
        log_id = await _write_import_log(db, filename, table, 0, 0, 0, "Succes", "Fichier vide")
        await db.commit()
        return {"message": "Fichier vide, aucune ligne insérée", "inserted": 0, "errors": 0, "log_id": log_id}

    # 4. Construire la requête upsert
    cols = ", ".join(expected_cols)
    placeholders = ", ".join([f":{c}" for c in expected_cols])
    conflict_target = UPSERT_CONFLICT.get(table, "")
    on_conflict = f"ON CONFLICT ({conflict_target}) DO NOTHING" if conflict_target else "ON CONFLICT DO NOTHING"
    insert_sql = text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) {on_conflict}")

    # 5. Insertion par chunks de 500
    inserted = 0
    errors = 0
    error_details: list[str] = []

    for chunk_start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[chunk_start : chunk_start + CHUNK_SIZE]
        for i, row in enumerate(chunk):
            try:
                await db.execute(insert_sql, row)
                inserted += 1
            except Exception as e:
                errors += 1
                lineno = chunk_start + i + 2  # +2 : header + 1-indexed
                error_details.append(f"L{lineno}: {str(e)[:150]}")
                await db.rollback()
        # Commit par chunk pour libérer les verrous
        await db.commit()

    # 6. Écrire dans import_log
    statut = "Succes" if errors == 0 else ("Erreur" if inserted == 0 else "Succes")
    details = "\n".join(error_details[:50]) if error_details else None
    log_id = await _write_import_log(db, filename, table, nb_in, inserted, errors, statut, details)
    await db.commit()

    return {
        "message": f"{inserted} lignes insérées dans '{table}'",
        "table": table,
        "inserted": inserted,
        "errors": errors,
        "total_in_file": nb_in,
        "log_id": log_id,
        "error_details": error_details[:20],
    }


@router.post("/{table_name}")
async def import_by_table(
    table_name: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Route alternative : forcer la table cible via l'URL.
    Utilisée par l'interface import pour les tables connues.
    """
    if table_name not in TABLE_COLUMNS:
        raise HTTPException(400, f"Table '{table_name}' non supportée.")
    # Réutiliser la logique principale
    from fastapi import Request
    return await import_upload(file=file, table_override=table_name, db=db)


@router.get("/template/{table_name}")
async def get_template_info(table_name: str):
    """Retourne les colonnes attendues pour un template Excel."""
    if table_name not in TABLE_COLUMNS:
        raise HTTPException(400, f"Table '{table_name}' non supportée.")
    return {
        "table": table_name,
        "colonnes": TABLE_COLUMNS[table_name],
        "nb_colonnes": len(TABLE_COLUMNS[table_name]),
        "conflict_key": UPSERT_CONFLICT.get(table_name),
    }
