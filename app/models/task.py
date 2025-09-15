from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, Date, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from db import Base


class TaskStatus(enum.Enum):
    pending = "pending"
    in_progress = "in progress"
    completed = "completed"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum(TaskStatus, name="taskstatus_enum"), nullable=False, default=TaskStatus.pending)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    start_date = Column(DateTime(timezone=True))
    due_date = Column(Date)
    completed_at = Column(DateTime(timezone=True))

    def __repr__(self):
        return f"<Task(uuid={self.uuid}, title={self.title}, status={self.status}, assigned_to={self.assigned_to})>"
