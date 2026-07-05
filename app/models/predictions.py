"""
BLOC C — Tables résultats ML.
Chaque prédiction est conservée dans l'historique.
is_latest = TRUE pour la prédiction active affichée dans le dashboard.
Quand le backend écrit une nouvelle prédiction, il passe les anciennes à is_latest = FALSE.
"""
from sqlalchemy import String, Integer, SmallInteger, BigInteger, Boolean, Numeric, TIMESTAMP, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class PredictionChurn(Base):
    """
    Historique des prédictions churn.
    1 ligne par (client, run de modèle).
    """
    __tablename__ = "prediction_churn"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), nullable=False)
    model_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_run.id"))
    score_churn: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)   # probabilité 0.0000–1.0000
    churn_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)       # 0|1 (seuil 0.5)
    horizon_jours: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    predicted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="predictions_churn")
    model_run: Mapped["ModelRun | None"] = relationship("ModelRun", back_populates="predictions_churn")


class SegmentDefinition(Base):
    """
    Nommage manuel des segments identifiés par K-Means.
    Remplie après analyse des centroides par l'équipe Data.
    """
    __tablename__ = "segment_definition"

    segment_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # cluster K-Means (0, 1, 2…)
    label: Mapped[str] = mapped_column(String(80), nullable=False)       # ex: "Gros utilisateur Data"
    description: Mapped[str | None] = mapped_column(Text)
    couleur_hex: Mapped[str | None] = mapped_column(String(7))           # ex: '#003087'
    model_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_run.id"))
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    model_run: Mapped["ModelRun | None"] = relationship("ModelRun", back_populates="segment_definitions")
    predictions: Mapped[list["PredictionSegment"]] = relationship("PredictionSegment", back_populates="segment_def")


class PredictionSegment(Base):
    """Assignation d'un client à un segment. Historique conservé."""
    __tablename__ = "prediction_segment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), nullable=False)
    model_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_run.id"))
    segment_id: Mapped[int] = mapped_column(Integer, ForeignKey("segment_definition.segment_id"), nullable=False)
    predicted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="predictions_segment")
    model_run: Mapped["ModelRun | None"] = relationship("ModelRun", back_populates="predictions_segment")
    segment_def: Mapped["SegmentDefinition"] = relationship("SegmentDefinition", back_populates="predictions")


class PredictionFraude(Base):
    """Historique des prédictions fraude. 1 ligne par (transaction, run)."""
    __tablename__ = "prediction_fraude"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fact_transaction_agent.transaction_id"), nullable=False)
    features_fraude_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("features_fraude.transaction_id"))
    model_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_run.id"))
    score_fraude: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    fraude_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)      # 0|1
    statut: Mapped[str] = mapped_column(String(20), default="Nouvelle", nullable=False)  # Nouvelle|Traitee|Ignoree
    predicted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    transaction: Mapped["FactTransactionAgent"] = relationship("FactTransactionAgent", back_populates="predictions_fraude")
    features: Mapped["FeaturesFraude | None"] = relationship("FeaturesFraude", back_populates="predictions")
    model_run: Mapped["ModelRun | None"] = relationship("ModelRun", back_populates="predictions_fraude")
