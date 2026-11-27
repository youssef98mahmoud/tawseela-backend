from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from app.core.database import Base


class Membership(Base):
    __tablename__ = 'memberships'
    user_id = Column(String, ForeignKey('users.id'), primary_key=True)
    customer_id = Column(String, unique=True, nullable=True)
    subscription_id = Column(String, unique=True, nullable=True)
    checkout_key = Column(String, nullable=False)
    checkout_started = Column(Integer, nullable=False)
    price_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default='none')
    paid_until = Column(Integer, nullable=False, default=0)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)


class BillingEvent(Base):
    __tablename__ = 'billing_events'
    id = Column(String, primary_key=True)
    processed_at = Column(Integer, nullable=False)
