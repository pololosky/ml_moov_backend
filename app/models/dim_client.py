from sqlalchemy import String, Integer, Boolean, Date, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class DimClient(Base):
    __tablename__ = "dim_client"

    client_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    msisdn_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    date_activation: Mapped[str] = mapped_column(Date, nullable=False)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[str] = mapped_column(String(30), nullable=False)
    type_client: Mapped[str] = mapped_column(String(20), nullable=False)
    mode_paiement: Mapped[str] = mapped_column(String(20), nullable=False)
    forfait_id: Mapped[str] = mapped_column(String(10), ForeignKey("dim_forfait.forfait_id"), nullable=False)
    canal_acquisition: Mapped[str] = mapped_column(String(30), nullable=False)
    smartphone_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    arpu_moyen_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    statut_ligne: Mapped[str] = mapped_column(String(20), nullable=False)
    date_reference: Mapped[str] = mapped_column(Date, nullable=False)
    inserted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    forfait: Mapped["DimForfait"] = relationship("DimForfait", back_populates="clients")
    consommations: Mapped[list["FactConsoMensuelle"]] = relationship("FactConsoMensuelle", back_populates="client")
    evenements: Mapped[list["FactEvenementServiceClient"]] = relationship("FactEvenementServiceClient", back_populates="client")
    features_churn: Mapped["FeaturesChurn | None"] = relationship("FeaturesChurn", back_populates="client", uselist=False)
    features_segmentation: Mapped["FeaturesSegmentation | None"] = relationship("FeaturesSegmentation", back_populates="client", uselist=False)
    predictions_churn: Mapped[list["PredictionChurn"]] = relationship("PredictionChurn", back_populates="client")
    predictions_segment: Mapped[list["PredictionSegment"]] = relationship("PredictionSegment", back_populates="client")
