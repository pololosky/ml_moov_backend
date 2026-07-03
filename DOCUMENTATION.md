# Moov Africa Togo — Backend FastAPI : Documentation complète

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du projet](#2-architecture-du-projet)
3. [Base de données](#3-base-de-données)
4. [Comment les données circulent](#4-comment-les-données-circulent)
5. [Les modèles ML](#5-les-modèles-ml)
6. [Les routes API](#6-les-routes-api)
7. [Démarrage pas à pas](#7-démarrage-pas-à-pas)
8. [Flux complet d'utilisation](#8-flux-complet-dutilisation)

---

## 1. Vue d'ensemble

Ce backend est une API REST construite avec **FastAPI** (Python). Son rôle est de :

- Exposer les données de la base PostgreSQL au frontend Next.js
- Charger au démarrage les modèles ML pré-entraînés (`.pkl`)
- Appliquer ces modèles sur les données et mettre à jour les résultats en base

```
Frontend Next.js  ←──── HTTP/JSON ────→  Backend FastAPI  ←──→  PostgreSQL
                                              ↑
                                         Modèles ML (.pkl)
```

---

## 2. Architecture du projet

```
backend/
├── app/
│   ├── main.py              ← Point d'entrée : crée l'app FastAPI, charge les modèles
│   ├── config.py            ← Variables d'environnement (DATABASE_URL, CORS...)
│   ├── database.py          ← Connexion async à PostgreSQL via SQLAlchemy
│   │
│   ├── models/              ← Représentation Python des tables PostgreSQL
│   │   ├── dim_forfait.py
│   │   ├── dim_client.py
│   │   ├── dim_agent.py
│   │   ├── fact_conso.py
│   │   ├── fact_evenement.py
│   │   ├── fact_transaction.py
│   │   ├── sample_target_churn.py
│   │   └── ml_tables.py     ← Tables Churn, Fraude, Segmentation
│   │
│   ├── ml/
│   │   ├── model_loader.py  ← Charge les fichiers .pkl au démarrage
│   │   └── preprocessing.py ← (legacy) Fonctions de transformation des données
│   │
│   └── routers/             ← Les routes HTTP (endpoints API)
│       ├── dashboard.py
│       ├── churn.py
│       ├── fraude.py
│       ├── segmentation.py
│       └── import_excel.py
│
└── models/                  ← Dossier où déposer vos fichiers .pkl
    ├── churn/
    │   ├── model.pkl
    │   ├── scaler.pkl
    │   └── features.pkl
    ├── fraude/
    └── segmentation/
```

---

## 3. Base de données

### 3.1 Tables de référence (données brutes)

| Table | Rôle |
|-------|------|
| `dim_forfait` | Catalogue des forfaits (prépayé, postpayé…) |
| `dim_client` | Informations clients (région, ancienneté, ARPU…) |
| `dim_agent` | Informations agents (type, zone, plafond…) |
| `fact_conso_mensuelle` | Consommation mensuelle par client (appels, data, SMS…) |
| `fact_evenement_service_client` | Réclamations, incidents, satisfaction client |
| `fact_transaction_agent` | Toutes les transactions effectuées par les agents |
| `sample_target_churn` | Vérité terrain : quels clients ont réellement churné |

### 3.2 Tables ML (datasets préparés)

Ces trois tables sont le **résultat du preprocessing**. Elles contiennent les données déjà agrégées, encodées numériquement, prêtes à être passées aux modèles.

| Table | Contient | Colonne cible |
|-------|----------|---------------|
| `churn` | 1 ligne par client avec ses features moyennées et encodées | `churn_flag` (0/1) |
| `fraude` | 1 ligne par transaction avec features calculées + feature engineering | `fraude_flag` (0/1) |
| `segmentation` | 1 ligne par client avec features de consommation moyennées | _(pas de cible, clustering)_ |

### 3.3 Encodages appliqués dans les tables ML

**Région** : `Grand Lomé=0, Maritime=1, Plateaux=2, Centrale=3, Kara=4, Savanes=5`

**Type client** : `Particulier=0, PME=1, Corporate=2`

**Mode paiement** : `Prepaid=0, Postpaid=1`

**Type transaction** : `Recharge crédit=0, Cash-in Flooz=1, Cash-out Flooz=2, Transfert P2P=3, Achat forfait=4`

**Canal transaction** : `USSD=0, POS=1, App agent=2`

**Type agent** : `Détaillant=0, Sous-distributeur=1, Master=2`

---

## 4. Comment les données circulent

### Étape 1 — Import des données brutes

Vous importez vos fichiers Excel via l'interface ou l'API :

```
POST /api/import/dim_client    → insère dans dim_client
POST /api/import/dim_forfait   → insère dans dim_forfait
POST /api/import/dim_agent     → insère dans dim_agent
POST /api/import/fact_conso_mensuelle  → insère les conso mensuelles
...etc
```

### Étape 2 — Préparation des tables ML (hors backend)

Les tables `churn`, `fraude` et `segmentation` sont peuplées **en dehors du backend**, par votre pipeline de preprocessing Python/SQL. Ce pipeline :

1. Lit les tables brutes (`dim_client`, `fact_conso_mensuelle`, etc.)
2. Calcule les agrégations (moyennes sur 12 mois, comptages…)
3. Applique les encodages numériques
4. Calcule les features dérivées (fraude : `ratio_montant_plafond`, `depassement_plafond`…)
5. Insère les résultats dans `churn`, `fraude`, `segmentation`

> **En résumé** : les tables ML sont remplies par votre script de preprocessing,
> pas automatiquement par le backend.

### Étape 3 — Prédiction ML via l'API

Une fois les tables ML remplies, vous appelez :

```
POST /api/churn/run        → applique model.pkl sur la table churn, met à jour churn_flag
POST /api/fraude/run       → applique model.pkl sur la table fraude, met à jour fraude_flag
POST /api/segmentation/run → applique model.pkl sur segmentation, retourne les clusters
```

Le backend :
1. Lit **toutes les lignes** de la table ML concernée
2. Extrait les colonnes dans l'ordre exact de `features.pkl`
3. Applique `scaler.pkl` pour normaliser
4. Applique `model.pkl` pour prédire
5. Écrit les prédictions en base (`UPDATE ... SET churn_flag = ...`)

---

## 5. Les modèles ML

### 5.1 Les 3 fichiers requis par modèle

Chaque cas d'usage (churn, fraude, segmentation) nécessite **3 fichiers** dans son dossier :

```
models/churn/
├── model.pkl     ← Le modèle entraîné (RandomForest, XGBoost, etc.)
├── scaler.pkl    ← Le StandardScaler/MinMaxScaler ajusté sur les données d'entraînement
└── features.pkl  ← Liste Python des noms de colonnes dans l'ordre exact attendu
```

### 5.2 Comment générer features.pkl

Dans votre script d'entraînement, après avoir défini vos colonnes :

```python
import joblib

# Exemple pour le churn
feature_columns = [
    "anciennete_mois", "region", "type_client", "mode_paiement",
    "canal_acquisition", "smartphone_flag", "arpu_moyen_fcfa",
    "prix_forfait_mensuel_fcfa", "quota_forfait_voix_min",
    # ... toutes vos features dans l'ordre
]

joblib.dump(feature_columns, "models/churn/features.pkl")
joblib.dump(scaler, "models/churn/scaler.pkl")
joblib.dump(model, "models/churn/model.pkl")
```

> **Important** : l'ordre dans `features.pkl` doit être identique à l'ordre des colonnes
> utilisé lors de l'entraînement. Le backend recoupe cet ordre avec les colonnes de la table ML.

### 5.3 Chargement au démarrage

`model_loader.py` charge les 3 fichiers au démarrage de l'API :

```python
# Extrait de model_loader.py
def load_all(self):
    for case in ("churn", "segmentation", "fraude"):
        model   = joblib.load(f"models/{case}/model.pkl")
        scaler  = joblib.load(f"models/{case}/scaler.pkl")
        features = joblib.load(f"models/{case}/features.pkl")
        # stockés en mémoire pour être réutilisés à chaque appel /run
```

Si un fichier est absent, l'API démarre quand même mais retourne une erreur 503
si vous appelez `/run` pour ce cas.

---

## 6. Les routes API

### Dashboard

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/dashboard/overview` | KPIs globaux (compteurs, taux) |
| GET | `/api/dashboard/churn-by-region` | Taux de churn par région |
| GET | `/api/dashboard/fraude-by-type` | Taux de fraude par type de transaction |

### Churn

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/churn/stats` | Total, churned, ARPU moyen, taux |
| GET | `/api/churn/by-region` | Distribution du churn par région |
| GET | `/api/churn/predictions?page=1&size=50&churn_flag=1` | Liste paginée |
| GET | `/api/churn/client/{client_id}` | Données d'un client |
| POST | `/api/churn/run` | Lance la prédiction ML |

### Fraude

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/fraude/stats` | Total, frauduleuses, montant moyen |
| GET | `/api/fraude/by-type` | Distribution par type de transaction |
| GET | `/api/fraude/predictions?fraude_flag=1` | Liste paginée |
| GET | `/api/fraude/transaction/{id}` | Données d'une transaction |
| POST | `/api/fraude/run` | Lance la détection ML |

### Segmentation

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/segmentation/stats` | Total, répartition par région/type |
| GET | `/api/segmentation/predictions?region=0` | Liste paginée |
| GET | `/api/segmentation/client/{client_id}` | Données d'un client |
| POST | `/api/segmentation/run` | Lance le clustering ML |

### Import Excel

| Méthode | Route | Description |
|---------|-------|-------------|
| POST | `/api/import/{table_name}` | Upload .xlsx → insertion en base |
| GET | `/api/import/template/{table_name}` | Colonnes attendues |

### Système

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/health` | Statut de l'API et des modèles chargés |
| GET | `/docs` | Documentation interactive Swagger |

---

## 7. Démarrage pas à pas

### Prérequis

- Python 3.11+
- PostgreSQL 14+
- La base de données créée avec le script SQL fourni

### Installation

```bash
# 1. Créer et activer l'environnement virtuel
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer la base de données
copy .env.example .env
# Editez .env et renseignez DATABASE_URL
```

### Configuration `.env`

```env
DATABASE_URL=postgresql+asyncpg://postgres:votre_mdp@localhost:5432/moov_africa_db
SYNC_DATABASE_URL=postgresql+psycopg2://postgres:votre_mdp@localhost:5432/moov_africa_db
CORS_ORIGINS=http://localhost:3000
```

### Déposer les modèles

```
models/
├── churn/
│   ├── model.pkl       ← obligatoire pour POST /api/churn/run
│   ├── scaler.pkl
│   └── features.pkl
├── fraude/
│   ├── model.pkl
│   ├── scaler.pkl
│   └── features.pkl
└── segmentation/
    ├── model.pkl
    ├── scaler.pkl
    └── features.pkl
```

### Lancer l'API

```bash
python uvicorn app.main:app --reload --port 8000
```

L'API est disponible sur `http://localhost:8000`
La documentation Swagger sur `http://localhost:8000/docs`

---

## 8. Flux complet d'utilisation

Voici l'ordre logique d'utilisation de la plateforme du début à la fin :

```
┌─────────────────────────────────────────────────────────────────┐
│  1. IMPORT DES DONNÉES BRUTES (via l'interface ou l'API)        │
│                                                                 │
│   dim_forfait → dim_client → dim_agent                          │
│   fact_conso_mensuelle → fact_evenement_service_client          │
│   fact_transaction_agent → sample_target_churn                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. PREPROCESSING (votre script Python externe)                 │
│                                                                 │
│   - Agréger fact_conso_mensuelle (moyennes sur 12 mois)         │
│   - Joindre dim_client + dim_forfait                            │
│   - Encoder les variables catégorielles                         │
│   - Calculer les features dérivées (fraude)                     │
│   → Insérer dans les tables : churn, fraude, segmentation       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. PRÉDICTION ML (via l'interface ou POST /run)                │
│                                                                 │
│   POST /api/churn/run        → churn_flag mis à jour            │
│   POST /api/fraude/run       → fraude_flag mis à jour           │
│   POST /api/segmentation/run → segments calculés                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. VISUALISATION (frontend Next.js)                            │
│                                                                 │
│   Dashboard → KPIs globaux                                      │
│   Page Churn → liste des clients avec churn_flag                │
│   Page Fraude → liste des transactions suspectes                │
│   Page Segmentation → profils clients                           │
└─────────────────────────────────────────────────────────────────┘
```

### Vérifier que tout fonctionne

```bash
# Statut général et modèles chargés
curl http://localhost:8000/health

# Réponse attendue
{
  "status": "ok",
  "modeles": {
    "churn": true,
    "segmentation": true,
    "fraude": true
  }
}
```

---

*Documentation générée pour Moov Africa Togo — Plateforme ML Analytics v1.0*
