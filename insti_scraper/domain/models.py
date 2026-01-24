from typing import List, Optional, Dict
from datetime import datetime
from sqlmodel import Field, Relationship, SQLModel, JSON

# --- Domain Models ---

class University(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    website: str
    location: Optional[str] = None
    
    # Relationships
    departments: List["Department"] = Relationship(back_populates="university")

class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    university_id: int = Field(foreign_key="university.id")
    url: Optional[str] = None
    
    # Relationships
    university: University = Relationship(back_populates="departments")
    professors: List["Professor"] = Relationship(back_populates="department")

class Professor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    office: Optional[str] = None
    
    # Profile & Links
    profile_url: Optional[str] = Field(default=None) # Relaxed: Not unique, not required
    image_url: Optional[str] = None
    website_url: Optional[str] = None
    
    # Research
    research_interests: List[str] = Field(default=[], sa_type=JSON)
    bio: Optional[str] = None
    
    # Apollo-like Enrichment Data
    google_scholar_id: Optional[str] = None
    h_index: int = Field(default=0)
    total_citations: int = Field(default=0)
    top_papers: List[str] = Field(default=[], sa_type=JSON)
    
    # Relationships
    department_id: Optional[int] = Field(default=None, foreign_key="department.id")
    department: Optional[Department] = Relationship(back_populates="professors")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
