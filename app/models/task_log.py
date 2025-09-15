from sqlalchemy import Column, DateTime, Enum, ForeignKey, BigInteger, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from db import Base


class TaskStatus(enum.Enum):
    pending = "pending"
    in_progress = "in progress"
    completed = "completed"


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(TaskStatus, name="tasklogstatus_enum", values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<TaskLog(id={self.id}, task_id={self.task_id}, action={self.action})>"

