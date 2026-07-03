# Modèles Churn

Déposez ici les 3 fichiers suivants issus de votre entraînement :

| Fichier | Description |
|---------|-------------|
| `model.pkl` | Modèle entraîné (ex: RandomForest, XGBoost...) |
| `scaler.pkl` | Scaler ajusté sur les données d'entraînement (StandardScaler, MinMaxScaler...) |
| `features.pkl` | Liste Python des noms de colonnes dans l'ordre exact attendu par le modèle |

## Features attendues (ordre)

```python
[
    "anciennete_mois", "region", "type_client", "mode_paiement",
    "canal_acquisition", "smartphone_flag", "arpu_moyen_fcfa",
    "prix_forfait_mensuel_fcfa", "quota_forfait_voix_min",
    "quota_forfait_sms", "quota_data_mo",
    "nb_appels_sortants_moy", "duree_voix_out_moy", "duree_voix_in_moy",
    "nb_sms_moy", "volume_data_moy", "nb_recharges_moy",
    "montant_recharge_moy", "nb_jours_actifs_moy", "solde_moy",
    "nb_tx_flooz_moy",
    "nb_evenements_total", "nb_reclamations", "nb_demandes_resiliation",
    "nb_non_resolu", "delai_resolution_moy", "satisfaction_moy"
]
```

## Encodages appliqués en amont

- `region` : Grand Lomé=0, Maritime=1, Plateaux=2, Centrale=3, Kara=4, Savanes=5
- `type_client` : Particulier=0, PME=1, Corporate=2
- `mode_paiement` : Prepaid=0, Postpaid=1
- `canal_acquisition` : App=0, Parrainage=1, Web=2, Agence=3, Agent=4
- `smartphone_flag` : False=0, True=1
