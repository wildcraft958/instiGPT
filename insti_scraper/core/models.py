from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class SelectorSchema(BaseModel):
    base_selector: str = Field(..., description="The CSS selector for the repeating container element (e.g. 'div.card', 'tr.row')")
    fields: Dict[str, str] = Field(..., description="Map of field names to their relative CSS selectors (e.g. {'name': 'h3', 'link': 'a.profile'}")

class FacultyDetail(BaseModel):
    name: Optional[str] = Field(None, description="Full name of the faculty member")
    designation: Optional[str] = Field(None, description="Academic title or designation (e.g. Professor, Assistant Professor)")
    email: Optional[str] = Field(None, description="The faculty member's email address")
    phone: Optional[str] = Field(None, description="Office phone number")
    office_address: Optional[str] = Field(None, description="Physical office location/room number")
    
    research_interests: List[str] = Field(default_factory=list, description="List of research areas or interests")
    publications: List[str] = Field(default_factory=list, description="Latest publications (max 5)")
    
    social_links: Dict[str, str] = Field(default_factory=dict, description="Social profiles (LinkedIn, Twitter, ResearchGate, etc.)")
    image_url: Optional[str] = Field(None, description="Profile image URL")
    
    # Metadata
    google_scholar_url: Optional[str] = None
    google_scholar_data: Optional[Dict] = None

class FallbackProfileSchema(BaseModel):
    name: str
    profile_url: str
    title: Optional[str] = None
