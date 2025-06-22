# src/main.py - Updated FastAPI with Playwright integration

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import os
import asyncio
import time
import json
from dotenv import load_dotenv
from services.patent_service import PatentService
from services.openai_service import OpenAIService
from services.cache_service import CacheService
from services.linkedin_playwright_search import LinkedInPlaywrightSearchService
from models.contact import ContactAnalysisRequest, ContactAnalysisResponse, ContactLead, InventorContact
from typing import Optional, List, Dict
import pandas as pd
from io import BytesIO

load_dotenv()

app = FastAPI(title="Patent Research Agent", version="1.0.0")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global services for efficiency
patent_service_context = None
cache_service = None
openai_service = None
linkedin_search_service = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global patent_service_context, cache_service, openai_service, linkedin_search_service

    # 1. Initialize OpenAI Service first
    try:
        openai_service = OpenAIService()
        print("✓ OpenAI Service Initialized.")
    except ValueError as e:
        openai_service = None
        print(f"⚠️ WARNING: OpenAI Service failed to initialize: {e}")

    # 2. Initialize Patent Service (which includes browser context)
    patent_service_context = PatentService()
    await patent_service_context.__aenter__()
    cache_service = CacheService()
    
    # 3. Initialize LinkedIn Search Service, passing the other services to it
    linkedin_search_service = LinkedInPlaywrightSearchService(
        browser_context=patent_service_context.context,
        openai_service=openai_service
    )
    await linkedin_search_service.__aenter__()
    
    print("✓ Patent Research Agent started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup services on shutdown"""
    global patent_service_context, linkedin_search_service
    if linkedin_search_service:
        await linkedin_search_service.__aexit__(None, None, None)
    if patent_service_context:
        await patent_service_context.__aexit__(None, None, None)
    print("✓ Services cleaned up")

class PatentRequest(BaseModel):
    patent_number: str

class MultiplePatentsRequest(BaseModel):
    patent_numbers: List[str]

class InventorAnalysisRequest(BaseModel):
    inventor_name: str
    patent_number: str
    patent_title: str

class InventorInfo(BaseModel):
    name: str
    email: str | None = None
    linkedin: str | None = None
    confidence_score: float = 0.0
    contact_lead: Optional[ContactLead] = None
    
class PatentResponse(BaseModel):
    patent_number: str
    title: str
    inventors: list[InventorInfo]
    processing_time: float
    source: str

class PatentTableRow(BaseModel):
    patent_number: str
    inventors: str
    publication_date: str
    description: str
    status: str = "pending"

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main HTML interface"""
    try:
        with open("static/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="""
        <html>
            <body>
                <h1>Patent Research Agent</h1>
                <p>API is running! Static files not found.</p>
                <p>Try: <a href="/docs">/docs</a> for API documentation</p>
            </body>
        </html>
        """)

@app.post("/research", response_model=PatentResponse)
async def research_patent(request: PatentRequest, analyze_contacts: bool = False):
    """Research patent and optionally enrich with contact analysis."""
    start_time = time.time()
    
    try:
        if not request.patent_number.strip():
            raise HTTPException(status_code=400, detail="Patent number cannot be empty")
        
        patent_data = await patent_service_context.extract_patent_data(request.patent_number)
        
        inventors_info = []
        if analyze_contacts and openai_service and patent_data.get('source') != 'mock_data':
            # Perform contact analysis
            analysis_data = {
                'patent_number': patent_data.get('patent_number'),
                'title': patent_data.get('title'),
                'inventors': patent_data.get('inventors', []),
                'assignee': patent_data.get('assignee')
            }
            contact_analysis = await openai_service.analyze_inventor_contacts(analysis_data)
            
            # Create a map of inventor names to their analysis
            analysis_map = {item['name']: item for item in contact_analysis.get('inventors', [])}

            for inventor_name in patent_data.get('inventors', []):
                lead_data = analysis_map.get(inventor_name)
                contact_lead = ContactLead(**lead_data) if lead_data else None
                inventors_info.append(InventorInfo(
                    name=inventor_name,
                    confidence_score=contact_lead.confidence_score if contact_lead else 0.0,
                    contact_lead=contact_lead
                ))
        else:
            # Basic info without contact analysis
            for inventor_name in patent_data.get('inventors', []):
                inventors_info.append(InventorInfo(
                    name=inventor_name,
                    confidence_score=0.8 if patent_data.get('source') == 'uspto_playwright' else 0.5
                ))

        processing_time = time.time() - start_time
        
        return PatentResponse(
            patent_number=request.patent_number,
            title=patent_data.get('title', 'Unknown Title'),
            inventors=inventors_info,
            processing_time=round(processing_time, 2),
            source=patent_data.get('source', 'unknown')
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        print(f"Error processing patent {request.patent_number}: {e}")
        
        return PatentResponse(
            patent_number=request.patent_number,
            title="Error: Could not retrieve patent data",
            inventors=[],
            processing_time=round(processing_time, 2),
            source="error"
        )

@app.post("/research-multiple")
async def research_multiple_patents(request: MultiplePatentsRequest):
    """Research multiple patents with real-time updates via SSE"""
    
    async def generate_updates():
        """Generate SSE updates for patent processing"""
        for i, patent_number in enumerate(request.patent_numbers):
            try:
                # Send status update
                yield f"data: {json.dumps({'type': 'status', 'patent': patent_number, 'message': 'Processing...', 'index': i})}\n\n"
                
                # Process patent
                start_time = time.time()
                patent_data = await patent_service_context.extract_patent_data(patent_number)
                processing_time = time.time() - start_time
                
                # Create table row data
                inventors_list = patent_data.get('inventors', [])
                # Filter out "et al." and similar placeholder text
                filtered_inventors = []
                for inventor in inventors_list:
                    inventor_clean = inventor.strip()
                    if inventor_clean.lower() not in ['et al.', 'et al', 'and others', 'others']:
                        filtered_inventors.append(inventor_clean)
                
                inventors_str = ", ".join(filtered_inventors)
                table_row = PatentTableRow(
                    patent_number=patent_number,
                    inventors=inventors_str,
                    publication_date=patent_data.get('publication_date', 'Unknown'),
                    description=patent_data.get('title', 'Unknown Title'),
                    status="completed"
                )
                
                # Send completion update
                yield f"data: {json.dumps({'type': 'complete', 'patent': patent_number, 'data': table_row.dict(), 'processing_time': round(processing_time, 2), 'index': i})}\n\n"
                
                # Small delay to prevent overwhelming the client
                await asyncio.sleep(0.1)
                
            except Exception as e:
                error_row = PatentTableRow(
                    patent_number=patent_number,
                    inventors="Error",
                    publication_date="Error",
                    description=f"Error: {str(e)}",
                    status="error"
                )
                yield f"data: {json.dumps({'type': 'error', 'patent': patent_number, 'data': error_row.dict(), 'error': str(e), 'index': i})}\n\n"
        
        # Send completion signal
        yield f"data: {json.dumps({'type': 'finished', 'total': len(request.patent_numbers)})}\n\n"
    
    return StreamingResponse(
        generate_updates(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

@app.post("/analyze-inventor")
async def analyze_single_inventor(request: InventorAnalysisRequest):
    """Analyze a single inventor for contact information"""
    if not openai_service:
        raise HTTPException(status_code=503, detail="OpenAI Service is not available. Please check API key.")
    
    try:
        # Filter out non-person names like "et al."
        inventor_name = request.inventor_name.strip()
        if inventor_name.lower() in ['et al.', 'et al', 'and others', 'others']:
            raise HTTPException(status_code=400, detail="Cannot analyze 'et al.' or similar placeholder names")
        
        # Check if it's not empty
        if not inventor_name:
            raise HTTPException(status_code=400, detail="Inventor name cannot be empty")
        
        # Check cache first
        cached_analysis = cache_service.get_ai_analysis(inventor_name, request.patent_number)
        if cached_analysis:
            return {"cached": True, "data": cached_analysis}
        
        # Perform analysis
        analysis_data = {
            'patent_number': request.patent_number,
            'title': request.patent_title,
            'inventors': [inventor_name],
            'assignee': None
        }
        
        contact_analysis = await openai_service.analyze_inventor_contacts(analysis_data)
        
        if "error" in contact_analysis:
            raise HTTPException(status_code=500, detail=contact_analysis["error"])
        
        # Extract the analysis for this specific inventor
        inventor_analysis = None
        for inventor in contact_analysis.get("inventors", []):
            # Make comparison more robust to handle minor name variations from the AI
            ai_name = inventor.get("name", "").lower()
            requested_name = inventor_name.lower()
            if requested_name in ai_name or ai_name in requested_name:
                inventor_analysis = inventor
                break
        
        if not inventor_analysis:
            raise HTTPException(status_code=404, detail="Inventor analysis not found")

        # --- New: Perform LinkedIn Search ---
        print(f"🔬 Performing LinkedIn search for {inventor_name}...")
        if linkedin_search_service:
            inventor_for_linkedin = {
                'name': inventor_name,
                'company': inventor_analysis.get('company', ''), # Use company from AI analysis if available
                'patent_title': request.patent_title,
            }
            linkedin_results = await linkedin_search_service.find_linkedin_profiles([inventor_for_linkedin])
            
            if linkedin_results and linkedin_results[0].get('linkedin_found'):
                found_url = linkedin_results[0].get('linkedin_url')
                print(f"✅ Found LinkedIn URL: {found_url}")
                inventor_analysis['linkedin_url'] = found_url
            else:
                print("❌ LinkedIn profile not found.")
                inventor_analysis['linkedin_url'] = None
        else:
            print("⚠️ LinkedIn Search Service not available.")
            inventor_analysis['linkedin_url'] = None
        # --- End of LinkedIn Search ---

        # Ensure the name is always in the analysis for the frontend.
        if 'name' not in inventor_analysis or not inventor_analysis['name']:
            inventor_analysis['name'] = inventor_name

        # Cache the combined result
        cache_service.set_ai_analysis(inventor_name, request.patent_number, inventor_analysis)
        
        return {"cached": False, "data": inventor_analysis}
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Error analyzing inventor {request.inventor_name}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during analysis: {str(e)}")

@app.post("/analyze-contacts", response_model=ContactAnalysisResponse)
async def analyze_contacts(request: ContactAnalysisRequest):
    """Analyzes patent data to generate contact-finding strategies for each inventor."""
    if not openai_service:
        raise HTTPException(status_code=503, detail="OpenAI Service is not available. Please check API key.")

    try:
        analysis_result = await openai_service.analyze_inventor_contacts(request.dict())
        
        if "error" in analysis_result:
            raise HTTPException(status_code=500, detail=analysis_result["error"])

        enriched_inventors = []
        for inventor_analysis in analysis_result.get("inventors", []):
            contact_lead = ContactLead(**inventor_analysis)
            enriched_inventors.append(InventorContact(
                name=inventor_analysis["name"],
                patent_number=request.patent_number,
                patent_title=request.title,
                contact_lead=contact_lead
            ))
        
        return ContactAnalysisResponse(enriched_inventors=enriched_inventors)

    except Exception as e:
        print(f"Error in /analyze-contacts: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during contact analysis.")

@app.post("/export-excel")
async def export_to_excel(request: Request):
    """Export patent data to Excel file with AI analysis"""
    try:
        data = await request.json()
        table_data = data.get('table_data', [])
        
        if not table_data:
            raise HTTPException(status_code=400, detail="No data to export")
        
        # Clean up the main patent data for export
        patents_for_export = []
        for row in table_data:
            patents_for_export.append({
                'Patent Number': row.get('patent_number'),
                'Inventors': row.get('inventors'),
                'Publication Date': row.get('publication_date'),
                'Title': row.get('description'),
                'Status': row.get('status')
            })
        df_patents = pd.DataFrame(patents_for_export)
        
        # Collect AI analysis data
        ai_analysis_data = []
        for row_data in table_data:
            patent_number = row_data.get('patent_number')
            if patent_number:
                # Get patent data to find inventors
                try:
                    patent_data = await patent_service_context.extract_patent_data(patent_number)
                    inventors_list = patent_data.get('inventors', [])
                    
                    # Filter out "et al." and similar
                    filtered_inventors = []
                    for inventor in inventors_list:
                        inventor_clean = inventor.strip()
                        if inventor_clean.lower() not in ['et al.', 'et al', 'and others', 'others']:
                            filtered_inventors.append(inventor_clean)
                    
                    # Check cache for each inventor
                    for inventor in filtered_inventors:
                        cached_analysis = cache_service.get_ai_analysis(inventor, patent_number)
                        if cached_analysis:
                            ai_analysis_data.append({
                                'Patent Number': patent_number,
                                'Patent Title': row_data.get('description', ''),
                                'Inventor Name': inventor,
                                'AI Confidence Score': f"{cached_analysis.get('confidence_score', 0) * 100:.0f}%",
                                'Email Suggestions': ', '.join(cached_analysis.get('email_suggestions', [])),
                                'LinkedIn Profile': cached_analysis.get('linkedin_url', 'Not Found'),
                                'GitHub Search Terms': ', '.join(cached_analysis.get('github_search_terms', [])),
                                'Search Strategy': cached_analysis.get('search_strategy', ''),
                                'Analysis Date': 'Cached'
                            })
                except Exception as e:
                    print(f"Error getting AI analysis for {patent_number}: {e}")
        
        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Write patent data sheet
            df_patents.to_excel(writer, sheet_name='Patent Data', index=False)
            
            # Write AI analysis sheet if there's data
            if ai_analysis_data:
                df_ai = pd.DataFrame(ai_analysis_data)
                df_ai.to_excel(writer, sheet_name='AI Analysis', index=False)
        
        output.seek(0)
        
        return StreamingResponse(
            BytesIO(output.getvalue()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=patent_data_with_ai_analysis.xlsx"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating Excel file: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "browser_ready": patent_service_context is not None,
        "openai_service_ready": openai_service is not None,
        "cache_service_ready": cache_service is not None,
        "version": "1.0.0"
    }

@app.get("/cache-stats")
async def get_cache_stats():
    """Get cache statistics"""
    if not cache_service:
        raise HTTPException(status_code=503, detail="Cache service not available")
    
    return cache_service.get_cache_stats()

@app.post("/clear-cache")
async def clear_cache(cache_type: str = "all"):
    """Clear cache"""
    if not cache_service:
        raise HTTPException(status_code=503, detail="Cache service not available")
    
    cache_service.clear_cache(cache_type)
    return {"message": f"Cache cleared: {cache_type}"}

@app.get("/test/{patent_number}")
async def test_patent(patent_number: str):
    """Quick test endpoint for debugging"""
    try:
        start_time = time.time()
        data = await patent_service_context.extract_patent_data(patent_number)
        processing_time = time.time() - start_time
        
        return {
            "patent_number": patent_number,
            "data": data,
            "processing_time": round(processing_time, 2)
        }
    except Exception as e:
        return {"error": str(e), "patent_number": patent_number}

@app.get("/check-ai-cache/{patent_number}")
async def check_ai_cache(patent_number: str):
    """Check if AI analysis is cached for any inventors of a patent"""
    if not cache_service:
        raise HTTPException(status_code=503, detail="Cache service not available")
    
    try:
        # Get patent data to find inventors
        patent_data = await patent_service_context.extract_patent_data(patent_number)
        inventors_list = patent_data.get('inventors', [])
        
        # Filter out "et al." and similar
        filtered_inventors = []
        for inventor in inventors_list:
            inventor_clean = inventor.strip()
            if inventor_clean.lower() not in ['et al.', 'et al', 'and others', 'others']:
                filtered_inventors.append(inventor_clean)
        
        # Check cache for each inventor
        cached_inventors = []
        for inventor in filtered_inventors:
            if cache_service.get_ai_analysis(inventor, patent_number):
                cached_inventors.append(inventor)
        
        return {
            "patent_number": patent_number,
            "has_cached_analysis": len(cached_inventors) > 0,
            "cached_inventors": cached_inventors,
            "total_inventors": len(filtered_inventors)
        }
        
    except Exception as e:
        print(f"Error checking AI cache for {patent_number}: {e}")
        return {
            "patent_number": patent_number,
            "has_cached_analysis": False,
            "cached_inventors": [],
            "total_inventors": 0,
            "error": str(e)
        }

class LinkedInSearchRequest(BaseModel):
    inventors: List[Dict]

@app.post("/find-linkedin-profiles")
async def find_linkedin_profiles(request: LinkedInSearchRequest):
    """Find LinkedIn profiles for inventors using DuckDuckGo search"""
    if not linkedin_search_service:
        raise HTTPException(status_code=503, detail="LinkedIn search service not available")
    
    try:
        print(f"🔍 Searching LinkedIn profiles for {len(request.inventors)} inventors")
        
        # Find LinkedIn profiles
        results = await linkedin_search_service.find_linkedin_profiles(request.inventors)
        
        return {
            "success": True,
            "results": results,
            "total_searched": len(request.inventors),
            "found_count": sum(1 for r in results if r.get('linkedin_found', False))
        }
        
    except Exception as e:
        print(f"Error finding LinkedIn profiles: {e}")
        raise HTTPException(status_code=500, detail=f"Error finding LinkedIn profiles: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, reload=False)  # reload=False because of browser context
