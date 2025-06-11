import os
import json # Import json for serializing/deserializing genres
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.sql import func
# No need for from sqlalchemy.dialects.postgresql import ARRAY for SQLite

# --- Database Connection Configuration for SQLite ---
# SQLite uses a file path. Conventionally, we put the database file
# in the project root or a specific data directory.
# For Docker, this file would need to be mounted as a volume.
DATABASE_FILE = "./sql_app.db" # The database file will be created here
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

# Create the SQLAlchemy engine instance
# connect_args are important for SQLite to allow multiple threads to access it
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}, # Required for SQLite with multiple threads/requests
    pool_pre_ping=True
)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declare a base class for declarative models
Base = declarative_base()

# --- Database Models ---

class Website(Base):
    """
    Represents a website from which novels are scraped (e.g., WuxiaWorld).
    """
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    url = Column(String, unique=True, nullable=False)
    # Relationship to Novels (one-to-many: one website can have many novels)
    novels = relationship("Novel", back_populates="source_website_rel")

class Novel(Base):
    """
    Represents a novel. This is the core entity that the scraper populates.
    """
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    author = Column(String, index=True)
    description = Column(Text) # Used for synopsis from scraper
    cover_image_url = Column(String)
    language = Column(String)
    is_completed = Column(Boolean, default=False)
    avg_rating = Column(Float)
    
    # Many-to-many relationship with Genre
    genres = relationship("Genre", secondary="novel_genres", back_populates="novels")

    # Foreign key to Website table
    source_website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    # Relationship to Website (many-to-one: many novels can be from one website)
    source_website_rel = relationship("Website", back_populates="novels")

    source_url = Column(String, unique=True, index=True) # URL of the novel's main page on the source website
    last_scraped_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    latest_chapter_number = Column(Integer, default=0)
    current_last_chapter_number = Column(Integer, default=0)

    # Relationships to Novel Instances and Chapters (one-to-many)
    novel_instances = relationship("NovelInstance", back_populates="novel")
    chapters = relationship("Chapter", back_populates="novel")

class NovelGenre(Base):
    """
    Association table for the many-to-many relationship between Novel and Genre.
    """
    __tablename__ = "novel_genres"
    novel_id = Column(Integer, ForeignKey("novels.id"), primary_key=True)
    genre_id = Column(Integer, ForeignKey("genres.id"), primary_key=True)

class Genre(Base):
    """
    Represents a genre for novels.
    """
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

    # Many-to-many relationship with Novel
    novels = relationship("Novel", secondary="novel_genres", back_populates="genres")

class NovelInstance(Base):
    """
    Represents a specific instance or version of a novel, if a novel exists
    on multiple sources or has different translations/versions.
    (Optional, could be simplified if only one source per novel is tracked).
    """
    __tablename__ = "novel_instances"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False)
    url = Column(String, unique=True, nullable=False) # URL of this specific instance
    version_name = Column(String, index=True) # e.g., "Official Translation", "Fan Translation"
    status = Column(String) # e.g., "Ongoing", "Completed", "Hiatus"
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    # Relationship back to Novel
    novel = relationship("Novel", back_populates="novel_instances")

class Chapter(Base):
    """
    Represents a single chapter of a novel.
    """
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False)
    title = Column(String, nullable=False)
    chapter_number = Column(Integer, index=True)
    url = Column(String, unique=True, nullable=False)
    content = Column(Text)
    published_date = Column(DateTime(timezone=True))
    # Relationship back to Novel
    novel = relationship("Novel", back_populates="chapters")


# --- Database Initialization Function ---
def create_db_and_tables():
    """
    Creates all tables defined in Base.metadata in the database.
    This function should be called only once during application startup.
    """
    print(f"Attempting to create database tables with URL: {SQLALCHEMY_DATABASE_URL}")
    try:
        Base.metadata.create_all(engine)
        print("Database tables checked/created successfully for SQLite.")
    except Exception as e:
        print(f"Error creating database tables: {e}")
        raise # Re-raise the exception after logging
def clear_all_data():
    session = SessionLocal()
    try:
        # Delete all rows from dependent tables first due to foreign key constraints
        session.query(Chapter).delete()
        session.query(NovelInstance).delete()
        session.query(NovelGenre).delete() # Clear association table first
        session.query(Genre).delete()
        session.query(Novel).delete()
        session.query(Website).delete()
        session.commit()
        print("All data cleared from the database.")
    except Exception as e:
        session.rollback()
        print(f"Error clearing data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    clear_all_data()

# Dependency to get a database session for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()