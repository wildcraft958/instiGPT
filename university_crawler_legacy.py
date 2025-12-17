import os
import logging
import sys
import argparse
import json
import time
from playwright.sync_api import sync_playwright, Page
from dotenv import load_dotenv
import google.genai as genai
import ollama
from typing import TypedDict, List, Dict, Any
from urllib.parse import urljoin
import re
from bs4 import BeautifulSoup

from models import ProfessorProfile
from prompts import GEMINI_ANALYSIS_PROMPT, OLLAMA_EXTRACTION_PROMPT, GEMINI_CORRECTION_PROMPT

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('university_crawler.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- LLM Clients ---
try:
    # The new SDK uses a client-based approach
    gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    # Quick validation call to check the API key
    gemini_client.models.list()
    logging.info("Gemini client initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize Gemini client: {e}")
    gemini_client = None

try:
    ollama.pull('llama3.2:latest')
    ollama_client = ollama.Client()
    logging.info("Ollama client initialized and model pulled successfully.")
except Exception as e:
    logging.error(f"Failed to initialize Ollama client or pull model: {e}")
    ollama_client = None


class UniversityCrawler:
    def __init__(self, verbose=False):
        self.playwright = None
        self.context = None
        self.page = None
        self.verbose = verbose

    def setup_browser(self):
        """Initialize browser with stealth settings."""
        if self.playwright:
            return
        logging.info("🔧 Setting up browser...")
        self.playwright = sync_playwright().__enter__()
        
        user_data_dir = os.path.join(os.path.expanduser("~"), ".playwright_user_data")

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            args=["--start-maximized"],
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080}
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(60000)
        logging.info("✅ Browser setup complete")

    def validate_action_plan(self, action_plan: Dict[str, Any]) -> (bool, str):
        """Validates the action plan from Gemini."""
        action = action_plan.get("action")
        args = action_plan.get("args", {})

        if not action:
            return False, "The 'action' key is missing from the plan."

        if action == "CLICK":
            if not args.get("selector"):
                return False, "Action 'CLICK' is missing the required 'selector' argument."
        
        if action in ["NAVIGATE_TO_LIST", "EXTRACT_LIST"]:
            required_keys = ["card_selector", "link_selector", "name_selector", "title_selector"]
            missing_keys = [key for key in required_keys if not args.get(key)]
            if missing_keys:
                return False, f"Action '{action}' is missing required arguments: {', '.join(missing_keys)}."
        
        return True, "Plan is valid."

    def analyze_page_with_gemini(self, objective: str, html_content: str, previous_plan: Dict = None, failure_reason: str = None) -> Dict[str, Any]:
        """Use Gemini to analyze the page and decide the next action. Can also be used for corrections."""
        if previous_plan:
            logging.info("🧠 Re-analyzing page with Gemini for a correction...")
            prompt = GEMINI_CORRECTION_PROMPT.format(
                objective=objective,
                current_url=self.page.url,
                invalid_plan=json.dumps(previous_plan, indent=2),
                failure_reason=failure_reason,
                html_content=html_content
            )
        else:
            logging.info("🧠 Analyzing page with Gemini...")
            prompt = GEMINI_ANALYSIS_PROMPT.format(
                objective=objective,
                current_url=self.page.url,
                html_content=html_content
            )
        
        try:
            # Use the new client method to generate content
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            # Clean the response text
            cleaned_response_text = response.text.strip().replace("```json", "").replace("```", "")
            action_plan = json.loads(cleaned_response_text)
            logging.info(f"🤖 Gemini suggested action: {action_plan.get('action')}")
            return action_plan
        except Exception as e:
            logging.error(f"Error analyzing page with Gemini: {e}")
            return {"action": "FINISH", "args": {"reason": "Gemini analysis failed."}}

    def extract_json_from_response(self, text: str) -> Dict[str, Any]:
        """Finds and parses a JSON object from a string, even with surrounding text."""
        # Find the start of the JSON object
        json_start = text.find('{')
        # Find the end of the JSON object
        json_end = text.rfind('}') + 1

        if json_start == -1 or json_end == 0:
            logging.error("No JSON object found in the response.")
            return None

        json_str = text[json_start:json_end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse extracted JSON: {e}")
            logging.error(f"Content that failed to parse: {json_str}")
            return None

    def extract_faculty_data_with_ollama(self, html_content: str, partial_profile: ProfessorProfile) -> ProfessorProfile:
        """Use Ollama to extract faculty data from a profile page."""
        logging.info(f"🖋️ Extracting details for {partial_profile.name}...")
        
        # --- Strip HTML to get clean text ---
        soup = BeautifulSoup(html_content, 'html.parser')
        # Get text from the main content area if possible, otherwise body
        main_content = soup.find('main') or soup.find('article') or soup.body
        page_text = main_content.get_text(separator='\\n', strip=True)

        partial_data_json = partial_profile.model_dump_json(indent=2)
        
        prompt = OLLAMA_EXTRACTION_PROMPT.format(
            partial_data=partial_data_json,
            page_text_content=page_text
        )
        try:
            response = ollama_client.generate(model='llama3.2:latest', prompt=prompt)
            response_text = response['response']
            
            extracted_json = self.extract_json_from_response(response_text)
            
            if not extracted_json:
                logging.error(f"Could not parse JSON for {partial_profile.name}")
                return partial_profile # Return the partial data at least

            # Update the profile with the newly extracted data
            # Pydantic will validate the data types
            updated_profile = partial_profile.model_copy(update=extracted_json)
            logging.info(f"✅ Extracted profile for: {updated_profile.name}")
            return updated_profile

        except Exception as e:
            logging.error(f"Error extracting data with Ollama for {partial_profile.name}: {e}")
            return partial_profile # Return partial data on failure

    def run(self, start_url: str, objective: str):
        """Main execution loop for the crawler."""
        if not gemini_client or not ollama_client:
            logging.error("LLM clients not initialized. Aborting.")
            return

        self.setup_browser()
        all_profiles = []
        max_steps = 20 # To prevent infinite loops
        step_count = 0
        
        # Create directories to store logs and scraped data
        os.makedirs("html_logs", exist_ok=True)
        os.makedirs("scraped_data", exist_ok=True)
        
        try:
            logging.info(f"Navigating to {start_url}")
            self.page.goto(start_url, wait_until="domcontentloaded")
            
            while step_count < max_steps:
                step_count += 1
                logging.info(f"\n--- Step {step_count} ---")
                
                html_content = self.page.content()
                with open(os.path.join("html_logs", f"step_{step_count}_main_page.html"), "w", encoding="utf-8") as f:
                    f.write(html_content)
                
                action_plan = None
                for attempt in range(3): # Allow up to 3 attempts for self-correction
                    if attempt > 0:
                        action_plan = self.analyze_page_with_gemini(objective, html_content, previous_plan=action_plan, failure_reason=failure_reason)
                    else:
                        action_plan = self.analyze_page_with_gemini(objective, html_content)
                    
                    is_valid, failure_reason = self.validate_action_plan(action_plan)
                    if is_valid:
                        break
                    else:
                        logging.warning(f"Attempt {attempt + 1}: Gemini plan is invalid. Reason: {failure_reason}")
                        if attempt == 2:
                            logging.error("Gemini failed to provide a valid plan after 3 attempts. Finishing.")
                            action_plan = {"action": "FINISH", "args": {"reason": "Gemini could not produce a valid plan."}}

                action = action_plan.get("action")
                args = action_plan.get("args", {})
                
                if action == "NAVIGATE_TO_LIST" or action == "EXTRACT_LIST": # Treat EXTRACT_LIST as an alias
                    logging.info("Action: NAVIGATE_TO_LIST")
                    card_selector = args.get("card_selector")
                    link_selector = args.get("link_selector")
                    name_selector = args.get("name_selector")
                    title_selector = args.get("title_selector")
                    
                    # This check is now redundant because of validate_action_plan, but we keep it as a safeguard
                    if not all([card_selector, link_selector, name_selector, title_selector]):
                        logging.error(f"Missing one or more required selectors for {action} action. Finishing.")
                        break

                    professor_cards = self.page.query_selector_all(card_selector)
                    logging.info(f"Found {len(professor_cards)} professor cards.")
                    
                    for card in professor_cards:
                        try:
                            name = card.query_selector(name_selector).inner_text().strip()
                            title = card.query_selector(title_selector).inner_text().strip()
                            link_element = card.query_selector(link_selector)
                            
                            if not all([name, title, link_element]):
                                logging.warning("Could not extract name, title, or link from a card. Skipping.")
                                continue

                            profile_url = link_element.get_attribute("href")
                            if not profile_url:
                                logging.warning("Found card but no href attribute. Skipping.")
                                continue
                                
                            full_profile_url = urljoin(self.page.url, profile_url)
                            
                            # --- Structured Output Logic ---
                            safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c==' ']).replace(' ', '_')
                            professor_dir = os.path.join("scraped_data", safe_name)
                            os.makedirs(professor_dir, exist_ok=True)
                            
                            # Create a partial profile with pre-scraped data
                            partial_profile = ProfessorProfile(
                                name=name,
                                title=title,
                                profile_url=full_profile_url
                            )
                            
                            # Save the card data
                            with open(os.path.join(professor_dir, "card_data.json"), "w") as f:
                                f.write(partial_profile.model_dump_json(indent=2))

                            # Navigate and extract the rest of the data
                            profile_page = self.context.new_page()
                            try:
                                profile_page.goto(full_profile_url, wait_until="domcontentloaded")
                                profile_html = profile_page.content()
                                
                                # Save profile page HTML
                                with open(os.path.join(professor_dir, "profile_page.html"), "w", encoding="utf-8") as f:
                                    f.write(profile_html)

                                final_profile = self.extract_faculty_data_with_ollama(profile_html, partial_profile)
                                if final_profile:
                                    all_profiles.append(final_profile)
                                    # Save the final profile data
                                    with open(os.path.join(professor_dir, "profile_data.json"), "w") as f:
                                        f.write(final_profile.model_dump_json(indent=2))
                            finally:
                                profile_page.close()
                        except Exception as e:
                            logging.error(f"Error processing a professor card: {e}", exc_info=True)

                    # Handle pagination
                    next_page_selector = args.get("next_page_selector")
                    if next_page_selector:
                        next_button = self.page.query_selector(next_page_selector)
                        if next_button:
                            logging.info("Clicking next page button...")
                            next_button.click()
                            self.page.wait_for_load_state("domcontentloaded")
                        else:
                            logging.info("No more next page buttons. Finishing.")
                            break
                    else:
                        logging.info("No pagination detected. Finishing list navigation.")
                        break
                        
                elif action == "EXTRACT_LIST":
                    logging.info("Action: EXTRACT_LIST")
                    card_selector = args.get("faculty_card_selector")
                    
                    if not card_selector:
                        logging.error("Missing 'faculty_card_selector' for EXTRACT_LIST action. Finishing.")
                        break

                    professor_cards = self.page.query_selector_all(card_selector)
                    logging.info(f"Found {len(professor_cards)} professor cards using selector '{card_selector}'.")
                    
                    for card in professor_cards:
                        try:
                            # Since we don't have pre-defined selectors for name/title/link here,
                            # we pass the entire card's HTML to Ollama for extraction.
                            card_html = card.inner_html()
                            
                            # Create a placeholder profile. Ollama will fill in the details.
                            partial_profile = ProfessorProfile(name="Unknown", title="Unknown", profile_url="")
                            
                            final_profile = self.extract_faculty_data_with_ollama(card_html, partial_profile)
                            
                            if final_profile and final_profile.name != "Unknown":
                                # If a profile URL was extracted, make it absolute
                                if final_profile.profile_url:
                                    final_profile.profile_url = urljoin(self.page.url, final_profile.profile_url)
                                all_profiles.append(final_profile)
                        except Exception as e:
                            logging.error(f"Error processing a professor card: {e}", exc_info=True)

                    # After extracting, handle pagination
                    next_page_selector = args.get("next_page_selector")
                    if next_page_selector:
                        next_button = self.page.query_selector(next_page_selector)
                        if next_button and next_button.is_visible() and next_button.is_enabled():
                            logging.info(f"Clicking next page button with selector '{next_page_selector}'...")
                            next_button.click()
                            self.page.wait_for_load_state("domcontentloaded")
                        else:
                            logging.info("No more next page buttons, or button is not interactive. Finishing.")
                            break
                    else:
                        logging.info("No pagination detected. Finishing list navigation.")
                        break

                elif action == "EXTRACT_PROFILE":
                    logging.info("Action: EXTRACT_PROFILE")
                    # This case needs to be more robust - what's the name/title?
                    # For now, we'll assume it's a one-off and won't have pre-scraped data
                    profile = self.extract_faculty_data_with_ollama(html_content, ProfessorProfile(name="Unknown", title="Unknown", profile_url=self.page.url))
                    if profile:
                        all_profiles.append(profile)
                    logging.info("Profile extracted. Finishing.")
                    break # Assuming one profile per run if starting on a profile page

                elif action == "CLICK":
                    logging.info(f"Action: CLICK on selector '{args.get('selector')}'")
                    selector = args.get("selector")
                    
                    # This check is now redundant because of validate_action_plan, but we keep it as a safeguard
                    if selector:
                        self.page.click(selector)
                        self.page.wait_for_load_state("domcontentloaded")
                    else:
                        logging.error("No selector provided for CLICK action. Finishing.")
                        break
                        
                elif action == "FINISH":
                    logging.info(f"Action: FINISH. Reason: {args.get('reason')}")
                    break
                
                else:
                    logging.warning(f"Unknown action: {action}. Finishing.")
                    break
            
            logging.info(f"\n--- Crawling Finished ---")
            logging.info(f"Extracted {len(all_profiles)} profiles.")
            
            if all_profiles:
                with open("faculty_data.json", "w") as f:
                    json.dump([p.model_dump() for p in all_profiles], f, indent=2)
                logging.info("💾 Saved data to faculty_data.json")

        except Exception as e:
            logging.error(f"An error occurred during the run: {e}", exc_info=True)
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up browser resources."""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()
        logging.info("🧹 Browser cleaned up.")

def main():
    parser = argparse.ArgumentParser(description="University Faculty Web Crawler")
    parser.add_argument("--url", required=True, help="Starting URL for the university faculty page.")
    parser.add_argument("--objective", required=True, help="The objective for the crawler (e.g., 'Scrape all Computer Science professors').")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")
    args = parser.parse_args()
    
    crawler = UniversityCrawler(verbose=args.verbose)
    crawler.run(start_url=args.url, objective=args.objective)

if __name__ == "__main__":
    main()
