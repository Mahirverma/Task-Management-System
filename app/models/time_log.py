from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from db import Base


class TimeLog(Base):
    __tablename__ = "time_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    hours = Column(Numeric(5, 2), nullable=False)  # 999.99 max
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # --- Relationships ---
    task = relationship("Task", back_populates="time_logs")
    user = relationship("User", back_populates="time_logs")

    __table_args__ = (
        Index("idx_timelog_task", "task_id"),
        Index("idx_timelog_user", "user_id"),
    )

    def __repr__(self):
        return f"<TimeLog(id={self.id}, task_id={self.task_id}, user_id={self.user_id}, duration={self.duration_minutes})>"
