# Modèles Segmentation

Déposez ici les 3 fichiers suivants :

| Fichier | Description |
|---------|-------------|
| `model.pkl` | Modèle de clustering (ex: KMeans, DBSCAN...) |
| `scaler.pkl` | Scaler ajusté sur les données d'entraînement |
| `features.pkl` | Liste Python des noms de colonnes dans l'ordre exact attendu |

## Features attendues (ordre)

```python
[
    "anciennete_mois", "region", "type_client", "mode_paiement",
    "smartphone_flag", "arpu_moyen_fcfa",
    "prix_forfait_mensuel_fcfa", "quota_forfait_voix_min",
    "quota_forfait_sms", "quota_data_mo",
    "duree_voix_out_moy", "duree_voix_in_moy", "nb_sms_moy",
    "volume_data_moy", "montant_recharge_moy", "nb_recharges_moy",
    "nb_jours_actifs_moy", "solde_moy", "nb_tx_flooz_moy"
]
```

## Encodages appliqués en amont

- `region` : Grand Lomé=0, Maritime=1, Plateaux=2, Centrale=3, Kara=4, Savanes=5
- `type_client` : Particulier=0, PME=1, Corporate=2
- `mode_paiement` : Prepaid=0, Postpaid=1
- `smartphone_flag` : False=0, True=1

## Labels des segments (à ajuster selon vos clusters)

Le fichier `segmentation/model_loader.py` contient un dictionnaire `SEGMENT_LABELS`
à modifier selon la signification réelle de vos clusters.
