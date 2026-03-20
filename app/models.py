from sqlalchemy import Column, Integer, String
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    planning_login = Column(String, nullable=False)
    planning_password = Column(String, nullable=False)
    ics_path = Column(String, nullable=True)

    status = Column(String, default="pending")