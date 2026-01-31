from sqlmodel import SQLModel, create_engine, Session
from threading import Lock

# Use a file-based SQLite database
sqlite_file_name = "insti.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# check_same_thread=False is needed for SQLite with multi-threading
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

# Simple singleton for thread-safe access if needed
_db_lock = Lock()

def create_db_and_tables():
    """Initializes the database schema."""
    SQLModel.metadata.create_all(engine)

def get_session():
    """Yields a database session."""
    with Session(engine) as session:
        yield session
