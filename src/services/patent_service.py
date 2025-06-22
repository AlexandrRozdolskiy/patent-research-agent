import asyncio
from playwright.async_api import async_playwright, Page
import re
from typing import List, Dict, Optional
import time
import json
from services.cache_service import CacheService

class PatentService:
    def __init__(self):
        self.uspto_search_url = "https://ppubs.uspto.gov/pubwebapp/static/pages/ppubsbasic.html"
        self.browser = None
        self.context = None
        self.cache_service = CacheService()
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        self.context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def extract_patent_data(self, patent_number: str) -> Dict:
        """Extract patent data using Playwright automation with caching"""
        try:
            clean_number = self._clean_patent_number(patent_number)
            
            # Check cache first
            cached_data = self.cache_service.get_patent_data(clean_number)
            if cached_data:
                print(f"Using cached data for patent {clean_number}")
                return cached_data
            
            # Try USPTO search
            data = await self._search_uspto_with_playwright(clean_number)
            
            if not data or not data.get('inventors'):
                # Fallback to mock data for demo
                data = self._use_mock_data(clean_number)
            
            # Cache the result
            self.cache_service.set_patent_data(clean_number, data)
                
            return data
            
        except Exception as e:
            print(f"Error extracting patent data: {e}")
            return self._use_mock_data(patent_number)
    
    def _clean_patent_number(self, patent_number: str) -> str:
        """Standardize patent number to its core numeric part for searching."""
        # Find all sequences of digits
        numbers = re.findall(r'\\d+', patent_number)
        if numbers:
            # Heuristic: The longest sequence of digits is usually the main patent number.
            # This handles cases like 'US10123456B2' -> '10123456'
            return max(numbers, key=len)
        # Fallback for cases with no digits, though unlikely for a patent number.
        return patent_number.strip()
    
    async def _search_uspto_with_playwright(self, patent_number: str) -> Optional[Dict]:
        """Use Playwright to search USPTO database"""
        if not self.context:
            raise Exception("Browser context not initialized. Use async context manager.")
        
        page = None
        try:
            page = await self.context.new_page()
            
            # Navigate to USPTO basic search page
            await page.goto(self.uspto_search_url, wait_until='domcontentloaded', timeout=30000)

            # Use the specific ID selector from the provided HTML
            search_input_selector = "#quickLookupTextInput"
            await page.wait_for_selector(search_input_selector, timeout=15000)
            search_input = page.locator(search_input_selector)
            
            # Clear and enter patent number
            await search_input.fill(patent_number)
            
            # Use the specific ID selector for the search button
            await page.locator("#quickLookupSearchBtn").click()
            
            # Wait for results to load, then scroll the results table into view
            results_table_selector = "#searchResults"
            await page.wait_for_selector(results_table_selector, timeout=15000)
            await page.locator(results_table_selector).scroll_into_view_if_needed()
            await page.wait_for_timeout(1000)  # Give time for rendering after scroll
            
            # Extract patent information from results page
            patent_data = await self._extract_from_results_page(page, patent_number)
            
            await page.close()
            return patent_data
            
        except Exception as e:
            print(f"Playwright search failed for '{patent_number}': {e}")
            if page:
                await page.screenshot(path=f'debug_screenshot_failed_{patent_number}.png')
            return None
    
    async def _extract_from_results_page(self, page: Page, patent_number: str) -> Dict:
        """Extract patent details from USPTO results page"""
        try:
            # First, check if the page indicates that no records were found.
            no_records_locator = page.locator("text='No records found'")
            try:
                await no_records_locator.wait_for(timeout=2000)
                print(f"No records found for patent {patent_number}.")
                return {
                    'patent_number': patent_number,
                    'title': 'No results found',
                    'inventors': [],
                    'publication_date': None,
                    'source': 'uspto_playwright',
                }
            except Exception:
                # This is expected if results are found.
                pass

            results_table_selector = "#searchResults"
            await page.wait_for_selector(results_table_selector, timeout=5000)
            
            # Find the first result row in the table body
            first_row = page.locator(f"{results_table_selector} tbody tr:first-child")
            await first_row.wait_for(timeout=5000)
            
            # Extract data from the cells of the first row based on column order
            cells = first_row.locator("td")
            title = await cells.nth(3).inner_text()
            inventors_text = await cells.nth(4).inner_text()
            publication_date = await cells.nth(5).inner_text()

            # Clean up inventor text, assuming "Last; First" format
            inventors = []
            has_et_al = 'et al.' in inventors_text
            cleaned_inventors_text = inventors_text.replace(' et al.', '').strip()
            parts = [p.strip() for p in cleaned_inventors_text.split(';') if p.strip()]
            
            if len(parts) >= 2:
                inventors.append(f"{parts[1]} {parts[0]}") # Reorder to "First Last"
            elif parts:
                inventors.append(parts[0])

            # Filter out any remaining "et al." or similar placeholder text
            filtered_inventors = []
            for inventor in inventors:
                inventor_clean = inventor.strip()
                if inventor_clean.lower() not in ['et al.', 'et al', 'and others', 'others'] and len(inventor_clean.split()) >= 2:
                    filtered_inventors.append(inventor_clean)
            
            inventors = filtered_inventors

            await page.screenshot(path=f'debug_screenshot_{patent_number}.png')
            
            return {
                'patent_number': patent_number,
                'title': title,
                'inventors': inventors,
                'publication_date': publication_date,
                'source': 'uspto_playwright',
            }
            
        except Exception as e:
            print(f"Error extracting from results page: {e}")
            return {
                'patent_number': patent_number,
                'title': '',
                'inventors': [],
                'source': 'uspto_playwright_failed',
                'error': str(e)
            }
    
    def _extract_inventors_from_text(self, text: str) -> List[str]:
        """This function is no longer the primary method for extraction but is kept as a potential fallback."""
        inventors = []
        patterns = [
            r'\s([A-Z][A-Za-z,\s]+et al\.)\s+\d{4}-\d{2}-\d{2}',
            r'Inventor[s]?:?\s*([^;]+(?:;[^;]+)*)',
            r'(?:Inventor|Applicant)[s]?:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            for m in matches:
                # Basic cleaning, can be improved
                cleaned_name = m.replace('et al.', '').strip()
                inventors.append(cleaned_name)
        
        return list(dict.fromkeys(inventors))
    
    def _extract_title_from_text(self, text: str) -> str:
        """This function is no longer the primary method for extraction but is kept as a potential fallback."""
        match = re.search(r'Preview PDF Text\s+(.*?)\s+[A-Z][a-z]+,', text)
        if match:
            return match.group(1).strip()
        
        return "Title not found"
    
    def _use_mock_data(self, patent_number: str) -> Dict:
        """Fallback to realistic mock data for demonstration"""
        mock_patents = {
            'US10123456B2': {
                'title': 'Method and system for artificial intelligence-based data processing',
                'inventors': ['John Smith', 'Sarah Johnson', 'Michael Chen'],
                'assignee': 'Tech Innovations Inc.'
            },
            '10123456': {
                'title': 'Method and system for artificial intelligence-based data processing',
                'inventors': ['John Smith', 'Sarah Johnson', 'Michael Chen'],
                'assignee': 'Tech Innovations Inc.'
            },
            'US9876543B1': {
                'title': 'Advanced machine learning algorithm for pattern recognition',
                'inventors': ['Emily Davis', 'Robert Wilson'],
                'assignee': 'AI Research Corp'
            },
            '9876543': {
                'title': 'Advanced machine learning algorithm for pattern recognition',
                'inventors': ['Emily Davis', 'Robert Wilson'],
                'assignee': 'AI Research Corp'
            },
            'US11234567A1': {
                'title': 'Automated system for digital content analysis',
                'inventors': ['David Brown', 'Lisa Martinez', 'James Taylor'],
                'assignee': 'Digital Solutions LLC'
            }
        }
        
        # Return mock data or generate realistic fake data
        if patent_number in mock_patents:
            data = mock_patents[patent_number].copy()
        else:
            # Generate realistic mock data for any patent number
            inventor_names = [
                ['John Doe', 'Jane Smith'],
                ['Michael Johnson', 'Sarah Wilson', 'David Chen'],
                ['Emily Rodriguez', 'James Taylor'],
                ['Lisa Anderson', 'Robert Martinez', 'Jennifer Davis'],
                ['Christopher Lee', 'Amanda Thompson']
            ]
            
            import random
            random.seed(hash(patent_number))  # Consistent results for same patent
            selected_inventors = random.choice(inventor_names)
            
            data = {
                'title': f'Advanced Technical System and Method for Innovation ({patent_number})',
                'inventors': selected_inventors,
                'assignee': 'Innovation Technologies LLC'
            }
        
        data.update({
            'patent_number': patent_number,
            'source': 'mock_data'
        })
        
        return data


# Synchronous wrapper for easy testing
class PatentServiceSync:
    def __init__(self):
        self.service = PatentService()
    
    def extract_patent_data(self, patent_number: str) -> Dict:
        """Synchronous wrapper for patent extraction"""
        async def _extract():
            async with PatentService() as service:
                return await service.extract_patent_data(patent_number)
        
        return asyncio.run(_extract())


# Test function
async def test_patent_extraction():
    test_patents = [
        '9876543', '7479949', '5960411', '6285999', '9311703', 
        '10232250', '10089093', '8396204', '7763011', '8868375', '10000772'
    ]
    
    print(f"{'Patent':<15} | {'Source':<20} | {'Inventors':<40} | {'Title'}")
    print("-" * 120)

    async with PatentService() as service:
        for patent in test_patents:
            data = await service.extract_patent_data(patent)
            
            inventors_str = ", ".join(data.get('inventors', []))
            title_str = data.get('title', 'N/A')
            source_str = data.get('source', 'unknown')
            
            # Truncate strings to fit in the table
            inventors_display = (inventors_str[:37] + '...') if len(inventors_str) > 40 else inventors_str
            title_display = (title_str[:50] + '...') if len(title_str) > 50 else title_str
            
            print(f"{patent:<15} | {source_str:<20} | {inventors_display:<40} | {title_display}")


# Synchronous test for quick validation
def test_sync():
    service = PatentServiceSync()
    result = service.extract_patent_data("US10123456B2")
    print("Sync test result:", result)


if __name__ == "__main__":
    # Run async test
    asyncio.run(test_patent_extraction())
    
    # Or run sync test
    # test_sync() 