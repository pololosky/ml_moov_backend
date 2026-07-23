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
import numpy as np

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

# ─── Types de colonnes pour conversion ────────────────────────────────────────
# CORRECTION : Classification par table pour éviter les conflits de types
# (ex: forfait_id est VARCHAR dans dim_forfait mais référencé ailleurs)

INTEGER_COLS_BY_TABLE: dict[str, set[str]] = {
    "dim_forfait": {
        "prix_mensuel_fcfa", "quota_voix_min", "quota_sms", "quota_data_mo",
    },
    "dim_client": {
        "anciennete_mois",
    },
    "dim_agent": {
        "anciennete_mois",
    },
    "fact_conso_mensuelle": {
        "conso_id", "nb_appels_sortants", "nb_sms_envoyes", "nb_recharges",
        "nb_jours_actifs", "nb_tx_flooz",
    },
    "fact_evenement_service_client": {
        "evenement_id",
    },
    "fact_transaction_agent": {
        "transaction_id", "nb_tx_24h",
    },
}

NUMERIC_COLS_BY_TABLE: dict[str, set[str]] = {
    "dim_forfait": set(),
    "dim_client": {
        "arpu_moyen_fcfa",
    },
    "dim_agent": {
        "plafond_journalier_fcfa",
    },
    "fact_conso_mensuelle": {
        "duree_voix_out_min", "duree_voix_in_min", "volume_data_mo",
        "montant_recharge_fcfa", "solde_moyen_fcfa",
    },
    "fact_evenement_service_client": {
        "delai_resolution_h", "satisfaction_score",
    },
    "fact_transaction_agent": {
        "montant_fcfa", "solde_avant_fcfa", "solde_apres_fcfa",
    },
}

BOOLEAN_COLS_BY_TABLE: dict[str, set[str]] = {
    "dim_forfait": {"is_actif"},
    "dim_client": {"smartphone_flag"},
    "fact_conso_mensuelle": {"roaming_flag"},
    "fact_transaction_agent": {"ecart_zone_habituelle"},
}

DATE_COLS_BY_TABLE: dict[str, set[str]] = {
    "dim_client": {"date_activation", "date_reference"},
    "dim_agent": {"date_recrutement"},
    "fact_conso_mensuelle": {"mois"},
    "fact_evenement_service_client": {"date_evenement"},
    "fact_transaction_agent": {"date_heure"},
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


def _to_int(val):
    """Convertit une valeur en entier, retourne None si impossible."""
    if val is None or pd.isna(val):
        return None
    try:
        # Gère les formats avec virgule comme séparateur de milliers
        cleaned = str(val).replace(' ', '').replace(',', '.').strip()
        # Si c'est un nombre décimal, on prend la partie entière
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _to_numeric(val):
    """Convertit une valeur en nombre décimal, retourne None si impossible."""
    if val is None or pd.isna(val):
        return None
    try:
        cleaned = str(val).replace(' ', '').replace(',', '.').strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _to_bool(val):
    """Convertit une valeur en booléen."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().lower()
    if s in ('1', 'true', 'vrai', 'yes', 'oui', 't', 'y', 'o'):
        return True
    if s in ('0', 'false', 'faux', 'no', 'non', 'f', 'n'):
        return False
    return None


def _clean_str(val):
    """Nettoie une chaîne : strip, remplace chaînes vides par None."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ('', 'null', 'none', 'n/a', 'na', '#n/a'):
        return None
    return s


def _clean_df(df: pd.DataFrame, expected_cols: list[str], table: str) -> pd.DataFrame:
    """
    Normalise les noms de colonnes et convertit les types selon la table cible.
    """
    # Normaliser les noms de colonnes
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier : {missing}")

    df = df[expected_cols].copy()

    # Récupérer les classifications pour cette table
    int_cols = INTEGER_COLS_BY_TABLE.get(table, set())
    num_cols = NUMERIC_COLS_BY_TABLE.get(table, set())
    bool_cols = BOOLEAN_COLS_BY_TABLE.get(table, set())
    date_cols = DATE_COLS_BY_TABLE.get(table, set())

    # Conversion colonne par colonne
    for col in expected_cols:
        if col in int_cols:
            df[col] = df[col].apply(_to_int)
        elif col in num_cols:
            df[col] = df[col].apply(_to_numeric)
        elif col in bool_cols:
            df[col] = df[col].apply(_to_bool)
        elif col in date_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        else:
            # Par défaut : chaîne nettoyée (pour les VARCHAR : client_id, forfait_id, etc.)
            df[col] = df[col].apply(_clean_str)

    # Remplacer NaN/NaT par None pour SQL
    df = df.replace({np.nan: None, pd.NaT: None})

    return df


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


def _extract_error_message(exc: Exception) -> str:
    """Extrait un message d'erreur lisible depuis une exception SQLAlchemy/asyncpg."""
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    root = cause or exc
    detail = getattr(root, "detail", None)
    pgmsg = getattr(root, "message", None)
    if detail and pgmsg:
        return f"{pgmsg} — {detail}"
    if pgmsg:
        return pgmsg
    if detail:
        return detail
    return str(root)


async def _mark_clients_for_retraining(db: AsyncSession, client_ids: list[str], table: str):
    """Marque les clients comme nécessitant un recalcul des features."""
    if not client_ids:
        return

    if table in ("fact_conso_mensuelle", "fact_evenement_service_client"):
        await db.execute(
            text("""
                INSERT INTO features_churn (client_id, needs_retraining, computed_at)
                SELECT client_id, TRUE, NOW()
                FROM dim_client
                WHERE client_id = ANY(:ids)
                ON CONFLICT (client_id) DO UPDATE
                SET needs_retraining = TRUE, computed_at = NOW()
            """),
            {"ids": client_ids}
        )
        await db.execute(
            text("""
                INSERT INTO features_segmentation (client_id, needs_retraining, computed_at)
                SELECT client_id, TRUE, NOW()
                FROM dim_client
                WHERE client_id = ANY(:ids)
                ON CONFLICT (client_id) DO UPDATE
                SET needs_retraining = TRUE, computed_at = NOW()
            """),
            {"ids": client_ids}
        )
        await db.commit()


async def _insert_dim_client_features(db: AsyncSession, client_ids: list[str]):
    """Insère ou met à jour les features de base pour les nouveaux clients."""
    if not client_ids:
        return

    await db.execute(
        text("""
            INSERT INTO features_churn (
                client_id, anciennete_mois, region, type_client, mode_paiement,
                canal_acquisition, smartphone_flag, arpu_moyen_fcfa,
                forfait_id, prix_forfait_mensuel_fcfa, quota_forfait_voix_min,
                quota_forfait_sms, quota_data_mo,
                nb_appels_sortants_moy, duree_voix_out_moy, duree_voix_in_moy,
                nb_sms_moy, volume_data_moy, nb_recharges_moy, montant_recharge_moy,
                nb_jours_actifs_moy, solde_moy, nb_tx_flooz_moy,
                nb_evenements_total, nb_reclamations, nb_demandes_resiliation,
                nb_non_resolu, delai_resolution_moy, satisfaction_moy,
                computed_at, needs_retraining
            )
            SELECT
                dc.client_id,
                dc.anciennete_mois,
                CASE dc.region
                    WHEN 'Grand Lome'  THEN 0
                    WHEN 'Maritime'    THEN 1
                    WHEN 'Plateaux'    THEN 2
                    WHEN 'Centrale'    THEN 3
                    WHEN 'Kara'        THEN 4
                    WHEN 'Savanes'     THEN 5
                    ELSE 0
                END::SMALLINT,
                CASE dc.type_client
                    WHEN 'Particulier' THEN 0
                    WHEN 'PME'         THEN 1
                    WHEN 'Corporate'   THEN 2
                    ELSE 0
                END::SMALLINT,
                CASE dc.mode_paiement
                    WHEN 'Prepaid'  THEN 0
                    WHEN 'Postpaid' THEN 1
                    ELSE 0
                END::SMALLINT,
                CASE dc.canal_acquisition
                    WHEN 'App'        THEN 0
                    WHEN 'Parrainage' THEN 1
                    WHEN 'Web'        THEN 2
                    WHEN 'Agence'     THEN 3
                    WHEN 'Agent'      THEN 4
                    ELSE 0
                END::SMALLINT,
                CASE WHEN dc.smartphone_flag THEN 1 ELSE 0 END::SMALLINT,
                dc.arpu_moyen_fcfa,
                dc.forfait_id,
                COALESCE(df.prix_mensuel_fcfa, 0),
                COALESCE(df.quota_voix_min, 0),
                COALESCE(df.quota_sms, 0),
                COALESCE(df.quota_data_mo, 0),
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0,
                NOW(),
                TRUE
            FROM dim_client dc
            LEFT JOIN dim_forfait df ON dc.forfait_id = df.forfait_id
            WHERE dc.client_id = ANY(:ids)
            ON CONFLICT (client_id) DO UPDATE
            SET needs_retraining = TRUE,
                anciennete_mois  = EXCLUDED.anciennete_mois,
                region           = EXCLUDED.region,
                type_client      = EXCLUDED.type_client,
                mode_paiement    = EXCLUDED.mode_paiement,
                canal_acquisition= EXCLUDED.canal_acquisition,
                smartphone_flag  = EXCLUDED.smartphone_flag,
                arpu_moyen_fcfa  = EXCLUDED.arpu_moyen_fcfa,
                forfait_id       = EXCLUDED.forfait_id,
                prix_forfait_mensuel_fcfa = EXCLUDED.prix_forfait_mensuel_fcfa,
                quota_forfait_voix_min    = EXCLUDED.quota_forfait_voix_min,
                quota_forfait_sms         = EXCLUDED.quota_forfait_sms,
                quota_data_mo             = EXCLUDED.quota_data_mo,
                computed_at = NOW()
        """),
        {"ids": client_ids}
    )

    await db.execute(
        text("""
            INSERT INTO features_segmentation (
                client_id, anciennete_mois, region, type_client, mode_paiement,
                forfait_id, prix_mensuel_fcfa, quota_voix_min, quota_sms,
                quota_data_mo, smartphone_flag, arpu_moyen_fcfa,
                voix_out_moy, voix_in_moy, sms_moy, data_moy,
                nb_recharges_moy, recharge_montant_moy, jours_actifs_moy,
                solde_moy, tx_flooz_moy, computed_at, needs_retraining
            )
            SELECT
                dc.client_id,
                dc.anciennete_mois,
                CASE dc.region
                    WHEN 'Grand Lome'  THEN 0 WHEN 'Maritime' THEN 1
                    WHEN 'Plateaux'    THEN 2 WHEN 'Centrale' THEN 3
                    WHEN 'Kara'        THEN 4 WHEN 'Savanes'  THEN 5
                    ELSE 0
                END::SMALLINT,
                CASE dc.type_client
                    WHEN 'Particulier' THEN 0 WHEN 'PME' THEN 1
                    WHEN 'Corporate'   THEN 2 ELSE 0
                END::SMALLINT,
                CASE dc.mode_paiement WHEN 'Prepaid' THEN 0 WHEN 'Postpaid' THEN 1 ELSE 0 END::SMALLINT,
                dc.forfait_id,
                COALESCE(df.prix_mensuel_fcfa, 0),
                COALESCE(df.quota_voix_min, 0),
                COALESCE(df.quota_sms, 0),
                COALESCE(df.quota_data_mo, 0),
                CASE WHEN dc.smartphone_flag THEN 1 ELSE 0 END::SMALLINT,
                dc.arpu_moyen_fcfa,
                0, 0, 0, 0, 0, 0, 0, 0, 0,
                NOW(),
                TRUE
            FROM dim_client dc
            LEFT JOIN dim_forfait df ON dc.forfait_id = df.forfait_id
            WHERE dc.client_id = ANY(:ids)
            ON CONFLICT (client_id) DO UPDATE
            SET needs_retraining = TRUE,
                anciennete_mois  = EXCLUDED.anciennete_mois,
                region           = EXCLUDED.region,
                type_client      = EXCLUDED.type_client,
                mode_paiement    = EXCLUDED.mode_paiement,
                forfait_id       = EXCLUDED.forfait_id,
                prix_mensuel_fcfa= EXCLUDED.prix_mensuel_fcfa,
                quota_voix_min   = EXCLUDED.quota_voix_min,
                quota_sms        = EXCLUDED.quota_sms,
                quota_data_mo    = EXCLUDED.quota_data_mo,
                smartphone_flag  = EXCLUDED.smartphone_flag,
                arpu_moyen_fcfa  = EXCLUDED.arpu_moyen_fcfa,
                computed_at = NOW()
        """),
        {"ids": client_ids}
    )

    await db.commit()


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

    # 3. Valider et nettoyer les colonnes + conversion des types
    expected_cols = TABLE_COLUMNS[table]
    try:
        df = _clean_df(df, expected_cols, table)
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

    if conflict_target and table in ("fact_conso_mensuelle",):
        update_cols = ", ".join([f"{c} = EXCLUDED.{c}" for c in expected_cols if c not in conflict_target.replace(" ", "").split(",")])
        on_conflict = f"ON CONFLICT ({conflict_target}) DO UPDATE SET {update_cols}"
    else:
        on_conflict = f"ON CONFLICT ({conflict_target}) DO NOTHING" if conflict_target else "ON CONFLICT DO NOTHING"

    insert_sql = text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) {on_conflict}")

    # 5. Insertion par chunks de 500
    TABLES_DISABLE_TRIGGERS = {"dim_client", "fact_conso_mensuelle", "fact_evenement_service_client"}

    inserted = 0
    errors = 0
    error_details: list[str] = []
    client_ids_from_conso: list[str] = []
    client_ids_from_evt: list[str] = []
    client_ids_from_dim: list[str] = []

    if table in TABLES_DISABLE_TRIGGERS:
        await db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER ALL"))
        await db.commit()

    for chunk_start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[chunk_start : chunk_start + CHUNK_SIZE]
        for i, row in enumerate(chunk):
            try:
                await db.execute(insert_sql, row)
                inserted += 1

                if table == "fact_conso_mensuelle" and row.get("client_id"):
                    client_ids_from_conso.append(row["client_id"])
                elif table == "fact_evenement_service_client" and row.get("client_id"):
                    client_ids_from_evt.append(row["client_id"])
                elif table == "dim_client" and row.get("client_id"):
                    client_ids_from_dim.append(row["client_id"])

            except Exception as e:
                errors += 1
                lineno = chunk_start + i + 2
                msg = _extract_error_message(e)
                error_details.append(f"Ligne {lineno} : {msg}")
                await db.rollback()
        await db.commit()

    if table in TABLES_DISABLE_TRIGGERS:
        await db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER ALL"))
        await db.commit()

    # 6. Post-traitement
    if table == "dim_client" and client_ids_from_dim:
        unique_client_ids = list(set(client_ids_from_dim))
        await _insert_dim_client_features(db, unique_client_ids)

    if table == "fact_conso_mensuelle" and client_ids_from_conso:
        unique_client_ids = list(set(client_ids_from_conso))
        await _mark_clients_for_retraining(db, unique_client_ids, table)

    if table == "fact_evenement_service_client" and client_ids_from_evt:
        unique_client_ids = list(set(client_ids_from_evt))
        await _mark_clients_for_retraining(db, unique_client_ids, table)

    # 7. Écrire dans import_log
    statut = "Succes" if errors == 0 else ("Erreur" if inserted == 0 else "Partiel")
    details = "\n".join(error_details) if error_details else None
    log_id = await _write_import_log(db, filename, table, nb_in, inserted, errors, statut, details)
    await db.commit()

    message = f"{inserted} lignes insérées dans '{table}'"
    if errors:
        message += f" ({errors} erreur(s))"

    if table in ("fact_conso_mensuelle", "fact_evenement_service_client") and inserted > 0:
        message += " — Clients marqués pour recalcul."
    elif table == "dim_client" and inserted > 0:
        message += " — Features de base insérées."

    return {
        "message": message,
        "table": table,
        "inserted": inserted,
        "errors": errors,
        "total_in_file": nb_in,
        "log_id": log_id,
        "error_details": error_details,
        "needs_retraining": table in ("dim_client", "fact_conso_mensuelle", "fact_evenement_service_client") and inserted > 0,
    }


@router.post("/recalc-features")
async def recalc_features(
    table: str | None = Form(None, description="Table de features : churn, segmentation, fraude, ou all"),
    db: AsyncSession = Depends(get_db),
):
    """Force le recalcul des features pour les clients marqués needs_retraining=TRUE."""
    results = {}

    if table in ("churn", "all"):
        await db.execute(text("""
            SELECT compute_features_churn(client_id) 
            FROM features_churn 
            WHERE needs_retraining = TRUE
        """))
        await db.commit()
        count_result = await db.execute(text("SELECT COUNT(*) FROM features_churn WHERE needs_retraining = TRUE"))
        count_before = count_result.scalar()
        results["churn"] = f"{count_before or 0} clients recalculés"

    if table in ("segmentation", "all"):
        await db.execute(text("""
            SELECT compute_features_segmentation(client_id) 
            FROM features_segmentation 
            WHERE needs_retraining = TRUE
        """))
        await db.commit()
        count_result = await db.execute(text("SELECT COUNT(*) FROM features_segmentation WHERE needs_retraining = TRUE"))
        count_before = count_result.scalar()
        results["segmentation"] = f"{count_before or 0} clients recalculés"

    if table in ("fraude", "all"):
        await db.execute(text("SELECT build_features_fraude_all()"))
        await db.commit()
        results["fraude"] = "Toutes les transactions recalculées"

    return {
        "message": "Recalcul des features terminé",
        "results": results,
    }


@router.post("/{table_name}")
async def import_by_table(
    table_name: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if table_name not in TABLE_COLUMNS:
        raise HTTPException(400, f"Table '{table_name}' non supportée.")
    return await import_upload(file=file, table_override=table_name, db=db)


@router.get("/template/{table_name}")
async def get_template_info(table_name: str):
    if table_name not in TABLE_COLUMNS:
        raise HTTPException(400, f"Table '{table_name}' non supportée.")
    return {
        "table": table_name,
        "colonnes": TABLE_COLUMNS[table_name],
        "nb_colonnes": len(TABLE_COLUMNS[table_name]),
        "conflict_key": UPSERT_CONFLICT.get(table_name),
    }