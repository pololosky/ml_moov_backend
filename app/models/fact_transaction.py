from sqlalchemy import String, BigInteger, Boolean, TIMESTAMP, Numeric, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class FactTransactionAgent(Base):
    __tablename__ = "fact_transaction_agent"

    transaction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_agent.agent_id"), nullable=False)
    date_heure: Mapped[str] = mapped_column(TIMESTAMP, nullable=False)
    type_transaction: Mapped[str] = mapped_column(String(30), nullable=False)
    montant_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    msisdn_benef_hash: Mapped[str | None] = mapped_column(String(64))
    zone_logique: Mapped[str] = mapped_column(String(10), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    solde_avant_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    solde_apres_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    nb_tx_24h: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ecart_zone_habituelle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inserted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    agent: Mapped["DimAgent"] = relationship("DimAgent", back_populates="transactions")
    features_fraude: Mapped["FeaturesFraude | None"] = relationship("FeaturesFraude", back_populates="transaction", uselist=False)
    predictions_fraude: Mapped[list["PredictionFraude"]] = relationship("PredictionFraude", back_populates="transaction")
