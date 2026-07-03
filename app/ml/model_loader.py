"""
Chargement des modèles ML pré-entraînés depuis le dossier models/.
Structure attendue :
  models/
    churn/
      model.pkl
      scaler.pkl
      features.pkl
    segmentation/
      model.pkl
      scaler.pkl
      features.pkl
    fraude/
      model.pkl
      scaler.pkl
      features.pkl
"""
import joblib
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).parent.parent.parent / "models"


def _load(case: str, filename: str) -> Any:
    path = MODELS_DIR / case / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier manquant : {path}. "
            f"Déposez votre fichier '{filename}' dans models/{case}/"
        )
    return joblib.load(path)


class MLModels:
    """Conteneur singleton pour tous les modèles chargés au démarrage."""

    def __init__(self):
        self.churn_model = None
        self.churn_scaler = None
        self.churn_features: list[str] = []

        self.segmentation_model = None
        self.segmentation_scaler = None
        self.segmentation_features: list[str] = []

        self.fraude_model = None
        self.fraude_scaler = None
        self.fraude_features: list[str] = []

    def load_all(self):
        for case in ("churn", "segmentation", "fraude"):
            try:
                model = _load(case, "model.pkl")
                scaler = _load(case, "scaler.pkl")
                features = _load(case, "features.pkl")
                setattr(self, f"{case}_model", model)
                setattr(self, f"{case}_scaler", scaler)
                setattr(self, f"{case}_features", features)
                print(f"[ML] Modèle '{case}' chargé ({len(features)} features)")
            except FileNotFoundError as e:
                print(f"[ML] AVERTISSEMENT : {e}")


# Instance globale partagée entre les routes
ml_models = MLModels()
