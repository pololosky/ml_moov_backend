from sqlalchemy import String, Integer, Boolean, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class DimForfait(Base):
    __tablename__ = "dim_forfait"

    forfait_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    nom_forfait: Mapped[str] = mapped_column(String(100), nullable=False)
    type_forfait: Mapped[str] = mapped_column(String(20), nullable=False)
    segment_cible: Mapped[str | None] = mapped_column(String(30))
    prix_mensuel_fcfa: Mapped[int] = mapped_column(Integer, default=0)
    quota_voix_min: Mapped[int] = mapped_column(Integer, default=0)
    quota_sms: Mapped[int] = mapped_column(Integer, default=0)
    quota_data_mo: Mapped[int] = mapped_column(Integer, default=0)
    is_actif: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    clients: Mapped[list["DimClient"]] = relationship("DimClient", back_populates="forfait")
