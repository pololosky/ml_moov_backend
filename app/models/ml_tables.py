"""
Tables ML directes : churn, fraude, segmentation.
Ces tables contiennent les données déjà agrégées et encodées,
prêtes à être passées aux modèles de prédiction.
"""
from sqlalchemy import String, Integer, SmallInteger, BigInteger, Boolean, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Churn(Base):
    __tablename__ = "churn"

    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), primary_key=True)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    type_client: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mode_paiement: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    forfait_id: Mapped[str] = mapped_column(String(10), nullable=False)
    prix_forfait_mensuel_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_forfait_voix_min: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_forfait_sms: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_data_mo: Mapped[int] = mapped_column(Integer, nullable=False)
    canal_acquisition: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    smartphone_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    arpu_moyen_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    nb_appels_sortants_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    duree_voix_out_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    duree_voix_in_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    nb_sms_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    volume_data_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    nb_recharges_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    montant_recharge_moy: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    nb_jours_actifs_moy: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    solde_moy: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    nb_tx_flooz_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    nb_evenements_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_reclamations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_demandes_resiliation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_non_resolu: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delai_resolution_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    satisfaction_moy: Mapped[float] = mapped_column(Numeric(6, 4), default=0, nullable=False)
    churn_flag: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="churn_data")


class Fraude(Base):
    __tablename__ = "fraude"

    transaction_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fact_transaction_agent.transaction_id"), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(20), nullable=False)
    type_transaction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    montant_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    zone_logique: Mapped[int] = mapped_column(Integer, nullable=False)
    canal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    solde_avant_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    solde_apres_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    nb_tx_24h: Mapped[int] = mapped_column(Integer, nullable=False)
    ecart_zone_habituelle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    type_agent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    region: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    plafond_journalier_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    depassement_plafond: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ratio_montant_plafond: Mapped[float] = mapped_column(Numeric(12, 8), default=0, nullable=False)
    ratio_montant_solde: Mapped[float] = mapped_column(Numeric(12, 8), default=0, nullable=False)
    variation_solde: Mapped[float] = mapped_column(Numeric(16, 2), default=0, nullable=False)
    agent_recent: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    fraude_flag: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    transaction: Mapped["FactTransactionAgent"] = relationship("FactTransactionAgent", back_populates="fraude_data")


class Segmentation(Base):
    __tablename__ = "segmentation"

    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), primary_key=True)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    type_client: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mode_paiement: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    forfait_id: Mapped[str] = mapped_column(String(10), nullable=False)
    prix_mensuel_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_voix_min: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_sms: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_data_mo: Mapped[int] = mapped_column(Integer, nullable=False)
    smartphone_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    arpu_moyen_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    voix_out_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    voix_in_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    sms_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    data_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    nb_recharges_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    recharge_montant_moy: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    jours_actifs_moy: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    solde_moy: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    tx_flooz_moy: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="segmentation_data")
