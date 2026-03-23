from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    profile_image = Column(String(500), nullable=True)
    credits = Column(Float, default=0.0)
    password_changes_this_month = Column(Integer, default=0)
    password_change_month = Column(Integer, nullable=True)
    password_change_year = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    slots = relationship("BotSlot", back_populates="owner", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class BotSlot(Base):
    __tablename__ = "bot_slots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    slot_number = Column(Integer, nullable=False)
    slot_name = Column(String(100), default="")
    iq_email = Column(String(100), nullable=True)
    iq_password = Column(String(255), nullable=True)
    investment_amount = Column(Float, default=10.0)
    trade_amount = Column(Float, default=5.0)
    profit_target = Column(Float, default=100.0)
    loss_limit = Column(Float, default=50.0)
    asset = Column(String(50), default="EURUSD-OTC")
    timeframe = Column(Integer, default=60)
    status = Column(String(20), default="inactive")
    current_balance = Column(Float, default=0.0)
    current_profit = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    win_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="slots")
    trade_results = relationship("TradeResult", back_populates="slot", cascade="all, delete-orphan")


class TradeResult(Base):
    __tablename__ = "trade_results"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(Integer, ForeignKey("bot_slots.id"), nullable=False)
    asset = Column(String(50))
    direction = Column(String(10))
    amount = Column(Float)
    result = Column(String(10))
    profit_loss = Column(Float, default=0.0)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    slot = relationship("BotSlot", back_populates="trade_results")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(255), nullable=True)
    status = Column(String(20), default="pending")
    reference_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
