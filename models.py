from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

class ProfessorProfile(BaseModel):
    name: str
    title: str
    email: Optional[str] = None
    profile_url: str
    research_interests: List[str] = Field(default_factory=list)
    publications: List[str] = Field(default_factory=list)
    lab: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

class PlanStep(BaseModel):
    action: Literal['goto', 'click', 'type', 'extract_details', 'loop', 'go_back']
    selector: Optional[str] = None
    value: Optional[str] = None
    # For 'loop' action, this will contain the steps to execute for each item
    steps: Optional[List['PlanStep']] = None 
    # For 'extract_details', this defines what to extract
    model_definition: Optional[Dict[str, Any]] = Field(default_factory=dict)

# This allows the recursive definition of PlanStep within itself
PlanStep.model_rebuild()

class ScrapingPlan(BaseModel):
    university_name: str
    faculty_start_url: str
    steps: List[PlanStep] = Field(default_factory=list)
