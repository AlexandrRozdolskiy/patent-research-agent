# src/services/linkedin_service.py - LinkedIn Profile Discovery with Playwright

import asyncio
import re
from playwright.async_api import Page, Browser
from typing import Dict, List, Optional, Tuple
import time
import urllib.parse

class LinkedInProfileFinder:
    def __init__(self, browser_context=None):
        self.browser_context = browser_context
        self.rate_limit_delay = 2  # Seconds between searches
        self.max_search_attempts = 3
        
    async def find_linkedin_profiles(self, inventor_data: List[Dict]) -> List[Dict]:
        """
        Find LinkedIn profiles for multiple inventors
        Returns enriched inventor data with LinkedIn URLs
        """
        results = []
        
        for inventor in inventor_data:
            print(f"🔍 Searching LinkedIn for: {inventor.get('name', 'Unknown')}")
            
            try:
                linkedin_url = await self._find_single_profile(inventor)
                
                # Add LinkedIn data to inventor info
                inventor_result = inventor.copy()
                inventor_result['linkedin_url'] = linkedin_url
                inventor_result['linkedin_found'] = linkedin_url is not None
                
                results.append(inventor_result)
                
                # Rate limiting - be respectful to LinkedIn
                await asyncio.sleep(self.rate_limit_delay)
                
            except Exception as e:
                print(f"❌ LinkedIn search failed for {inventor.get('name')}: {e}")
                inventor_result = inventor.copy()
                inventor_result['linkedin_url'] = None
                inventor_result['linkedin_found'] = False
                inventor_result['linkedin_error'] = str(e)
                results.append(inventor_result)
        
        return results
    
    async def _find_single_profile(self, inventor: Dict) -> Optional[str]:
        """Find LinkedIn profile for a single inventor"""
        
        name = inventor.get('name', '').strip()
        if not name or name == 'Unknown':
            return None
        
        # Get search queries from OpenAI analysis or generate basic ones
        search_queries = inventor.get('linkedin_search_queries', [])
        if not search_queries:
            search_queries = self._generate_basic_search_queries(inventor)
        
        # Try each search query until we find a good match
        for query in search_queries[:self.max_search_attempts]:
            try:
                profile_url = await self._search_linkedin_for_query(query, inventor)
                if profile_url:
                    print(f"✅ Found LinkedIn profile: {profile_url}")
                    return profile_url
                    
                # Small delay between search attempts
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"⚠️  Search query '{query}' failed: {e}")
                continue
        
        print(f"❌ No LinkedIn profile found for {name}")
        return None
    
    async def _search_linkedin_for_query(self, query: str, inventor: Dict) -> Optional[str]:
        """Search LinkedIn with a specific query and extract profile URL"""
        
        if not self.browser_context:
            raise Exception("Browser context not available")
        
        page = await self.browser_context.new_page()
        
        try:
            # Set up the page to look more human-like
            await page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            })
            
            # Navigate to LinkedIn people search
            encoded_query = urllib.parse.quote(query)
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}"
            
            print(f"🔍 Searching: {query}")
            await page.goto(search_url, wait_until='networkidle', timeout=30000)
            
            # Wait for search results to load
            await page.wait_for_timeout(3000)
            
            # Check if we need to handle authentication/captcha
            page_content = await page.content()
            if 'Sign in' in page_content or 'Join LinkedIn' in page_content:
                print("⚠️  LinkedIn requires authentication - switching to alternative method")
                return await self._try_direct_profile_url(inventor, page)
            
            # Extract profile URLs from search results
            profile_links = await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                    return links
                        .map(link => link.href)
                        .filter(href => href.includes('/in/') && !href.includes('?'))
                        .slice(0, 5); // Top 5 results
                }
            """)
            
            if not profile_links:
                print("❌ No profile links found in search results")
                return None
            
            # Validate and rank the found profiles
            best_match = await self._find_best_profile_match(profile_links, inventor, page)
            return best_match
            
        finally:
            await page.close()
    
    async def _find_best_profile_match(self, profile_urls: List[str], inventor: Dict, page: Page) -> Optional[str]:
        """Analyze found profiles to find the best match"""
        
        inventor_name = inventor.get('name', '').lower()
        company = inventor.get('company', '').lower()
        patent_title = inventor.get('patent_title', '').lower()
        
        scored_profiles = []
        
        for url in profile_urls[:3]:  # Check top 3 profiles
            try:
                score = await self._score_profile_match(url, inventor_name, company, patent_title, page)
                scored_profiles.append((url, score))
                
                # If we find a very high confidence match, return it immediately
                if score > 0.8:
                    return url
                    
            except Exception as e:
                print(f"❌ Error scoring profile {url}: {e}")
                continue
        
        # Return the highest scoring profile if any have reasonable confidence
        if scored_profiles:
            best_profile = max(scored_profiles, key=lambda x: x[1])
            if best_profile[1] > 0.5:  # Minimum confidence threshold
                return best_profile[0]
        
        return None
    
    async def _score_profile_match(self, profile_url: str, inventor_name: str, company: str, patent_title: str, page: Page) -> float:
        """Score how well a LinkedIn profile matches the inventor"""
        
        try:
            # Navigate to the profile (just get basic info from URL and preview)
            await page.goto(profile_url, wait_until='domcontentloaded', timeout=15000)
            await page.wait_for_timeout(2000)
            
            # Get visible profile information
            profile_info = await page.evaluate("""
                () => {
                    const getName = () => {
                        const selectors = ['h1', '.text-heading-xlarge', '.pv-text-details__left-panel h1'];
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element && element.textContent) {
                                return element.textContent.trim();
                            }
                        }
                        return '';
                    };
                    
                    const getHeadline = () => {
                        const selectors = ['.text-body-medium', '.pv-text-details__left-panel .text-body-medium'];
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element && element.textContent) {
                                return element.textContent.trim();
                            }
                        }
                        return '';
                    };
                    
                    return {
                        name: getName(),
                        headline: getHeadline(),
                        pageText: document.body.innerText.toLowerCase()
                    };
                }
            """)
            
            # Calculate match score
            score = 0.0
            
            # Name matching (most important)
            profile_name = profile_info.get('name', '').lower()
            if profile_name and inventor_name:
                name_similarity = self._calculate_name_similarity(inventor_name, profile_name)
                score += name_similarity * 0.6  # 60% weight for name match
            
            # Company matching
            page_text = profile_info.get('pageText', '')
            headline = profile_info.get('headline', '').lower()
            
            if company and (company in page_text or company in headline):
                score += 0.3  # 30% weight for company match
            
            # Technology/patent context matching
            if patent_title:
                patent_keywords = self._extract_tech_keywords(patent_title)
                for keyword in patent_keywords:
                    if keyword in page_text or keyword in headline:
                        score += 0.1  # Small bonus for tech relevance
                        break
            
            return min(score, 1.0)  # Cap at 1.0
            
        except Exception as e:
            print(f"❌ Error accessing profile {profile_url}: {e}")
            return 0.0
    
    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names"""
        
        # Clean names
        name1_clean = re.sub(r'[^\w\s]', '', name1.lower()).strip()
        name2_clean = re.sub(r'[^\w\s]', '', name2.lower()).strip()
        
        name1_parts = name1_clean.split()
        name2_parts = name2_clean.split()
        
        if not name1_parts or not name2_parts:
            return 0.0
        
        # Exact match
        if name1_clean == name2_clean:
            return 1.0
        
        # Check if all parts of the shorter name are in the longer name
        shorter = name1_parts if len(name1_parts) <= len(name2_parts) else name2_parts
        longer = name2_parts if len(name1_parts) <= len(name2_parts) else name1_parts
        
        matches = 0
        for part in shorter:
            if part in longer:
                matches += 1
        
        return matches / len(shorter) if shorter else 0.0
    
    def _extract_tech_keywords(self, patent_title: str) -> List[str]:
        """Extract relevant technology keywords from patent title"""
        
        # Common technology terms to look for
        tech_terms = [
            'algorithm', 'machine learning', 'artificial intelligence', 'neural network',
            'software', 'hardware', 'processor', 'computing', 'database', 'network',
            'wireless', 'mobile', 'internet', 'web', 'cloud', 'security', 'encryption',
            'biotech', 'pharmaceutical', 'medical', 'therapeutic', 'genetic', 'dna',
            'semiconductor', 'chip', 'circuit', 'electronic', 'optical', 'laser'
        ]
        
        patent_lower = patent_title.lower()
        found_terms = []
        
        for term in tech_terms:
            if term in patent_lower:
                found_terms.append(term)
        
        return found_terms[:3]  # Return up to 3 most relevant terms
    
    async def _try_direct_profile_url(self, inventor: Dict, page: Page) -> Optional[str]:
        """Try to access predicted LinkedIn URLs directly"""
        
        predicted_urls = inventor.get('predicted_linkedin_urls', [])
        if not predicted_urls:
            predicted_urls = self._generate_predicted_urls(inventor.get('name', ''))
        
        for url in predicted_urls[:3]:  # Try top 3 predictions
            try:
                full_url = f"https://{url}" if not url.startswith('http') else url
                
                response = await page.goto(full_url, wait_until='domcontentloaded', timeout=10000)
                
                if response and response.status == 200:
                    # Check if it's a valid profile page
                    page_content = await page.content()
                    if 'linkedin.com/in/' in page_content and 'Profile' in page_content:
                        return full_url
                        
            except Exception as e:
                print(f"❌ Direct URL check failed for {url}: {e}")
                continue
        
        return None
    
    def _generate_predicted_urls(self, name: str) -> List[str]:
        """Generate predicted LinkedIn URLs from name"""
        
        if not name:
            return []
        
        # Clean name
        clean_name = re.sub(r'[^\w\s]', '', name.lower()).strip()
        name_parts = clean_name.split()
        
        if len(name_parts) < 2:
            return []
        
        first_name = name_parts[0]
        last_name = name_parts[-1]
        
        patterns = [
            f"linkedin.com/in/{first_name}-{last_name}",
            f"linkedin.com/in/{first_name}{last_name}",
            f"linkedin.com/in/{first_name}-{last_name}-phd",
            f"linkedin.com/in/{first_name[0]}{last_name}",
            f"linkedin.com/in/{first_name}-{last_name}-1"
        ]
        
        return patterns
    
    def _generate_basic_search_queries(self, inventor: Dict) -> List[str]:
        """Generate basic search queries if none provided"""
        
        name = inventor.get('name', '')
        company = inventor.get('company', '')
        
        if not name:
            return []
        
        queries = [name]
        
        if company:
            queries.append(f"{name} {company}")
            queries.append(f'"{name}" {company}')
        
        # Add common professional terms
        queries.append(f"{name} engineer")
        queries.append(f"{name} inventor")
        
        return queries[:4]


# Integration with existing services
class EnhancedPatentService:
    """Enhanced patent service that includes LinkedIn discovery"""
    
    def __init__(self, patent_service, openai_service, browser_context):
        self.patent_service = patent_service
        self.openai_service = openai_service
        self.linkedin_finder = LinkedInProfileFinder(browser_context)
    
    async def research_patent_with_linkedin(self, patent_number: str, include_linkedin: bool = True) -> Dict:
        """Complete patent research including LinkedIn profile discovery"""
        
        # Step 1: Extract patent data
        patent_data = await self.patent_service.extract_patent_data(patent_number)
        
        # Step 2: Get OpenAI contact analysis
        if self.openai_service:
            contact_analysis = self.openai_service.analyze_inventor_contacts(patent_data)
        else:
            contact_analysis = []
        
        # Step 3: Find LinkedIn profiles if requested
        if include_linkedin and contact_analysis:
            enriched_inventors = await self.linkedin_finder.find_linkedin_profiles(contact_analysis)
        else:
            enriched_inventors = contact_analysis
        
        # Step 4: Combine all data
        result = {
            'patent_number': patent_number,
            'title': patent_data.get('title', ''),
            'inventors': enriched_inventors,
            'source': patent_data.get('source', ''),
            'linkedin_search_performed': include_linkedin,
            'total_inventors': len(enriched_inventors),
            'linkedin_found_count': sum(1 for inv in enriched_inventors if inv.get('linkedin_found', False))
        }
        
        return result


# Testing function
async def test_linkedin_finder(custom_name: str = None):
    """Test the LinkedIn finder with sample data or custom name"""
    
    # You would use your existing browser context here
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Set to True for production
        context = await browser.new_context()
        
        finder = LinkedInProfileFinder(context)
        
        # Test with custom name or sample data
        if custom_name:
            test_inventors = [
                {
                    'name': custom_name,
                    'company': 'Technology Company',
                    'patent_title': 'Innovative technology patent',
                    'linkedin_search_queries': [
                        f'{custom_name}',
                        f'{custom_name} engineer',
                        f'{custom_name} technology'
                    ]
                }
            ]
        else:
            # Default test data
            test_inventors = [
                {
                    'name': 'Steven P. Jobs',
                    'company': 'Apple Inc.',
                    'patent_title': 'Touch screen device, method, and graphical user interface',
                    'linkedin_search_queries': [
                        'Steven Jobs Apple CEO',
                        'Steve Jobs Apple founder',
                        'Steven Jobs Apple Cupertino'
                    ]
                }
            ]
        
        print(f"🔍 Testing LinkedIn finder for: {test_inventors[0]['name']}")
        results = await finder.find_linkedin_profiles(test_inventors)
        
        for result in results:
            print(f"\nInventor: {result['name']}")
            print(f"LinkedIn Found: {result.get('linkedin_found', False)}")
            print(f"LinkedIn URL: {result.get('linkedin_url', 'Not found')}")
        
        await browser.close()


if __name__ == "__main__":
    import sys
    
    # Allow command line argument for custom name
    custom_name = sys.argv[1] if len(sys.argv) > 1 else None
    
    if custom_name:
        print(f"Testing LinkedIn finder with custom name: {custom_name}")
        asyncio.run(test_linkedin_finder(custom_name))
    else:
        print("Testing LinkedIn finder with default data (Steven P. Jobs)")
        asyncio.run(test_linkedin_finder())