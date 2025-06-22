import os
import openai
from typing import Dict, List
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class OpenAIService:
    def __init__(self, api_key: str = None):
        """Initializes the OpenAI service with an API key."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set.")
        openai.api_key = self.api_key

    def _build_contact_analysis_prompt(self, patent_data: Dict) -> str:
        """Builds the detailed prompt for contact analysis based on patent data."""
        patent_number = patent_data.get('patent_number', 'N/A')
        title = patent_data.get('title', 'N/A')
        assignee = patent_data.get('assignee', 'N/A')
        inventors = ", ".join(patent_data.get('inventors', []))
        
        # A simple keyword-based tech domain extraction
        tech_domain = "General"
        if any(keyword in title.lower() for keyword in ['software', 'system', 'method', 'database']):
            tech_domain = "Software/IT"
        elif any(keyword in title.lower() for keyword in ['biotech', 'medical', 'dna']):
            tech_domain = "Biotech/Medical"
        elif any(keyword in title.lower() for keyword in ['gaming', 'device', 'hardware']):
            tech_domain = "Hardware/Gaming"

        return f"""
        ANALYZE INVENTOR FOR CONTACT STRATEGY

        **Patent Information:**
        - **Patent Number:** {patent_number}
        - **Title:** {title}
        - **Assignee/Company:** {assignee}
        - **Technology Domain:** {tech_domain}
        - **Inventors:** {inventors}

        **Your Task:**
        For each inventor listed, generate a contact-finding strategy. Analyze their name, the patent's technology, and the assignee company to suggest the best ways to find their contact information.

        **Analysis Framework:**
        1.  **Name Analysis:** How common is the name? Unique names are easier to find.
        2.  **Technology Context:** A software patent suggests a strong GitHub presence. A biotech patent points towards academic papers or ResearchGate.
        3.  **Company Context:** An inventor at a large corporation (e.g., Apple) is harder to contact directly than one at a university or startup.

        **Required Output Format:**
        You MUST return a single valid JSON object. Do not include any text or formatting outside of this JSON object.
        The JSON object should have a single key "inventors", which is a list of objects. Each object in the list represents an inventor and must contain the following keys:
        - `name`: The inventor's full name.
        - `email_suggestions`: A list of 3-5 potential email patterns (e.g., "j.doe@company.com").
        - `linkedin_search_terms`: A list of 2-3 targeted search queries for LinkedIn.
        - `github_search_terms`: A list of potential GitHub usernames. Leave empty if the tech domain is not software-related.
        - `confidence_score`: A float between 0.0 and 1.0 indicating the likelihood of finding this person's contact info.
        - `search_strategy`: A brief (1-2 sentence) explanation of your reasoning.

        **Example for one inventor:**
        {{
            "name": "Lawrence Page",
            "email_suggestions": ["larry.page@google.com", "lpage@google.com", "larry@google.com"],
            "linkedin_search_terms": ["Lawrence Page Google Founder", "Larry Page Alphabet CEO"],
            "github_search_terms": [],
            "confidence_score": 0.4,
            "search_strategy": "High-profile executive, so direct contact is difficult. Focus on documented corporate history and public appearances rather than direct outreach."
        }}

        Now, analyze the provided patent information and generate the JSON output for ALL inventors listed.
        """

    async def analyze_inventor_contacts(self, patent_data: Dict) -> Dict:
        """
        Analyzes patent data to generate contact-finding strategies for each inventor.
        Returns a structured dictionary with contact leads.
        """
        prompt = self._build_contact_analysis_prompt(patent_data)
        
        try:
            # Use the async client for async operations
            async_client = openai.AsyncOpenAI(api_key=self.api_key)
            response = await async_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert contact research assistant. Your task is to analyze patent data and provide actionable strategies for finding inventor contact information in a structured JSON format."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
            )
            
            analysis_text = response.choices[0].message.content
            return json.loads(analysis_text)

        except openai.APIError as e:
            print(f"OpenAI API Error: {e}")
            return {"error": "OpenAI API error."}
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return {"error": "An unexpected error occurred."}

    async def analyze_html_for_linkedin_url(self, html_content: str, target_name: str) -> Dict:
        # This function is now deprecated in favor of analyze_links_for_linkedin_url
        print("WARNING: analyze_html_for_linkedin_url is deprecated.")
        return { "linkedin_url": None, "confidence": "none", "reasoning": "This function is deprecated." }

    async def analyze_links_for_linkedin_url(self, search_results: List[Dict], target_name: str) -> Dict:
        """
        Analyzes a list of search result links to find the most relevant LinkedIn profile URL.
        """
        prompt = f"""
        ANALYZE SEARCH RESULTS FOR A LINKEDIN PROFILE

        **Objective:**
        Your task is to act as an expert data analyst. You will be given a JSON list of search engine results and the name of a person. You must find the single most relevant LinkedIn profile URL for that person from the list.

        **Target Person:**
        {target_name}

        **Search Results (JSON):**
        ```json
        {json.dumps(search_results, indent=2)}
        ```

        **Instructions:**
        1.  Examine the list of search results. Each result has a `url`, a `title`, and a `snippet`.
        2.  Your goal is to identify the result that is most likely the correct LinkedIn profile for "{target_name}". The final URL you return **must** start with `https://www.linkedin.com/in/`.
        3.  The `title` and `snippet` are the most important clues. They often contain the person's name, job title, or company.
        4.  **URL Transformation Rule**: Some links may point to a LinkedIn **post** (e.g., a URL containing `/posts/`) or an article. If you determine a post belongs to the target person, you **must transform** the post URL into its corresponding profile URL.
            - **Example Transformation**: A post URL like `https://www.linkedin.com/posts/john-doe-12345_some-activity` must be converted to the profile URL `https://www.linkedin.com/in/john-doe-12345`.
        5.  Use the `title` and `snippet` to confirm the person's identity before transforming a URL.
        6.  If you find a direct profile link (`/in/...`), that is usually the best choice unless a post link has much stronger contextual evidence.
        7.  If multiple results seem correct, choose the one that appears to be the most official or primary profile.

        **Required Output Format:**
        You MUST return a single, valid JSON object and nothing else.
        The JSON object must contain the following keys:
        - `linkedin_url`: The full, correct LinkedIn profile URL. If no relevant URL is found, this must be `null`.
        - `confidence`: A string indicating your confidence in the result. Must be one of: "high", "medium", "low", or "none".
        - `reasoning`: A brief (1-2 sentence) explanation of why you chose this URL or why none was found, referencing the title or snippet.

        **Example Output:**
        {{
          "linkedin_url": "https://www.linkedin.com/in/john-doe-12345",
          "confidence": "high",
          "reasoning": "The link was the first result and its title 'John Doe - Software Engineer at XYZ Corp' directly matches the target."
        }}

        Now, analyze the provided JSON data and find the best LinkedIn URL.
        """
        
        try:
            async_client = openai.AsyncOpenAI(api_key=self.api_key)
            response = await async_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert data analyst. Your task is to analyze a JSON list of search results and return a structured JSON response identifying the correct LinkedIn URL."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            
            analysis_text = response.choices[0].message.content
            return json.loads(analysis_text)

        except Exception as e:
            print(f"An unexpected error occurred during link analysis: {e}")
            return {
                "linkedin_url": None,
                "confidence": "none",
                "reasoning": f"An exception occurred: {e}",
            }

# Example Test Function
async def test_openai_service():
    """A simple function to test the OpenAI service."""
    print("Testing OpenAI Service...")
    
    # Example data based on contact-enrich.md
    test_patent = {
        'patent_number': '7479949',
        'title': 'Touch screen device, method, and graphical user interface',
        'inventors': ['Steven P. Jobs', 'Scott Forstall'],
        'assignee': 'Apple Inc.'
    }

    # Ensure you have your OPENAI_API_KEY set in your environment
    if not os.getenv("OPENAI_API_KEY"):
        print("\nWARNING: OPENAI_API_KEY is not set. The test will fail.")
        print("Please create a .env file and add your key: OPENAI_API_KEY='your_key_here'")
        return

    service = OpenAIService()
    analysis = await service.analyze_inventor_contacts(test_patent)
    
    print("\nAnalysis Result:")
    print(json.dumps(analysis, indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_openai_service()) 