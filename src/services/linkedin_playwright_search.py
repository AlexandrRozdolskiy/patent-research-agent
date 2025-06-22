# src/services/linkedin_playwright_search.py - LinkedIn Profile Discovery using Playwright

import asyncio
import re
from typing import Dict, List, Optional
import time
import random
from playwright.async_api import async_playwright, Browser, Page
from services.openai_service import OpenAIService # Import the service
import json

class LinkedInPlaywrightSearchService:
    def __init__(self, browser_context=None, openai_service: OpenAIService = None):
        """
        Initialize LinkedIn search service using Playwright
        
        Args:
            browser_context: Optional existing browser context to reuse
            openai_service: An instance of the OpenAIService
        """
        self.browser_context = browser_context
        self.page = None
        self.openai_service = openai_service
    
    async def __aenter__(self):
        """Async context manager entry"""
        if not self.browser_context:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.browser_context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US'
            )
        
        self.page = await self.browser_context.new_page()

        # If openai_service is not provided, create a new one.
        if not self.openai_service:
            try:
                self.openai_service = OpenAIService()
                print("✓ LinkedInPlaywrightSearchService created its own OpenAI Service instance.")
            except ValueError as e:
                print(f"⚠️ WARNING: Could not initialize OpenAI Service within Playwright service: {e}")
                self.openai_service = None

        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.page:
            await self.page.close()
        if not self.browser_context:
            if self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
    
    async def search_people(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for people using search engines with Playwright
        
        Args:
            query: Search query (name, company, etc.)
            limit: Maximum number of results
            
        Returns:
            List of people profiles with LinkedIn URLs
        """
        if not self.page:
            raise Exception("Service not initialized. Use async context manager.")
        
        if not self.openai_service:
            raise Exception("OpenAI Service is not available to the Playwright Search Service.")
        
        try:
            # Using only Bing and the specific query format as requested
            search_engines = [
                {'engine': 'bing', 'url': 'https://www.bing.com/search'},
            ]

            query_variations = [
                f'{query} linkedin',
                f'{query} {self._extract_key_terms(self.current_patent_title)} linkedin'
            ] if hasattr(self, 'current_patent_title') and self.current_patent_title else [f'{query} linkedin']

            for engine in search_engines:
                for i, q_variation in enumerate(query_variations):
                    try:
                        print(f"   Trying {engine['engine']} search with query: {q_variation}")
                        
                        # More robust search flow: navigate, fill, and submit
                        await self.page.goto(engine['url'], wait_until='domcontentloaded', timeout=20000)
                        
                        # Handle consent pop-ups first
                        await self._handle_consent_popups()

                        # Fill the search box and submit
                        search_box_selector = 'textarea[name="q"]'
                        await self.page.wait_for_selector(search_box_selector, timeout=10000)
                        search_box = self.page.locator(search_box_selector).first
                        await search_box.fill(q_variation)
                        
                        # Wait for navigation after pressing Enter. This is crucial.
                        await asyncio.gather(
                            self.page.wait_for_load_state('domcontentloaded', timeout=15000),
                            search_box.press('Enter')
                        )
                        
                        # Save a debug screenshot of the results page
                        screenshot_path = f"debug_{engine['engine']}_results_{i}.png"
                        await self.page.screenshot(path=screenshot_path)
                        print(f"   Saved debug screenshot to {screenshot_path}")

                        # Extract structured search results from the page
                        search_results = await self._extract_search_results_data()

                        if not search_results:
                            print("   Could not extract any search results from the page.")
                            continue

                        # Send the structured data to OpenAI for analysis
                        print(f"   Sending {len(search_results)} search results to OpenAI for analysis...")
                        ai_result = await self.openai_service.analyze_links_for_linkedin_url(search_results, query)
                        print(f"   AI Analysis Result: {ai_result}")

                        if ai_result and ai_result.get('linkedin_url'):
                            profile = {
                                'linkedin_url': ai_result['linkedin_url'],
                                'name': query,
                                'title': ai_result.get('reasoning'), # Use reasoning as title
                            }
                            return [profile]
                        else:
                            print(f"   AI did not find a relevant profile. Reasoning: {ai_result.get('reasoning')}")
                            
                    except Exception as e:
                        print(f"   {engine['engine']} search failed for query '{q_variation}': {e}")
                        screenshot_path = f"debug_{engine['engine']}_failure.png"
                        await self.page.screenshot(path=screenshot_path)
                        print(f"   Saved failure screenshot to {screenshot_path}")
                        continue
            
            return []
                
        except Exception as e:
            print(f"Error in search: {e}")
            return []
    
    async def _handle_consent_popups(self):
        """Handles common consent pop-ups on search engines."""
        consent_selectors = [
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Reject all")',
            'button:has-text("Alle akzeptieren")', # German for "Accept all"
            '[aria-label="Accept all"]',
            '[aria-label="Reject all"]',
            '#L2AGLb', # Google's "I agree" button ID in some regions
        ]
        for selector in consent_selectors:
            try:
                button = self.page.locator(selector).first
                if await button.is_visible(timeout=2500):
                    print(f"   Consent button found with selector '{selector}', clicking it...")
                    await button.click()
                    await self.page.wait_for_load_state('networkidle', timeout=5000)
                    print("   Consent button clicked.")
                    return # Exit after clicking one
            except Exception:
                # Selector not found or not visible, which is expected
                continue

    def _build_query_string(self, params: Dict) -> str:
        """Build query string from parameters"""
        import urllib.parse
        return urllib.parse.urlencode(params)
    
    async def _extract_search_results_data(self) -> List[Dict]:
        """Extracts all links from the page and sends them to the AI for analysis."""
        print("   Extracting ALL links from page for AI analysis...")
        
        # This script grabs every link on the page, letting the AI do the filtering.
        results = await self.page.evaluate("""() => {
            const all_links = [];
            document.querySelectorAll('a').forEach(link => {
                if (link.href && link.innerText) {
                    all_links.push({
                        url: link.href,
                        title: link.innerText.trim(),
                        snippet: '' // Snippet is less critical when AI analyzes the full list
                    });
                }
            });
            return all_links;
        }""")
        
        print(f"   Extracted {len(results)} total links from the page.")
        
        # Log the extracted search results to a file for debugging
        try:
            with open("search_results_log.json", "w") as f: # Overwrite with the latest search
                f.write(f"--- New Search at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                json.dump(results, f, indent=2)
                f.write("\n\n")
            print("   Successfully logged all extracted links to search_results_log.json")
        except Exception as e:
            print(f"   Failed to log search results to file: {e}")

        return results

    async def _extract_linkedin_profiles(self, limit: int) -> List[Dict]:
        """This method is now deprecated but kept for compatibility."""
        # The primary logic has moved to _extract_search_results_data and AI analysis
        return []
    
    def _extract_name_from_title(self, title: str) -> str:
        """Extract name from LinkedIn profile title"""
        if not title:
            return ''
        
        # LinkedIn titles usually have format: "Name - Title at Company | LinkedIn"
        if ' - ' in title:
            return title.split(' - ')[0].strip()
        elif ' | LinkedIn' in title:
            return title.split(' | LinkedIn')[0].strip()
        else:
            return title.strip()
    
    async def find_linkedin_profiles(self, inventor_data: List[Dict]) -> List[Dict]:
        """
        Find LinkedIn profiles for multiple inventors using Playwright search
        
        Args:
            inventor_data: List of inventor dictionaries
            
        Returns:
            Enriched inventor data with LinkedIn information
        """
        results = []
        
        for inventor in inventor_data:
            print(f"🔍 Searching for: {inventor.get('name', 'Unknown')}")
            
            # Store patent title for query generation if available
            self.current_patent_title = inventor.get('patent_title')

            try:
                # The search_people method now handles query variations internally
                profiles = await self.search_people(inventor.get('name', ''), limit=5)

                best_match = None
                best_score = 0
                
                for profile in profiles:
                    score = self._calculate_match_score(profile, inventor)
                    if score > best_score:
                        best_score = score
                        best_match = profile
                
                if best_match:
                    results.append({
                        **inventor,
                        'linkedin_url': best_match.get('linkedin_url'),
                        'linkedin_found': True,
                        'match_score': best_score,
                        'match_reasoning': best_match.get('title')
                    })
                else:
                    results.append({**inventor, 'linkedin_found': False})

            except Exception as e:
                print(f"   An error occurred while searching for {inventor.get('name')}: {e}")
                results.append({**inventor, 'linkedin_found': False, 'error': str(e)})
            
            finally:
                # Clean up context for next inventor
                if hasattr(self, 'current_patent_title'):
                    del self.current_patent_title
        
        return results
    
    def _generate_search_queries(self, inventor: Dict) -> List[str]:
        """
        DEPRECATED: This logic is now integrated into the `search_people` method.
        This method is kept for reference but is no longer called.
        """
        # ... (previous implementation can be removed or kept for reference)
        name = inventor.get('name', '').strip()
        company = inventor.get('company', '').strip()
        patent_title = inventor.get('patent_title', '').strip()
        
        queries = [f'"{name}" linkedin']
        if company:
            queries.append(f'"{name}" "{company}" linkedin')
        
        if patent_title:
            key_terms = self._extract_key_terms(patent_title)
            if key_terms:
                queries.append(f'"{name}" {key_terms} linkedin')
        
        return queries
    
    def _extract_key_terms(self, patent_title: str) -> str:
        """
        Extracts key technical terms from a patent title.
        """
        # Remove common words and keep technical terms
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'system', 'method', 'apparatus', 'device'}
        
        words = patent_title.lower().split()
        key_words = [word for word in words if word not in common_words and len(word) > 3]
        
        return ' '.join(key_words[:3])  # Return top 3 key terms
    
    def _calculate_match_score(self, profile: Dict, inventor: Dict) -> float:
        """Calculate how well a profile matches the inventor"""
        score = 0.0
        
        # Name matching
        profile_name = profile.get('name', '').lower()
        inventor_name = inventor.get('name', '').lower()
        
        if profile_name == inventor_name:
            score += 0.8
        elif inventor_name in profile_name:
            score += 0.6
        elif self._name_similarity(profile_name, inventor_name) > 0.8:
            score += 0.7
        
        # Company matching
        profile_company = profile.get('company', '').lower()
        company = inventor.get('company', '').lower()
        
        if company and company in profile_company:
            score += 0.2
        elif company and profile_company in company:
            score += 0.2
        
        return min(score, 1.0)
    
    def _name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names"""
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)


# Test function
async def test_linkedin_playwright_search():
    """Test LinkedIn search service using Playwright"""
    
    async with LinkedInPlaywrightSearchService() as service:
        test_inventors = [
            {
                'name': 'Elon Musk',
                'company': 'Tesla',
                'patent_title': 'Electric vehicle technology'
            },
            {
                'name': 'Tim Cook',
                'company': 'Apple',
                'patent_title': 'Mobile device interface'
            }
        ]
        
        print("🔍 Testing Playwright LinkedIn search...")
        print("=" * 50)
        
        results = await service.find_linkedin_profiles(test_inventors)
        
        for result in results:
            print(f"\n📋 Results for: {result['name']}")
            print(f"✅ LinkedIn Found: {result.get('linkedin_found', False)}")
            print(f"🔗 LinkedIn URL: {result.get('linkedin_url', 'Not found')}")
            print(f"🎯 Confidence: {result.get('match_score', 0):.2f}")
            
            if result.get('linkedin_profile'):
                profile = result['linkedin_profile']
                print(f"📝 Title: {profile.get('title', 'N/A')}")
                print(f"🏢 Company: {profile.get('company', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(test_linkedin_playwright_search()) 