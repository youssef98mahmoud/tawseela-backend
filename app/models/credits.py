"""Integer-credit settlement records; no public credit issuance API."""
import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, CheckConstraint, UniqueConstraint
from app.core.database import Base
from .base import TimeStampMixin

class PlatformLedger(Base):
    __tablename__ = 'platform_ledger'
    id = Column(Integer, primary_key=True)
    commission_balance = Column(Integer, nullable=False, default=0)
    __table_args__ = (CheckConstraint('id = 1'), CheckConstraint('commission_balance >= 0'))

class CreditTransfer(Base, TimeStampMixin):
    __tablename__ = 'credit_transfers'
    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    ride_id = Column(String, ForeignKey('rides.id'), nullable=False)
    passenger_id = Column(String, ForeignKey('users.id'), nullable=False)
    kind = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('ride_id', 'passenger_id', 'kind'),
                     CheckConstraint('amount > 0'), CheckConstraint("kind IN ('escrow', 'release')"))
