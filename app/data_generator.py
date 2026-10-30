"""
Générateur de données fictives — Moov Africa Togo ML Analytics.

Crée des lignes aléatoires dans toutes les tables sources en respectant :
  - Les dépendances (dim_forfait → dim_client → fact_conso, fact_evenement)
  - Les contraintes NOT NULL et FK
  - Les encodages de features (region, type_client, etc. → SMALLINT)
  - needs_retraining=TRUE pour déclencher les modèles

Après un seuil de nouvelles lignes, lance automatiquement les modèles ML.
"""
import asyncio
import random
import hashlib
from datetime import datetime, timedelta, date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.ml.model_loader import ml_models
from app.config import settings

# ─── Vocabulaires ─────────────────────────────────────────────────────────────
REGIONS = ["Grand Lomé", "Maritime", "Plateaux", "Centrale", "Kara", "Savanes"]
REGION_ENCODE = {"Grand Lomé": 0, "Maritime": 1, "Plateaux": 2, "Centrale": 3, "Kara": 4, "Savanes": 5}
TYPES_CLIENT = ["Particulier", "PME", "Corporate"]
TYPE_CLIENT_ENCODE = {"Particulier": 0, "PME": 1, "Corporate": 2}
MODES_PAIEMENT = ["Prepaid", "Postpaid"]
MODE_PAIEMENT_ENCODE = {"Prepaid": 0, "Postpaid": 1}
CANAUX_ACQUISITION = ["App", "Parrainage", "Web", "Agence", "Agent"]
CANAL_ACQUISITION_ENCODE = {"App": 0, "Parrainage": 1, "Web": 2, "Agence": 3, "Agent": 4}
TYPES_AGENT = ["Détaillant", "Master", "Sous-distributeur"]
TYPE_AGENT_ENCODE = {"Détaillant": 0, "Master": 1, "Sous-distributeur": 2}
ZONES_LOGIQUES = ["Z045", "Z115", "Z089", "Z201", "Z033", "Z178", "Z256", "Z067"]
TYPES_TRANSACTION = ["Recharge credit", "Transfert P2P", "Cash-out Flooz", "Cash-in Flooz"]
TYPE_TX_ENCODE = {"Recharge credit": 0, "Transfert P2P": 1, "Cash-out Flooz": 2, "Cash-in Flooz": 3}
CANAUX_TX = ["POS", "USSD", "App agent"]
CANAL_TX_ENCODE = {"POS": 0, "USSD": 1, "App agent": 2}
TYPES_FORFAIT = ["Prepaid", "Postpaid", "Hybride"]
SEGMENTS_CIBLE = ["Particulier", "PME", "Corporate", "Grand public"]
TYPES_EVENEMENT = ["Réclamation réseau", "Demande résiliation", "Facturation", "Support technique", "Qualité service"]
CATEGORIES_EVT = ["Réseau", "Facturation", "Technique", "Commercial"]
CANAUX_EVT = ["Appel", "SMS", "Agence", "App mobile", "Email"]
STATUTS_RESOLUTION = ["Résolu", "En cours", "Non résolu"]
STATUTS_LIGNE = ["Actif", "Suspendu", "Résilié"]

FORFAITS_BASE = [
    ("F001", "Liberté 500",  "Prepaid",  "Particulier", 500, 60, 50, 500),
    ("F002", "Liberté 1000", "Prepaid",  "Particulier", 1000, 120, 100, 1024),
    ("F003", "Pro Data",     "Postpaid", "PME",         2500, 300, 200, 5120),
    ("F004", "Corporate",    "Postpaid", "Corporate",   5000, 600, 500, 10240),
    ("F005", "Découverte",   "Prepaid",  "Grand public", 200, 30, 20, 200),
    ("F006", "Business",     "Hybride",  "PME",         3500, 400, 300, 8192),
    ("F007", "Elite",        "Postpaid", "Corporate",   10000, 1000, 800, 20480),
    ("F008", "Jeune",        "Prepaid",  "Particulier", 300, 45, 30, 300),
    ("F009", "Famille",      "Prepaid",  "Particulier", 800, 90, 80, 800),
    ("F010", "Pro Plus",     "Postpaid", "PME",         4500, 500, 400, 10240),
    ("F011", "Business Max", "Hybride",  "Corporate",   6500, 700, 600, 15360),
    ("F012", "Essentiel",    "Prepaid",  "Grand public", 150, 20, 10, 100),
    ("F013", "Liberté 2000", "Prepaid",  "Particulier", 2000, 200, 150, 2048),
    ("F014", "Data Only",    "Prepaid",  "Particulier", 1000, 0, 0, 5120),
    ("F015", "Pro Voice",    "Postpaid", "PME",         3000, 600, 300, 2048),
]

# ─── État global du générateur ───────────────────────────────────────────────
class GeneratorState:
    def __init__(self):
        self.running = False
        self.task: asyncio.Task | None = None
        self.interval_seconds = 5       # génère toutes les 5s
        self.batch_size = 3             # 3 nouvelles entités par cycle
        self.new_since_last_run = {"churn": 0, "fraude": 0, "segmentation": 0}
        self.auto_run_threshold = 50    # lance le modèle après 50 nouvelles lignes
        self.stats = {
            "total_generated": 0,
            "dim_client": 0,
            "dim_agent": 0,
            "dim_forfait": 0,
            "fact_conso": 0,
            "fact_evenement": 0,
            "fact_transaction": 0,
            "models_run": 0,
            "last_activity": None,
            "last_model_run": None,
        }

gen_state = GeneratorState()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))

def _rand_phone_hash() -> str:
    raw = f"{random.randint(70000000, 99999999)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def _rand_conso_id() -> int:
    return random.randint(1_000_000, 9_999_999)

def _rand_tx_id() -> int:
    return random.randint(100_000_000, 999_999_999)

def _rand_evenement_id() -> int:
    return random.randint(1_000_000, 9_999_999)


async def _get_existing_forfaits(db: AsyncSession) -> list[dict]:
    result = await db.execute(text("SELECT forfait_id, prix_mensuel_fcfa, quota_voix_min, quota_sms, quota_data_mo FROM dim_forfait"))
    return [dict(r) for r in result.mappings()]

async def _get_existing_clients(db: AsyncSession, limit: int = 100) -> list[str]:
    result = await db.execute(text("SELECT client_id FROM dim_client ORDER BY inserted_at DESC LIMIT :n"), {"n": limit})
    return [r[0] for r in result.fetchall()]

async def _get_existing_agents(db: AsyncSession, limit: int = 50) -> list[dict]:
    result = await db.execute(text("""
        SELECT a.agent_id, a.type_agent, a.region, a.zone_logique,
               a.plafond_journalier_fcfa, a.anciennete_mois
        FROM dim_agent a ORDER BY a.inserted_at DESC LIMIT :n
    """), {"n": limit})
    return [dict(r) for r in result.mappings()]


# ─── Générateurs individuels ─────────────────────────────────────────────────

async def _maybe_create_forfait(db: AsyncSession) -> int:
    """Crée un forfait occasionnellement (1 chance sur ~100 à chaque cycle)."""
    if random.random() > 0.01:
        return 0
    # Trouver un forfait_id libre
    existing = set()
    r = await db.execute(text("SELECT forfait_id FROM dim_forfait"))
    existing = {row[0] for row in r.fetchall()}

    idx = len(existing) + 1
    while f"F{idx:03d}" in existing:
        idx += 1
    fid = f"F{idx:03d}"

    nom = random.choice(["Liberté", "Pro", "Business", "Essentiel", "Découverte"]) + f" {idx}"
    prix = random.choice([200, 500, 1000, 2000, 3000, 5000, 8000])
    await db.execute(text("""
        INSERT INTO dim_forfait (forfait_id, nom_forfait, type_forfait, segment_cible,
            prix_mensuel_fcfa, quota_voix_min, quota_sms, quota_data_mo, is_actif)
        VALUES (:id, :nom, :type, :seg, :prix, :voix, :sms, :data, TRUE)
        ON CONFLICT (forfait_id) DO NOTHING
    """), {
        "id": fid, "nom": nom, "type": random.choice(TYPES_FORFAIT),
        "seg": random.choice(SEGMENTS_CIBLE), "prix": prix,
        "voix": random.randint(30, 600), "sms": random.randint(10, 500),
        "data": random.randint(100, 20480),
    })
    return 1


async def _create_client(db: AsyncSession, forfaits: list[dict]) -> int:
    """Crée un nouveau client + ses features_churn/segmentation."""
    # Trouver un client_id libre
    idx = random.randint(4001, 99999)
    cid = f"CLI{idx:07d}"
    region = random.choice(REGIONS)
    type_client = random.choice(TYPES_CLIENT)
    mode_paiement = random.choice(MODES_PAIEMENT)
    canal = random.choice(CANAUX_ACQUISITION)
    forfait = random.choice(forfaits) if forfaits else None
    fid = forfait["forfait_id"] if forfait else "F001"
    anc = random.randint(1, 120)
    date_act = date.today() - timedelta(days=anc * 30)
    arpu = round(random.uniform(200, 10000), 2)
    smartphone = random.random() > 0.4

    await db.execute(text("""
        INSERT INTO dim_client (client_id, msisdn_hash, date_activation, anciennete_mois,
            region, type_client, mode_paiement, forfait_id, canal_acquisition,
            smartphone_flag, arpu_moyen_fcfa, statut_ligne, date_reference)
        VALUES (:cid, :msisdn, :dact, :anc, :reg, :tc, :mp, :fid, :canal,
            :smart, :arpu, :statut, :dref)
        ON CONFLICT (client_id) DO NOTHING
    """), {
        "cid": cid, "msisdn": _rand_phone_hash(), "dact": date_act,
        "anc": anc, "reg": region, "tc": type_client, "mp": mode_paiement,
        "fid": fid, "canal": canal, "smart": smartphone, "arpu": arpu,
        "statut": random.choices(STATUTS_LIGNE, weights=[80, 15, 5])[0],
        "dref": date.today(),
    })

    # Insérer features_churn encodé
    prix_f = forfait["prix_mensuel_fcfa"] if forfait else 500
    qv = forfait["quota_voix_min"] if forfait else 60
    qs = forfait["quota_sms"] if forfait else 50
    qd = forfait["quota_data_mo"] if forfait else 500

    await db.execute(text("""
        INSERT INTO features_churn (client_id, anciennete_mois, region, type_client,
            mode_paiement, canal_acquisition, smartphone_flag, arpu_moyen_fcfa,
            forfait_id, prix_forfait_mensuel_fcfa, quota_forfait_voix_min,
            quota_forfait_sms, quota_data_mo, needs_retraining)
        VALUES (:cid, :anc, :reg, :tc, :mp, :canal, :smart, :arpu,
            :fid, :prix, :qv, :qs, :qd, TRUE)
        ON CONFLICT (client_id) DO UPDATE SET needs_retraining = TRUE
    """), {
        "cid": cid, "anc": anc,
        "reg": REGION_ENCODE[region], "tc": TYPE_CLIENT_ENCODE[type_client],
        "mp": MODE_PAIEMENT_ENCODE[mode_paiement],
        "canal": CANAL_ACQUISITION_ENCODE[canal],
        "smart": 1 if smartphone else 0, "arpu": arpu,
        "fid": fid, "prix": prix_f, "qv": qv, "qs": qs, "qd": qd,
    })

    # Insérer features_segmentation encodé
    await db.execute(text("""
        INSERT INTO features_segmentation (client_id, anciennete_mois, region, type_client,
            mode_paiement, forfait_id, prix_mensuel_fcfa, quota_voix_min, quota_sms,
            quota_data_mo, smartphone_flag, arpu_moyen_fcfa, needs_retraining)
        VALUES (:cid, :anc, :reg, :tc, :mp, :fid, :prix, :qv, :qs, :qd, :smart, :arpu, TRUE)
        ON CONFLICT (client_id) DO UPDATE SET needs_retraining = TRUE
    """), {
        "cid": cid, "anc": anc,
        "reg": REGION_ENCODE[region], "tc": TYPE_CLIENT_ENCODE[type_client],
        "mp": MODE_PAIEMENT_ENCODE[mode_paiement],
        "fid": fid, "prix": prix_f, "qv": qv, "qs": qs, "qd": qd,
        "smart": 1 if smartphone else 0, "arpu": arpu,
    })

    # Créer 1-3 lignes de conso mensuelle
    nb_conso = random.randint(1, 3)
    for _ in range(nb_conso):
        mois = _rand_date(date_act, date.today())
        await db.execute(text("""
            INSERT INTO fact_conso_mensuelle (conso_id, client_id, mois, nb_appels_sortants,
                duree_voix_out_min, duree_voix_in_min, nb_sms_envoyes, volume_data_mo,
                nb_recharges, montant_recharge_fcfa, nb_jours_actifs, solde_moyen_fcfa,
                nb_tx_flooz, roaming_flag)
            VALUES (:cid2, :cid, :mois, :nas, :dvo, :dvi, :nse, :vd,
                :nr, :mr, :nja, :sm, :ntf, :roam)
            ON CONFLICT (client_id, mois) DO NOTHING
        """), {
            "cid2": _rand_conso_id(), "cid": cid, "mois": mois,
            "nas": random.randint(0, 200), "dvo": round(random.uniform(0, 600), 2),
            "dvi": round(random.uniform(0, 300), 2), "nse": random.randint(0, 100),
            "vd": round(random.uniform(0, 5000), 2), "nr": random.randint(0, 10),
            "mr": round(random.uniform(0, 50000), 2), "nja": random.randint(1, 30),
            "sm": round(random.uniform(0, 50000), 2), "ntf": random.randint(0, 20),
            "roam": random.random() > 0.8,
        })

    # Créer 0-2 événements
    nb_evt = random.choices([0, 1, 2], weights=[50, 35, 15])[0]
    for _ in range(nb_evt):
        statut_res = random.choice(STATUTS_RESOLUTION)
        await db.execute(text("""
            INSERT INTO fact_evenement_service_client (evenement_id, client_id, date_evenement,
                canal, type_evenement, categorie, statut_resolution, delai_resolution_h, satisfaction_score)
            VALUES (:eid, :cid, :de, :canal, :te, :cat, :sr, :drh, :ss)
            ON CONFLICT (evenement_id) DO NOTHING
        """), {
            "eid": _rand_evenement_id(), "cid": cid,
            "de": datetime.now() - timedelta(days=random.randint(0, 365)),
            "canal": random.choice(CANAUX_EVT),
            "te": random.choice(TYPES_EVENEMENT),
            "cat": random.choice(CATEGORIES_EVT),
            "sr": statut_res,
            "drh": round(random.uniform(0, 72), 2) if statut_res != "En cours" else None,
            "ss": round(random.uniform(1, 5), 2) if statut_res == "Résolu" else None,
        })

    return 1 + nb_conso + nb_evt


async def _create_agent(db: AsyncSession) -> int:
    """Crée un nouvel agent."""
    idx = random.randint(301, 9999)
    aid = f"AG{idx:05d}"
    region = random.choice(REGIONS)
    zone = random.choice(ZONES_LOGIQUES)
    anc = random.randint(1, 60)
    date_rec = date.today() - timedelta(days=anc * 30)
    plafond = round(random.uniform(50000, 500000), 2)

    await db.execute(text("""
        INSERT INTO dim_agent (agent_id, type_agent, region, zone_logique,
            date_recrutement, plafond_journalier_fcfa, statut, anciennete_mois)
        VALUES (:aid, :ta, :reg, :zone, :dr, :pj, :statut, :anc)
        ON CONFLICT (agent_id) DO NOTHING
    """), {
        "aid": aid, "ta": random.choice(TYPES_AGENT),
        "reg": region, "zone": zone, "dr": date_rec,
        "pj": plafond, "statut": random.choice(["Actif", "Actif", "Suspendu"]),
        "anc": anc,
    })
    return 1


async def _create_transaction(db: AsyncSession, agents: list[dict]) -> int:
    """Crée une transaction agent + ses features_fraude encodées."""
    if not agents:
        return 0
    agent = random.choice(agents)
    tx_id = _rand_tx_id()
    type_tx = random.choice(TYPES_TRANSACTION)
    montant = round(random.uniform(500, 50000), 2)
    zone = random.choice(ZONES_LOGIQUES)
    canal = random.choice(CANAUX_TX)
    solde_avant = round(random.uniform(10000, 500000), 2)
    solde_apres = round(solde_avant - montant + random.uniform(-5000, 5000), 2)
    nb_24h = random.randint(1, 20)
    ecart = random.random() > 0.7 and zone != agent.get("zone_logique", "")

    await db.execute(text("""
        INSERT INTO fact_transaction_agent (transaction_id, agent_id, date_heure,
            type_transaction, montant_fcfa, msisdn_benef_hash, zone_logique, canal,
            solde_avant_fcfa, solde_apres_fcfa, nb_tx_24h, ecart_zone_habituelle)
        VALUES (:tx, :aid, :dh, :tt, :mont, :msisdn, :zone, :canal,
            :sav, :sap, :nb24, :ecart)
        ON CONFLICT (transaction_id) DO NOTHING
    """), {
        "tx": tx_id, "aid": agent["agent_id"],
        "dh": datetime.now() - timedelta(hours=random.randint(0, 720)),
        "tt": type_tx, "mont": montant,
        "msisdn": _rand_phone_hash(), "zone": zone, "canal": canal,
        "sav": solde_avant, "sap": solde_apres, "nb24": nb_24h,
        "ecart": ecart,
    })

    # Insérer features_fraude encodé
    zone_num = int("".join(filter(str.isdigit, zone)) or 0)
    plafond = float(agent.get("plafond_journalier_fcfa", 100000))
    anc_agent = int(agent.get("anciennete_mois", 12))
    type_agent_str = agent.get("type_agent", "Détaillant")
    region_str = agent.get("region", "Grand Lomé")

    await db.execute(text("""
        INSERT INTO features_fraude (transaction_id, agent_id, type_transaction,
            montant_fcfa, zone_logique, canal, solde_avant_fcfa, solde_apres_fcfa,
            nb_tx_24h, ecart_zone_habituelle, type_agent, region,
            plafond_journalier_fcfa, anciennete_mois, depassement_plafond,
            ratio_montant_plafond, ratio_montant_solde, variation_solde, agent_recent)
        VALUES (:tx, :aid, :tt, :mont, :zone, :canal, :sav, :sap,
            :nb24, :ecart, :ta, :reg, :pj, :anc,
            :dep, :rmp, :rms, :vs, :ar)
        ON CONFLICT (transaction_id) DO NOTHING
    """), {
        "tx": tx_id, "aid": agent["agent_id"],
        "tt": TYPE_TX_ENCODE.get(type_tx, 0),
        "mont": montant, "zone": zone_num,
        "canal": CANAL_TX_ENCODE.get(canal, 0),
        "sav": solde_avant, "sap": solde_apres,
        "nb24": nb_24h, "ecart": 1 if ecart else 0,
        "ta": TYPE_AGENT_ENCODE.get(type_agent_str, 0),
        "reg": REGION_ENCODE.get(region_str, 0),
        "pj": plafond, "anc": anc_agent,
        "dep": max(montant - plafond, 0),
        "rmp": round(montant / max(plafond, 1), 8),
        "rms": round(montant / max(solde_avant, 1), 8),
        "vs": solde_apres - solde_avant,
        "ar": 1 if anc_agent < 3 else 0,
    })

    return 1


# ─── Boucle principale ────────────────────────────────────────────────────────
async def _generation_loop():
    """Boucle async qui génère des données périodiquement."""
    while gen_state.running:
        try:
            async with AsyncSessionLocal() as db:
                forfaits = await _get_existing_forfaits(db)
                if not forfaits:
                    # Seed initial : créer tous les forfaits de base
                    for fid, nom, tf, seg, prix, qv, qs, qd in FORFAITS_BASE:
                        await db.execute(text("""
                            INSERT INTO dim_forfait (forfait_id, nom_forfait, type_forfait, segment_cible,
                                prix_mensuel_fcfa, quota_voix_min, quota_sms, quota_data_mo, is_actif)
                            VALUES (:id, :nom, :type, :seg, :prix, :voix, :sms, :data, TRUE)
                            ON CONFLICT DO NOTHING
                        """), {"id": fid, "nom": nom, "type": tf, "seg": seg,
                               "prix": prix, "voix": qv, "sms": qs, "data": qd})
                    await db.commit()
                    forfaits = await _get_existing_forfaits(db)

                agents = await _get_existing_agents(db)

                generated = 0
                for _ in range(gen_state.batch_size):
                    action = random.choices(
                        ["client", "client", "transaction", "transaction", "agent"],
                        weights=[30, 30, 25, 25, 10],
                    )[0]

                    if action == "client":
                        n = await _create_client(db, forfaits)
                        gen_state.stats["dim_client"] += 1
                        gen_state.stats["fact_conso"] += n - 1
                        gen_state.new_since_last_run["churn"] += 1
                        gen_state.new_since_last_run["segmentation"] += 1
                        generated += n
                    elif action == "transaction":
                        n = await _create_transaction(db, agents)
                        gen_state.stats["fact_transaction"] += n
                        gen_state.new_since_last_run["fraude"] += n
                        generated += n
                    elif action == "agent":
                        n = await _create_agent(db)
                        gen_state.stats["dim_agent"] += n
                        generated += n

                    n = await _maybe_create_forfait(db)
                    gen_state.stats["dim_forfait"] += n
                    generated += n

                await db.commit()
                gen_state.stats["total_generated"] += generated
                gen_state.stats["last_activity"] = datetime.now().isoformat()

                # Lancer automatiquement les modèles si seuil atteint
                for model_type in ["churn", "fraude", "segmentation"]:
                    if gen_state.new_since_last_run[model_type] >= gen_state.auto_run_threshold:
                        await _auto_run_model(db, model_type)
                        gen_state.new_since_last_run[model_type] = 0

                await db.commit()

        except Exception as e:
            # Log l'erreur mais continue la boucle
            print(f"[data_generator] Error: {e}")

        await asyncio.sleep(gen_state.interval_seconds)


async def _auto_run_model(db: AsyncSession, model_type: str):
    """Lance un modèle ML automatiquement."""
    try:
        import pandas as pd
        from app.routers.churn import REGION_LABELS, TYPE_CLIENT_LABELS  # noqa

        if model_type == "churn":
            if ml_models.churn_model is None:
                return
            result = await db.execute(text("SELECT * FROM features_churn WHERE needs_retraining = TRUE"))
            rows = [dict(r) for r in result.mappings()]
            if not rows:
                return
            df = pd.DataFrame(rows)
            X = ml_models.churn_scaler.transform(df[ml_models.churn_features])
            scores = ml_models.churn_model.predict_proba(X)[:, 1]
            flags = (scores >= settings.SCORE_THRESHOLD_CHURN).astype(int)

            run_result = await db.execute(text("""
                INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
                VALUES ('churn', 'v1.0', 'models/churn/model.pkl', 'auto-daemon')
                RETURNING id
            """))
            run_id = run_result.scalar()

            inserted = 0
            for client_id, score, flag in zip(df["client_id"], scores, flags):
                await db.execute(text("UPDATE prediction_churn SET is_latest = FALSE WHERE client_id = :id AND is_latest = TRUE"), {"id": client_id})
                await db.execute(text("""
                    INSERT INTO prediction_churn (client_id, model_run_id, score_churn, churn_flag, horizon_jours, is_latest)
                    VALUES (:cid, :rid, :score, :flag, 30, TRUE)
                """), {"cid": client_id, "rid": run_id, "score": float(score), "flag": int(flag)})
                inserted += 1

            await db.execute(text("UPDATE features_churn SET needs_retraining = FALSE WHERE client_id = ANY(:ids)"), {"ids": list(df["client_id"])})
            await db.execute(text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"), {"nb": inserted, "id": run_id})
            gen_state.stats["models_run"] += 1
            gen_state.stats["last_model_run"] = datetime.now().isoformat()

        elif model_type == "fraude":
            if ml_models.fraude_model is None:
                return
            result = await db.execute(text("""
                SELECT ff.* FROM features_fraude ff
                WHERE NOT EXISTS (
                    SELECT 1 FROM prediction_fraude pf
                    WHERE pf.transaction_id = ff.transaction_id AND pf.is_latest = TRUE
                )
            """))
            rows = [dict(r) for r in result.mappings()]
            if not rows:
                return
            df = pd.DataFrame(rows)
            X = ml_models.fraude_scaler.transform(df[ml_models.fraude_features])
            scores = ml_models.fraude_model.predict_proba(X)[:, 1]
            flags = (scores >= settings.SCORE_THRESHOLD_FRAUDE).astype(int)

            run_result = await db.execute(text("""
                INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
                VALUES ('fraude', 'v1.0', 'models/fraude/model.pkl', 'auto-daemon')
                RETURNING id
            """))
            run_id = run_result.scalar()

            inserted = 0
            for tx_id, score, flag in zip(df["transaction_id"], scores, flags):
                await db.execute(text("UPDATE prediction_fraude SET is_latest = FALSE WHERE transaction_id = :id AND is_latest = TRUE"), {"id": int(tx_id)})
                await db.execute(text("""
                    INSERT INTO prediction_fraude (transaction_id, model_run_id, score_fraude, fraude_flag, is_latest)
                    VALUES (:tx, :rid, :score, :flag, TRUE)
                """), {"tx": int(tx_id), "rid": run_id, "score": float(score), "flag": int(flag)})
                inserted += 1

            await db.execute(text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"), {"nb": inserted, "id": run_id})
            gen_state.stats["models_run"] += 1
            gen_state.stats["last_model_run"] = datetime.now().isoformat()

        elif model_type == "segmentation":
            if ml_models.segmentation_model is None:
                return
            result = await db.execute(text("SELECT * FROM features_segmentation WHERE needs_retraining = TRUE"))
            rows = [dict(r) for r in result.mappings()]
            if not rows:
                return
            df = pd.DataFrame(rows)
            X = ml_models.segmentation_scaler.transform(df[ml_models.segmentation_features])
            clusters = ml_models.segmentation_model.predict(X)

            run_result = await db.execute(text("""
                INSERT INTO model_run (cas_usage, modele_version, fichier_model, run_by)
                VALUES ('segmentation', 'v1.0', 'models/segmentation/model.pkl', 'auto-daemon')
                RETURNING id
            """))
            run_id = run_result.scalar()

            DEFAULT_LABELS = {0: "Segment 0", 1: "Segment 1", 2: "Segment 2", 3: "Segment 3"}
            inserted = 0
            for client_id, cluster in zip(df["client_id"], clusters):
                seg_id = int(cluster)
                await db.execute(text("""
                    INSERT INTO segment_definition (segment_id, label, model_run_id)
                    VALUES (:sid, :label, :rid)
                    ON CONFLICT (segment_id) DO NOTHING
                """), {"sid": seg_id, "label": DEFAULT_LABELS.get(seg_id, f"Segment {seg_id}"), "rid": run_id})

                await db.execute(text("UPDATE prediction_segment SET is_latest = FALSE WHERE client_id = :id AND is_latest = TRUE"), {"id": client_id})
                await db.execute(text("""
                    INSERT INTO prediction_segment (client_id, model_run_id, segment_id, is_latest)
                    VALUES (:cid, :rid, :sid, TRUE)
                """), {"cid": client_id, "rid": run_id, "sid": seg_id})
                inserted += 1

            await db.execute(text("UPDATE features_segmentation SET needs_retraining = FALSE WHERE client_id = ANY(:ids)"), {"ids": list(df["client_id"])})
            await db.execute(text("UPDATE model_run SET nb_predictions = :nb WHERE id = :id"), {"nb": inserted, "id": run_id})
            gen_state.stats["models_run"] += 1
            gen_state.stats["last_model_run"] = datetime.now().isoformat()

    except Exception as e:
        print(f"[data_generator] Auto-run {model_type} error: {e}")


# ─── API publique ─────────────────────────────────────────────────────────────
def start_generator():
    """Démarre la boucle de génération en arrière-plan."""
    if gen_state.running:
        return
    gen_state.running = True
    gen_state.task = asyncio.create_task(_generation_loop())

def stop_generator():
    """Arrête la boucle de génération."""
    gen_state.running = False
    if gen_state.task and not gen_state.task.done():
        gen_state.task.cancel()
    gen_state.task = None

def get_state() -> dict:
    """Retourne l'état courant du générateur pour le dashboard."""
    return {
        "running": gen_state.running,
        "interval_seconds": gen_state.interval_seconds,
        "batch_size": gen_state.batch_size,
        "auto_run_threshold": gen_state.auto_run_threshold,
        "new_since_last_run": gen_state.new_since_last_run,
        "stats": gen_state.stats,
    }
