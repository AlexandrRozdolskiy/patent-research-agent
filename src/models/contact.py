from pydantic import BaseModel, Field
from typing import List, Optional

class ContactLead(BaseModel):
    """Represents a potential contact lead for an inventor."""
    email_suggestions: List[str] = Field(default_factory=list, description="Suggested email patterns.")
    linkedin_search_terms: List[str] = Field(default_factory=list, description="Targeted LinkedIn search queries.")
    github_search_terms: List[str] = Field(default_factory=list, description="Potential GitHub usernames or search terms.")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score for finding contact info (0.0 to 1.0).")
    search_strategy: str = Field(..., description="The reasoning and strategy behind the contact suggestions.")

class InventorContact(BaseModel):
    """Enriched inventor data including contact leads."""
    name: str = Field(..., description="Inventor's full name.")
    patent_number: str = Field(..., description="Associated patent number.")
    patent_title: str = Field(..., description="Title of the patent.")
    contact_lead: Optional[ContactLead] = None

class ContactAnalysisRequest(BaseModel):
    """Request model for contact analysis."""
    patent_number: str
    title: str
    inventors: List[str]
    assignee: Optional[str] = None

class ContactAnalysisResponse(BaseModel):
    """Response model for contact analysis, containing enriched inventor data."""
    enriched_inventors: List[InventorContact] = Field(default_factory=list) 