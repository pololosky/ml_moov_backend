"""
Transformations des données brutes de la BDD vers les features attendues
par chaque modèle ML, en reproduisant exactement le pipeline décrit dans
le document de méthodologie.
"""
import numpy as np
import pandas as pd
from typing import Any

# ─── Encodages (doc section IV) ─────────────────────────────────────────────

REGION_ENCODE = {
    "Grand Lomé": 0, "Maritime": 1, "Plateaux": 2,
    "Centrale": 3, "Kara": 4, "Savanes": 5,
}
TYPE_CLIENT_ENCODE = {"Particulier": 0, "PME": 1, "Corporate": 2}
MODE_PAIEMENT_ENCODE = {"Prepaid": 0, "Postpaid": 1}
CANAL_ACQUISITION_ENCODE = {"App": 0, "Parrainage": 1, "Web": 2, "Agence": 3, "Agent": 4}
TYPE_AGENT_ENCODE = {"Détaillant": 0, "Master": 1, "Sous-distributeur": 2}
TYPE_TRANSACTION_ENCODE = {
    "Recharge credit": 0, "Transfert P2P": 1,
    "Cash-out Flooz": 2, "Cash-in Flooz": 3,
}
CANAL_TX_ENCODE = {"POS": 0, "USSD": 1, "App agent": 2}


def _safe_encode(value: Any, mapping: dict, default: int = -1) -> int:
    return mapping.get(str(value).strip(), default)


def build_churn_features(row: dict) -> pd.DataFrame:
    """
    Construit le vecteur de features churn à partir d'une ligne
    de la vue v_client_features.
    Features attendues (dans l'ordre du features.pkl) :
      anciennete_mois, region, type_client, mode_paiement,
      canal_acquisition, smartphone_flag, arpu_moyen_fcfa,
      prix_forfait_mensuel_fcfa, quota_forfait_voix_min,
      quota_forfait_sms, quota_data_mo,
      nb_appels_sortants_moy, duree_voix_out_moy, duree_voix_in_moy,
      nb_sms_moy, volume_data_moy, nb_recharges_moy,
      montant_recharge_moy, nb_jours_actifs_moy, solde_moy,
      nb_tx_flooz_moy,
      nb_evenements_total, nb_reclamations, nb_demandes_resiliation,
      nb_non_resolu, delai_resolution_moy, satisfaction_moy
    """
    features = {
        "anciennete_mois": row.get("anciennete_mois", 0),
        "region": _safe_encode(row.get("region"), REGION_ENCODE),
        "type_client": _safe_encode(row.get("type_client"), TYPE_CLIENT_ENCODE),
        "mode_paiement": _safe_encode(row.get("mode_paiement"), MODE_PAIEMENT_ENCODE),
        "canal_acquisition": _safe_encode(row.get("canal_acquisition"), CANAL_ACQUISITION_ENCODE),
        "smartphone_flag": int(bool(row.get("smartphone_flag", False))),
        "arpu_moyen_fcfa": float(row.get("arpu_moyen_fcfa") or 0),
        "prix_forfait_mensuel_fcfa": float(row.get("prix_forfait_mensuel_fcfa") or 0),
        "quota_forfait_voix_min": float(row.get("quota_forfait_voix_min") or 0),
        "quota_forfait_sms": float(row.get("quota_forfait_sms") or 0),
        "quota_data_mo": float(row.get("quota_data_mo") or 0),
        "nb_appels_sortants_moy": float(row.get("nb_appels_sortants_moy") or 0),
        "duree_voix_out_moy": float(row.get("duree_voix_out_moy") or 0),
        "duree_voix_in_moy": float(row.get("duree_voix_in_moy") or 0),
        "nb_sms_moy": float(row.get("nb_sms_moy") or 0),
        "volume_data_moy": float(row.get("volume_data_moy") or 0),
        "nb_recharges_moy": float(row.get("nb_recharges_moy") or 0),
        "montant_recharge_moy": float(row.get("montant_recharge_moy") or 0),
        "nb_jours_actifs_moy": float(row.get("nb_jours_actifs_moy") or 0),
        "solde_moy": float(row.get("solde_moy") or 0),
        "nb_tx_flooz_moy": float(row.get("nb_tx_flooz_moy") or 0),
        "nb_evenements_total": int(row.get("nb_evenements_total") or 0),
        "nb_reclamations": int(row.get("nb_reclamations") or 0),
        "nb_demandes_resiliation": int(row.get("nb_demandes_resiliation") or 0),
        "nb_non_resolu": int(row.get("nb_non_resolu") or 0),
        "delai_resolution_moy": float(row.get("delai_resolution_moy") or 0),
        "satisfaction_moy": float(row.get("satisfaction_moy") or 0),
    }
    return pd.DataFrame([features])


def build_segmentation_features(row: dict) -> pd.DataFrame:
    """
    Features segmentation (sans canal_acquisition, sans colonnes événements).
    """
    features = {
        "anciennete_mois": row.get("anciennete_mois", 0),
        "region": _safe_encode(row.get("region"), REGION_ENCODE),
        "type_client": _safe_encode(row.get("type_client"), TYPE_CLIENT_ENCODE),
        "mode_paiement": _safe_encode(row.get("mode_paiement"), MODE_PAIEMENT_ENCODE),
        "smartphone_flag": int(bool(row.get("smartphone_flag", False))),
        "arpu_moyen_fcfa": float(row.get("arpu_moyen_fcfa") or 0),
        "prix_forfait_mensuel_fcfa": float(row.get("prix_forfait_mensuel_fcfa") or 0),
        "quota_forfait_voix_min": float(row.get("quota_forfait_voix_min") or 0),
        "quota_forfait_sms": float(row.get("quota_forfait_sms") or 0),
        "quota_data_mo": float(row.get("quota_data_mo") or 0),
        "duree_voix_out_moy": float(row.get("duree_voix_out_moy") or 0),
        "duree_voix_in_moy": float(row.get("duree_voix_in_moy") or 0),
        "nb_sms_moy": float(row.get("nb_sms_moy") or 0),
        "volume_data_moy": float(row.get("volume_data_moy") or 0),
        "montant_recharge_moy": float(row.get("montant_recharge_moy") or 0),
        "nb_recharges_moy": float(row.get("nb_recharges_moy") or 0),
        "nb_jours_actifs_moy": float(row.get("nb_jours_actifs_moy") or 0),
        "solde_moy": float(row.get("solde_moy") or 0),
        "nb_tx_flooz_moy": float(row.get("nb_tx_flooz_moy") or 0),
    }
    return pd.DataFrame([features])


def build_fraude_features(row: dict) -> pd.DataFrame:
    """
    Features fraude avec feature engineering (doc section III.C).
    """
    montant = float(row.get("montant_fcfa") or 0)
    plafond = float(row.get("plafond_journalier_fcfa") or 1)  # éviter division par 0
    solde_avant = float(row.get("solde_avant_fcfa") or 1)
    solde_apres = float(row.get("solde_apres_fcfa") or 0)
    anciennete = int(row.get("anciennete_mois") or 0)

    # Conversion zone_logique : garder uniquement la partie numérique (Z045 -> 45)
    zone_raw = str(row.get("zone_logique_agent") or "0")
    zone_num = int("".join(filter(str.isdigit, zone_raw)) or 0)

    features = {
        "type_agent": _safe_encode(row.get("type_agent"), TYPE_AGENT_ENCODE),
        "anciennete_mois_agent": anciennete,
        "zone_logique": zone_num,
        "montant_fcfa": montant,
        "type_transaction": _safe_encode(row.get("type_transaction"), TYPE_TRANSACTION_ENCODE),
        "solde_avant_fcfa": solde_avant,
        "solde_apres_fcfa": solde_apres,
        "ecart_zone_habituelle": int(bool(row.get("ecart_zone_habituelle", False))),
        "nb_tx_24h": int(row.get("nb_tx_24h") or 0),
        "canal": _safe_encode(row.get("canal"), CANAL_TX_ENCODE),
        # Feature engineering
        "depassement_plafond": max(montant - plafond, 0),
        "ratio_montant_plafond": montant / plafond,
        "ratio_montant_solde": montant / solde_avant,
        "variation_solde": solde_apres - solde_avant,
        "agent_recent": 1 if anciennete < 3 else 0,
    }
    return pd.DataFrame([features])


def reorder_features(df: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    """Réordonne les colonnes selon la liste de features du modèle."""
    missing = [f for f in feature_names if f not in df.columns]
    if missing:
        for col in missing:
            df[col] = 0
    return df[feature_names]
