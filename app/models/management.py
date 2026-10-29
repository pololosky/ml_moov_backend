"""
BLOC D — Tables de gestion.
Traçabilité des runs de modèle et des imports de fichiers Excel.
"""
from sqlalchemy import String, Integer, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class ModelRun(Base):
    """
    Trace chaque exécution d'un modèle .pkl.
    Permet de savoir quelle version a produit quel résultat.
    """
    __tablename__ = "model_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cas_usage: Mapped[str] = mapped_column(String(20), nullable=False)      # 'churn'|'fraude'|'segmentation'
    modele_version: Mapped[str] = mapped_column(String(20), nullable=False) # ex: 'v1.0', 'v2.1'
    fichier_model: Mapped[str | None] = mapped_column(String(200))          # chemin relatif du .pkl
    nb_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metriques: Mapped[dict | None] = mapped_column(JSONB)                   # {'auc': 0.87, 'f1': 0.72}
    hyperparametres: Mapped[dict | None] = mapped_column(JSONB)
    run_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    run_by: Mapped[str | None] = mapped_column(String(50))                  # utilisateur ou 'system'

    predictions_churn: Mapped[list["PredictionChurn"]] = relationship("PredictionChurn", back_populates="model_run")
    predictions_fraude: Mapped[list["PredictionFraude"]] = relationship("PredictionFraude", back_populates="model_run")
    predictions_segment: Mapped[list["PredictionSegment"]] = relationship("PredictionSegment", back_populates="model_run")
    segment_definitions: Mapped[list["SegmentDefinition"]] = relationship("SegmentDefinition", back_populates="model_run")


class ImportLog(Base):
    """
    Trace chaque import de fichier Excel via le drag-and-drop du frontend.
    Permet d'auditer qui a importé quoi.
    """
    __tablename__ = "import_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fichier_source: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: 'dim_client.xlsx'
    table_cible: Mapped[str] = mapped_column(String(60), nullable=False)      # ex: 'dim_client'
    nb_lignes_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_lignes_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_lignes_err: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    statut: Mapped[str] = mapped_column(String(20), default="En cours", nullable=False)  # En cours|Succes|Erreur
    details_erreur: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    imported_by: Mapped[str | None] = mapped_column(String(50))
