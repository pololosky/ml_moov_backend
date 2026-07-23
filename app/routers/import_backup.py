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


def _extract_error_message(exc: Exception) -> str:
    """
    Extrait un message d'erreur lisible depuis une exception SQLAlchemy/asyncpg.
    Les exceptions de BDD imbriquent souvent le vrai message dans __cause__ ou __context__.
    Exemples :
      - NotNullViolationError → "valeur NULL dans la colonne «client_id»"
      - ForeignKeyViolationError → "clé étrangère «forfait_id» inexistante"
      - UniqueViolationError → "doublon sur la contrainte «conso_id»"
    """
    # Chercher la cause racine (asyncpg lève l'exception réelle dans __cause__)
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    root = cause or exc

    # asyncpg expose un attribut 'detail' et 'message' très lisibles
    detail  = getattr(root, "detail",  None)
    pgmsg   = getattr(root, "message", None)

    if detail and pgmsg:
        return f"{pgmsg} — {detail}"
    if pgmsg:
        return pgmsg
    if detail:
        return detail

    # Dernier recours : str() sans troncature
    return str(root)


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
    # Pour dim_client et les tables qui déclenchent des triggers vers features_*,
    # on désactive les triggers pendant l'INSERT car la fonction PostgreSQL
    # compute_features_churn() reçoit les valeurs texte brutes (ex: 'Grand Lome')
    # alors qu'elle attend des SMALLINT encodés. Le backend Python gère
    # le recalcul des features après import via POST /churn/run ou /segmentation/run.
    TABLES_DISABLE_TRIGGERS = {"dim_client", "fact_conso_mensuelle", "fact_evenement_service_client"}

    inserted = 0
    errors = 0
    error_details: list[str] = []

    # Désactiver les triggers si nécessaire pour cette table
    if table in TABLES_DISABLE_TRIGGERS:
        await db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER ALL"))

    for chunk_start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[chunk_start : chunk_start + CHUNK_SIZE]
        for i, row in enumerate(chunk):
            try:
                await db.execute(insert_sql, row)
                inserted += 1
            except Exception as e:
                errors += 1
                lineno = chunk_start + i + 2  # +2 : header + 1-indexed
                # Extraire le message le plus utile depuis l'exception imbriquée
                msg = _extract_error_message(e)
                error_details.append(f"Ligne {lineno} : {msg}")
                await db.rollback()
        # Commit par chunk pour libérer les verrous
        await db.commit()

    # Réactiver les triggers après insertion
    if table in TABLES_DISABLE_TRIGGERS:
        await db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER ALL"))
        await db.commit()

    # 6. Après import de dim_client : mettre needs_retraining=TRUE dans features_churn/seg
    # pour que le backend recalcule les features encodées correctement
    # (les triggers étaient désactivés pendant l'import)
    if table == "dim_client" and inserted > 0:
        # Insérer des lignes vierges dans features_churn pour les nouveaux clients
        # needs_retraining=TRUE → le job /churn/run les calculera
        await db.execute(text("""
            INSERT INTO features_churn (
                client_id, anciennete_mois, region, type_client, mode_paiement,
                canal_acquisition, smartphone_flag, arpu_moyen_fcfa,
                forfait_id, prix_forfait_mensuel_fcfa, quota_forfait_voix_min,
                quota_forfait_sms, quota_data_mo, needs_retraining
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
                END,
                CASE dc.type_client
                    WHEN 'Particulier' THEN 0
                    WHEN 'PME'         THEN 1
                    WHEN 'Corporate'   THEN 2
                    ELSE 0
                END,
                CASE dc.mode_paiement
                    WHEN 'Prepaid'  THEN 0
                    WHEN 'Postpaid' THEN 1
                    ELSE 0
                END,
                CASE dc.canal_acquisition
                    WHEN 'App'       THEN 0
                    WHEN 'Parrainage' THEN 1
                    WHEN 'Web'       THEN 2
                    WHEN 'Agence'    THEN 3
                    WHEN 'Agent'     THEN 4
                    ELSE 0
                END,
                CASE WHEN dc.smartphone_flag THEN 1 ELSE 0 END,
                dc.arpu_moyen_fcfa,
                dc.forfait_id,
                COALESCE(df.prix_mensuel_fcfa, 0),
                COALESCE(df.quota_voix_min, 0),
                COALESCE(df.quota_sms, 0),
                COALESCE(df.quota_data_mo, 0),
                TRUE   -- needs_retraining : sera recalculé par /churn/run
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
                arpu_moyen_fcfa  = EXCLUDED.arpu_moyen_fcfa
        """), {"ids": [r["client_id"] for r in rows if "client_id" in r]})

        # Idem pour features_segmentation
        await db.execute(text("""
            INSERT INTO features_segmentation (
                client_id, anciennete_mois, region, type_client, mode_paiement,
                forfait_id, prix_mensuel_fcfa, quota_voix_min, quota_sms,
                quota_data_mo, smartphone_flag, arpu_moyen_fcfa, needs_retraining
            )
            SELECT
                dc.client_id,
                dc.anciennete_mois,
                CASE dc.region
                    WHEN 'Grand Lome'  THEN 0 WHEN 'Maritime' THEN 1
                    WHEN 'Plateaux'    THEN 2 WHEN 'Centrale' THEN 3
                    WHEN 'Kara'        THEN 4 WHEN 'Savanes'  THEN 5
                    ELSE 0
                END,
                CASE dc.type_client
                    WHEN 'Particulier' THEN 0 WHEN 'PME' THEN 1
                    WHEN 'Corporate'   THEN 2 ELSE 0
                END,
                CASE dc.mode_paiement WHEN 'Prepaid' THEN 0 WHEN 'Postpaid' THEN 1 ELSE 0 END,
                dc.forfait_id,
                COALESCE(df.prix_mensuel_fcfa, 0),
                COALESCE(df.quota_voix_min, 0),
                COALESCE(df.quota_sms, 0),
                COALESCE(df.quota_data_mo, 0),
                CASE WHEN dc.smartphone_flag THEN 1 ELSE 0 END,
                dc.arpu_moyen_fcfa,
                TRUE
            FROM dim_client dc
            LEFT JOIN dim_forfait df ON dc.forfait_id = df.forfait_id
            WHERE dc.client_id = ANY(:ids)
            ON CONFLICT (client_id) DO UPDATE
            SET needs_retraining = TRUE
        """), {"ids": [r["client_id"] for r in rows if "client_id" in r]})

        await db.commit()

    # 7. Écrire dans import_log
    statut = "Succes" if errors == 0 else ("Erreur" if inserted == 0 else "Partiel")
    details = "\n".join(error_details) if error_details else None
    log_id = await _write_import_log(db, filename, table, nb_in, inserted, errors, statut, details)
    await db.commit()

    return {
        "message": f"{inserted} lignes insérées dans '{table}'" + (f" ({errors} erreur(s))" if errors else ""),
        "table": table,
        "inserted": inserted,
        "errors": errors,
        "total_in_file": nb_in,
        "log_id": log_id,
        "error_details": error_details,  # toutes les erreurs, sans limite
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
