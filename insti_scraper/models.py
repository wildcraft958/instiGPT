"""
Data models for the faculty scraper.

Combines SQLModel database models and Pydantic schemas into one place.
"""

from typing import List, Optional, Dict
from datetime import datetime, timezone
from sqlmodel import Field, Relationship, SQLModel, JSON, create_engine, Session
from pydantic import BaseModel
from dataclasses import dataclass, field

# =============================================================================
# Database Models (SQLModel)
# =============================================================================

class University(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    website: str
    location: Optional[str] = None
    departments: List["Department"] = Relationship(back_populates="university")


class Department(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    university_id: int = Field(foreign_key="university.id")
    url: Optional[str] = None
    university: University = Relationship(back_populates="departments")
    professors: List["Professor"] = Relationship(back_populates="department")


class Professor(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    office: Optional[str] = None
    
    profile_url: Optional[str] = None
    image_url: Optional[str] = None
    website_url: Optional[str] = None
    
    research_interests: List[str] = Field(default=[], sa_type=JSON)
    publication_summary: Optional[str] = None
    education: Optional[str] = None
    bio: Optional[str] = None
    
    # Scholar data
    google_scholar_id: Optional[str] = None
    h_index: int = Field(default=0)
    total_citations: int = Field(default=0)
    top_papers: List[str] = Field(default=[], sa_type=JSON)
    
    department_id: Optional[int] = Field(default=None, foreign_key="department.id")
    department: Optional[Department] = Relationship(back_populates="professors")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Database Connection
# =============================================================================

_engine = None

def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            "sqlite:///insti.db",
            connect_args={"check_same_thread": False}
        )
    return _engine


def init_database():
    """Initialize database tables."""
    SQLModel.metadata.create_all(get_engine())


def get_session():
    """Get a database session."""
    return Session(get_engine())


# =============================================================================
# Discovery Models
# =============================================================================

@dataclass
class DiscoveredPage:
    """A discovered faculty page."""
    url: str
    score: float = 0.0
    page_type: str = "unknown"  # 'directory', 'profile'
    source: str = "unknown"  # 'sitemap', 'search', 'crawl'
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        return self.url == other.url


@dataclass
class DiscoveryResult:
    """Result of faculty page discovery."""
    pages: List[DiscoveredPage] = field(default_factory=list)
    method: str = "none"
    
    @property
    def faculty_pages(self) -> List[DiscoveredPage]:
        return sorted(self.pages, key=lambda p: p.score, reverse=True)


# =============================================================================
# Extraction Models
# =============================================================================

@dataclass
class ExtractionResult:
    """Result of faculty extraction."""
    professors: List[Professor]
    department_name: str = "General"
    confidence: float = 0.0
    method: str = "unknown"
    
    def __post_init__(self):
        if not hasattr(self, 'metadata'):
            self.metadata = {}


# =============================================================================
# LLM Schema Models (for structured extraction)
# =============================================================================

class SelectorSchema(BaseModel):
    """CSS selector schema for page extraction."""
    base_selector: str
    fields: Dict[str, str]


class FacultyDetail(BaseModel):
    """Detailed faculty profile schema."""
    name: Optional[str] = None
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    office_address: Optional[str] = None
    research_interests: List[str] = []
    publications: List[str] = []
    social_links: Dict[str, str] = {}
    image_url: Optional[str] = None
    google_scholar_url: Optional[str] = None
