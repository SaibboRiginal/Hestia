import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

# Gets the URL from docker-compose.yml
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://hestia_admin:super_secret_local_password@localhost:5432/hestia_memory")

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency to give each API request its own secure database connection


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
