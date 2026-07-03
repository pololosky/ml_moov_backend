from sqlalchemy import String, Integer, Boolean, Date, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
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

    forfait: Mapped["DimForfait"] = relationship("DimForfait", back_populates="clients")
    consommations: Mapped[list["FactConsoMensuelle"]] = relationship("FactConsoMensuelle", back_populates="client")
    evenements: Mapped[list["FactEvenementServiceClient"]] = relationship("FactEvenementServiceClient", back_populates="client")
    churn_data: Mapped["Churn | None"] = relationship("Churn", back_populates="client", uselist=False)
    segmentation_data: Mapped["Segmentation | None"] = relationship("Segmentation", back_populates="client", uselist=False)
