from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class SelectorSchema(BaseModel):
    base_selector: str = Field(..., description="The CSS selector for the repeating container element (e.g. 'div.card', 'tr.row')")
    fields: Dict[str, str] = Field(..., description="Map of field names to their relative CSS selectors (e.g. {'name': 'h3', 'link': 'a.profile'}")

class FacultyDetail(BaseModel):
    email: Optional[str] = Field(None, description="The faculty member's email address")
    research_interests: List[str] = Field(default_factory=list, description="List of research areas or interests")
    publications: List[str] = Field(default_factory=list, description="Latest publications (max 5)")
    image_url: Optional[str] = Field(None, description="Profile image URL")

class FallbackProfileSchema(BaseModel):
    name: str
    profile_url: str
    title: Optional[str] = None
