# Modèles Fraude

Déposez ici les 3 fichiers suivants :

| Fichier | Description |
|---------|-------------|
| `model.pkl` | Modèle entraîné (ex: IsolationForest, XGBoost...) |
| `scaler.pkl` | Scaler ajusté sur les données d'entraînement |
| `features.pkl` | Liste Python des noms de colonnes dans l'ordre exact attendu |

## Features attendues (ordre)

```python
[
    "type_agent", "anciennete_mois_agent", "zone_logique",
    "montant_fcfa", "type_transaction",
    "solde_avant_fcfa", "solde_apres_fcfa",
    "ecart_zone_habituelle", "nb_tx_24h", "canal",
    # Features calculées (feature engineering)
    "depassement_plafond", "ratio_montant_plafond",
    "ratio_montant_solde", "variation_solde", "agent_recent"
]
```

## Encodages appliqués en amont

- `type_agent` : Détaillant=0, Master=1, Sous-distributeur=2
- `type_transaction` : Recharge credit=0, Transfert P2P=1, Cash-out Flooz=2, Cash-in Flooz=3
- `canal` : POS=0, USSD=1, App agent=2
- `ecart_zone_habituelle` : False=0, True=1
- `zone_logique` : Partie numérique uniquement (ex: Z045 → 45)
- `agent_recent` : 1 si ancienneté < 3 mois, sinon 0

## Features calculées automatiquement

| Feature | Formule |
|---------|---------|
| `depassement_plafond` | max(montant - plafond_journalier, 0) |
| `ratio_montant_plafond` | montant / plafond_journalier |
| `ratio_montant_solde` | montant / solde_avant |
| `variation_solde` | solde_apres - solde_avant |
| `agent_recent` | 1 si anciennete_mois < 3 |
