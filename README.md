# Moov Africa Togo — Backend FastAPI

## Installation

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Configuration

```bash
copy .env.example .env
# Editez .env avec votre DATABASE_URL PostgreSQL
```

## Déposer les modèles ML

```
models/
  churn/
    model.pkl       ← votre modèle entraîné
    scaler.pkl      ← votre scaler
    features.pkl    ← liste des noms de features (dans l'ordre)
  segmentation/
    model.pkl
    scaler.pkl
    features.pkl
  fraude/
    model.pkl
    scaler.pkl
    features.pkl
```

Consultez le fichier `DEPOSER_ICI.md` dans chaque dossier pour les détails.

## Lancement

```bash
uvicorn app.main:app --reload --port 8000
```

Documentation interactive : http://localhost:8000/docs

## Endpoints principaux

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/dashboard/overview` | KPIs globaux |
| GET | `/api/churn/stats` | Stats churn |
| GET | `/api/churn/predictions` | Liste prédictions churn |
| POST | `/api/churn/run` | Lance la prédiction churn |
| GET | `/api/segmentation/stats` | Répartition segments |
| POST | `/api/segmentation/run` | Lance le clustering |
| GET | `/api/fraude/stats` | Stats fraude |
| GET | `/api/fraude/predictions` | Liste transactions suspectes |
| POST | `/api/fraude/run` | Lance la détection fraude |
| POST | `/api/import/{table}` | Import fichier Excel |
| GET | `/health` | État des modèles chargés |
