from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid4())


class Dealership(Base):
    __tablename__ = "dealerships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_connection: Mapped[str] = mapped_column(String(100), nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("dealership_id", "source_id", name="uq_vehicle_dealership_source"),
        CheckConstraint("year >= 1886 AND year <= 2100", name="ck_vehicle_year"),
        CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="ck_vehicle_price"),
        CheckConstraint("mileage IS NULL OR mileage >= 0", name="ck_vehicle_mileage"),
        Index("ix_vehicle_dealership_id_id", "dealership_id", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dealership_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dealerships.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    make_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    price_cents: Mapped[int | None] = mapped_column(nullable=True)
    body_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body_type_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trim: Mapped[str | None] = mapped_column(String(100), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mileage: Mapped[int | None] = mapped_column(nullable=True)
    exterior_color: Mapped[str | None] = mapped_column(String(100), nullable=True)
    drivetrain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fuel: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dealership_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dealerships.id", ondelete="RESTRICT"), nullable=False
    )
    creation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=new_uuid)
    __table_args__ = (
        Index("uq_conversation_creation", "dealership_id", "creation_id", unique=True),
    )

    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_vehicle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=True
    )
    next_message_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ChatRequest(Base):
    __tablename__ = "chat_requests"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_request_id", name="uq_chat_request_client"),
        UniqueConstraint("id", "conversation_id", name="uq_chat_request_id_conversation"),
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed', 'interrupted')",
            name="ck_chat_request_status",
        ),
        CheckConstraint(
            "(status = 'in_progress' AND terminal_http_status IS NULL "
            "AND terminal_body IS NULL) OR "
            "(status != 'in_progress' AND terminal_http_status IS NOT NULL "
            "AND terminal_body IS NOT NULL)",
            name="ck_chat_request_terminal",
        ),
        Index(
            "uq_chat_request_active_conversation",
            "conversation_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index(
            "ix_chat_request_expired",
            "lease_expires_at",
            postgresql_where=text("status = 'in_progress'"),
            sqlite_where=text("status = 'in_progress'"),
        ),
        Index(
            "ix_chat_request_completed_turns",
            "conversation_id",
            "status",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    terminal_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terminal_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    presented_vehicle_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "conversation_id"],
            ["chat_requests.id", "chat_requests.conversation_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("conversation_id", "sequence", name="uq_message_conversation_sequence"),
        UniqueConstraint("request_id", "role", name="uq_message_request_role"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
        Index("ix_message_conversation_sequence", "conversation_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
