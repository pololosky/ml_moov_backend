from sqlalchemy import String, Integer, Date, SmallInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SampleTargetChurn(Base):
    __tablename__ = "sample_target_churn"

    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_client.client_id"), primary_key=True)
    date_reference: Mapped[str] = mapped_column(Date, nullable=False)
    horizon_jours: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    churn_flag: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    date_churn_observe: Mapped[str | None] = mapped_column(Date)
