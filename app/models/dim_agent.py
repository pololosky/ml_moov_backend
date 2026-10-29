from sqlalchemy import String, Integer, Date, Numeric, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class DimAgent(Base):
    __tablename__ = "dim_agent"

    agent_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    type_agent: Mapped[str] = mapped_column(String(30), nullable=False)
    region: Mapped[str] = mapped_column(String(30), nullable=False)
    zone_logique: Mapped[str] = mapped_column(String(10), nullable=False)
    date_recrutement: Mapped[str] = mapped_column(Date, nullable=False)
    plafond_journalier_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    transactions: Mapped[list["FactTransactionAgent"]] = relationship("FactTransactionAgent", back_populates="agent")
