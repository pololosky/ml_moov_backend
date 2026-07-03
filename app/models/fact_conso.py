from sqlalchemy import String, Integer, Boolean, Date, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class FactConsoMensuelle(Base):
    __tablename__ = "fact_conso_mensuelle"
    __table_args__ = (UniqueConstraint("client_id", "mois"),)

    conso_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), nullable=False)
    mois: Mapped[str] = mapped_column(Date, nullable=False)
    nb_appels_sortants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duree_voix_out_min: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    duree_voix_in_min: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    nb_sms_envoyes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    volume_data_mo: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    nb_recharges: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    montant_recharge_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    nb_jours_actifs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solde_moyen_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    nb_tx_flooz: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    roaming_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # colonne1 supprimée — erreur de conception, sans utilité

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="consommations")
