from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Patent(BaseModel):
    patent_number: str = Field(..., description="USPTO patent number")
    title: str = Field(..., description="Patent title")
    inventors: List[str] = Field(default_factory=list)
    assignee: Optional[str] = None
    publication_date: Optional[datetime] = None
    source: str = Field(default="unknown")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class Inventor(BaseModel):
    name: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    company: Optional[str] = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    search_results: List[str] = Field(default_factory=list)
    
    def __str__(self):
        return f"{self.name} (confidence: {self.confidence_score:.2f})" 