"""
BLOC B — Tables features ML.
Construites automatiquement depuis les tables sources via des fonctions/triggers PostgreSQL.
Inputs prêts à l'emploi pour les modèles .pkl (encodages entiers).
"""
from sqlalchemy import String, Integer, SmallInteger, BigInteger, Boolean, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database import Base


class FeaturesChurn(Base):
    """
    Sources : dim_client + dim_forfait + AVG(fact_conso_mensuelle) + COUNT/AVG(fact_evenement)
    1 ligne par client.
    needs_retraining = TRUE → trigger posé quand les données sources changent.
    """
    __tablename__ = "features_churn"

    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), primary_key=True)

    # Démographie encodée (LabelEncoder)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[int] = mapped_column(SmallInteger, nullable=False)           # 0=Grand Lome … 5=Savanes
    type_client: Mapped[int] = mapped_column(SmallInteger, nullable=False)      # 0=Particulier|1=PME|2=Corporate
    mode_paiement: Mapped[int] = mapped_column(SmallInteger, nullable=False)    # 0=Prepaid|1=Postpaid
    canal_acquisition: Mapped[int] = mapped_column(SmallInteger, nullable=False)# 0=App…4=Agent
    smartphone_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0|1
    arpu_moyen_fcfa: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Forfait
    forfait_id: Mapped[str] = mapped_column(String(10), nullable=False)
    prix_forfait_mensuel_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_forfait_voix_min: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_forfait_sms: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_data_mo: Mapped[int] = mapped_column(Integer, nullable=False)

    # Moyennes conso 12 mois
    nb_appels_sortants_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    duree_voix_out_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    duree_voix_in_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    nb_sms_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    volume_data_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    nb_recharges_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    montant_recharge_moy: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    nb_jours_actifs_moy: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    solde_moy: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    nb_tx_flooz_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)

    # Comptages événements
    nb_evenements_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_reclamations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_demandes_resiliation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nb_non_resolu: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delai_resolution_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    satisfaction_moy: Mapped[float] = mapped_column(Numeric(6, 4), default=0, nullable=False)

    # Métadonnées
    computed_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    needs_retraining: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="features_churn")


class FeaturesSegmentation(Base):
    """
    Sources : dim_client + dim_forfait + AVG(fact_conso_mensuelle)
    (identique à FeaturesChurn sans les événements)
    """
    __tablename__ = "features_segmentation"

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
    voix_out_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    voix_in_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    sms_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    data_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    nb_recharges_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    recharge_montant_moy: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    jours_actifs_moy: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    solde_moy: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tx_flooz_moy: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    computed_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())
    needs_retraining: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client: Mapped["DimClient"] = relationship("DimClient", back_populates="features_segmentation")


class FeaturesFraude(Base):
    """
    Sources : fact_transaction_agent + dim_agent + feature engineering.
    Calculée immédiatement à l'INSERT d'une nouvelle transaction (trigger).
    """
    __tablename__ = "features_fraude"

    transaction_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fact_transaction_agent.transaction_id"), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(20), nullable=False)

    # Transaction encodée
    type_transaction: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Recharge…4=Achat forfait
    montant_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    zone_logique: Mapped[int] = mapped_column(Integer, nullable=False)           # Z115 → 115
    canal: Mapped[int] = mapped_column(SmallInteger, nullable=False)             # 0=POS|1=USSD|2=App agent
    solde_avant_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    solde_apres_fcfa: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    nb_tx_24h: Mapped[int] = mapped_column(Integer, nullable=False)
    ecart_zone_habituelle: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0|1

    # Agent encodé
    type_agent: Mapped[int] = mapped_column(SmallInteger, nullable=False)        # 0=Detaillant|1=Master|2=Sous-distributeur
    region: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    plafond_journalier_fcfa: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    anciennete_mois: Mapped[int] = mapped_column(Integer, nullable=False)

    # Features dérivées (feature engineering)
    depassement_plafond: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ratio_montant_plafond: Mapped[float] = mapped_column(Numeric(12, 8), default=0, nullable=False)
    ratio_montant_solde: Mapped[float] = mapped_column(Numeric(12, 8), default=0, nullable=False)
    variation_solde: Mapped[float] = mapped_column(Numeric(16, 2), default=0, nullable=False)
    agent_recent: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)  # 1 si ancienneté < 3 mois

    computed_at: Mapped[str | None] = mapped_column(TIMESTAMP, server_default=func.now())

    transaction: Mapped["FactTransactionAgent"] = relationship("FactTransactionAgent", back_populates="features_fraude")
    predictions: Mapped[list["PredictionFraude"]] = relationship("PredictionFraude", back_populates="features")
