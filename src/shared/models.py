"""SQLAlchemy ORM models shared between MCP and Controller services."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OdooConnection(Base):
    __tablename__ = "odoo_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet-encrypted credential value
    credential: Mapped[str] = mapped_column(Text, nullable=False)
    # "api_key" or "password"
    credential_type: Mapped[str] = mapped_column(String(20), nullable=False, default="api_key")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    # "untested", "ok", "error"
    status: Mapped[str] = mapped_column(String(20), default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    request_logs: Mapped[list["RequestLog"]] = relationship(back_populates="connection")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # bcrypt hash of the full key
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # first 8 chars of the plaintext key, shown in UI
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    request_logs: Mapped[list["RequestLog"]] = relationship(back_populates="api_key")


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("odoo_connections.id", ondelete="SET NULL"), nullable=True
    )
    api_key_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    # "success" or "error"
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    connection: Mapped["OdooConnection | None"] = relationship(back_populates="request_logs")
    api_key: Mapped["ApiKey | None"] = relationship(back_populates="request_logs")
