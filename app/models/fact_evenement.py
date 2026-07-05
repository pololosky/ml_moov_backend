from sqlalchemy import String, Integer, TIMESTAMP, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class FactEvenementServiceClient(Base):
    __tablename__ = "fact_evenement_service_client"

    evenement_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), nullable=False)
    date_evenement: Mapped[str] = mapped_column(TIMESTAMP, nullable=False)
    canal: Mapped[str] = mapped_column(String(30), nullable=False)
    type_evenement: Mapped[str] = mapped_column(String(40), nullable=False)
    categorie: Mapped[str] = mapped_column(String(30), nullable=False)
    statut_resolution: Mapped[str] = mapped_column(String(20), nullable=False)
    delai_resolution_h: Mapped[float | None] = mapped_column(Numeric(8, 2))
    satisfaction_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    inserted_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="evenements")
