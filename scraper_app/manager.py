"""
CrawlerManager - LangGraph-based orchestrator for the hybrid web scraper.

Manages the crawling workflow using a StateGraph with nodes for:
- PlanAction: Analyze page and decide next action
- ExecuteNavigation: Perform browser actions
- ExtractData: Extract faculty profiles
"""
import json
import logging
import time
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urljoin

from langgraph.graph import StateGraph, END

import sys
sys.path.insert(0, '..')
from models import ProfessorProfile

from .state import (
    CrawlerState, 
    NavigationAction, 
    ActionType,
    create_initial_state,
    action_to_dict,
    dict_to_action
)
from .browser import BrowserManager
from .config import settings
from .utils import (
    setup_logging,
    html_to_markdown,
    ensure_absolute_url,
    check_robots_txt,
    sanitize_filename,
    create_output_dirs
)
from .backends.base import BaseCrawlerBackend
from .backends.gemini import GeminiBackend
from .backends.ollama_vision import OllamaVisionBackend
from .backends.ollama_only import OllamaOnlyBackend

logger = logging.getLogger(__name__)


class CrawlerManager:
    """
    Main orchestrator for the hybrid web scraper.
    
    Uses LangGraph StateGraph to manage the crawl workflow with 
    automatic backend switching (local -> cloud fallback).
    """
    
    def __init__(
        self,
        backend_mode: Literal["auto", "gemini", "local", "ollama_only"] = "auto",
        headless: bool = False,
        debug: bool = False
    ):
        self.backend_mode = backend_mode
        self.debug = debug
        
        # Setup logging
        log_file = "university_crawler.log" if debug else None
        setup_logging(debug, log_file)
        
        # Create output directories
        self.output_dirs = create_output_dirs()
        
        # Initialize browser
        self.browser = BrowserManager(headless=headless)
        
        # Initialize backends
        self.gemini_backend: Optional[GeminiBackend] = None
        self.local_backend: Optional[OllamaVisionBackend] = None
        self.ollama_only_backend: Optional[OllamaOnlyBackend] = None
        self.active_backend: Optional[BaseCrawlerBackend] = None
        
        # Build the state graph
        self.graph = self._build_graph()
        self.compiled_graph = self.graph.compile()
    
    def _initialize_backends(self):
        """Initialize the appropriate backends based on mode."""
        if self.backend_mode in ["auto", "gemini"]:
            self.gemini_backend = GeminiBackend(self.browser)
            
        if self.backend_mode in ["auto", "local"]:
            self.local_backend = OllamaVisionBackend(self.browser)
        
        if self.backend_mode == "ollama_only":
            self.ollama_only_backend = OllamaOnlyBackend(self.browser)
        
        # Set initial active backend
        if self.backend_mode == "ollama_only":
            self.active_backend = self.ollama_only_backend
            logger.info("🔄 Using Ollama-only backend (Qwen3-VL)")
        elif self.backend_mode == "local":
            self.active_backend = self.local_backend
        elif self.backend_mode == "gemini":
            self.active_backend = self.gemini_backend
        else:  # auto - try local first
            if self.local_backend and self.local_backend.is_ready():
                self.active_backend = self.local_backend
                logger.info("🔄 Auto mode: Using local (Ollama Vision) backend")
            elif self.gemini_backend and self.gemini_backend.is_ready():
                self.active_backend = self.gemini_backend
                logger.info("🔄 Auto mode: Using Gemini backend (local not available)")
            else:
                raise RuntimeError("No backend available. Check API keys and Ollama status.")
    
    def _switch_backend(self, reason: str = ""):
        """Switch from local to cloud backend in auto mode."""
        if self.backend_mode != "auto":
            return False
        
        if self.active_backend == self.local_backend and self.gemini_backend:
            logger.info(f"🔄 Switching to Gemini backend: {reason}")
            self.active_backend = self.gemini_backend
            return True
        
        return False
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for crawl orchestration."""
        
        # Define the graph
        workflow = StateGraph(CrawlerState)
        
        # Add nodes
        workflow.add_node("plan_action", self._node_plan_action)
        workflow.add_node("execute_navigation", self._node_execute_navigation)
        workflow.add_node("extract_data", self._node_extract_data)
        workflow.add_node("handle_pagination", self._node_handle_pagination)
        
        # Set entry point
        workflow.set_entry_point("plan_action")
        
        # Add conditional edges from plan_action
        workflow.add_conditional_edges(
            "plan_action",
            self._route_after_plan,
            {
                "execute": "execute_navigation",
                "extract": "extract_data",
                "finish": END,
            }
        )
        
        # After execution, check for more work
        workflow.add_conditional_edges(
            "execute_navigation",
            self._route_after_execute,
            {
                "plan": "plan_action",
                "extract": "extract_data",
                "finish": END,
            }
        )
        
        # After extraction, handle pagination
        workflow.add_edge("extract_data", "handle_pagination")
        
        # After pagination, either continue or finish
        workflow.add_conditional_edges(
            "handle_pagination",
            self._route_after_pagination,
            {
                "continue": "plan_action",
                "finish": END,
            }
        )
        
        return workflow
    
    def _route_after_plan(self, state: CrawlerState) -> str:
        """Route based on the planned action."""
        action_dict = state.get("current_action")
        if not action_dict:
            return "finish"
        
        action = dict_to_action(action_dict)
        
        if action.action_type == ActionType.FINISH:
            return "finish"
        elif action.action_type in [ActionType.EXTRACT_LIST, ActionType.EXTRACT_PROFILE]:
            return "extract"
        else:
            return "execute"
    
    def _route_after_execute(self, state: CrawlerState) -> str:
        """Route after executing navigation."""
        if state.get("step_count", 0) >= state.get("max_steps", 50):
            return "finish"
        
        # Check if we should extract after navigation
        action_dict = state.get("current_action")
        if action_dict:
            action = dict_to_action(action_dict)
            if action.action_type == ActionType.NAVIGATE:
                return "plan"  # Need to plan again for new page
        
        return "plan"
    
    def _route_after_pagination(self, state: CrawlerState) -> str:
        """Route after handling pagination."""
        pagination = state.get("pagination_status", {})
        
        if pagination.get("has_next") and state.get("step_count", 0) < state.get("max_steps", 50):
            return "continue"
        
        return "finish"
    
    # ==================== Node Implementations ====================
    
    def _node_plan_action(self, state: CrawlerState) -> CrawlerState:
        """Plan the next action using the active backend."""
        state["step_count"] = state.get("step_count", 0) + 1
        step = state["step_count"]
        
        logger.info(f"\n--- Step {step} ---")
        
        # Save HTML snapshot if debug mode
        if self.debug:
            html = self.browser.get_html()
            html_path = Path(self.output_dirs['html_logs']) / f"step_{step}.html"
            html_path.write_text(html, encoding='utf-8')
            state["last_html_path"] = str(html_path)
            
            # Also save markdown
            markdown = html_to_markdown(html)
            state["last_markdown"] = markdown
        
        # Get action from backend with retry logic
        action = None
        retry_count = 0
        max_retries = settings.MAX_RETRIES
        
        while retry_count < max_retries:
            try:
                action = self.active_backend.plan_next_action(state)
                is_valid, error = self.active_backend.validate_action(action)
                
                if is_valid:
                    break
                else:
                    logger.warning(f"Invalid action plan: {error}")
                    action = self.active_backend.request_correction(state, action, error)
                    retry_count += 1
                    
            except Exception as e:
                logger.error(f"Planning failed: {e}")
                retry_count += 1
                
                # Try switching backend in auto mode
                if self._switch_backend(str(e)):
                    retry_count = 0  # Reset retries with new backend
        
        if action is None:
            action = NavigationAction(action_type=ActionType.FINISH, reason="Planning failed after retries")
        
        state["current_action"] = action_to_dict(action)
        state["retry_count"] = retry_count
        
        return state
    
    def _node_execute_navigation(self, state: CrawlerState) -> CrawlerState:
        """Execute the planned navigation action."""
        action_dict = state.get("current_action")
        if not action_dict:
            return state
        
        action = dict_to_action(action_dict)
        
        try:
            if action.action_type == ActionType.CLICK:
                logger.info(f"🖱️ Clicking: {action.selector}")
                self.browser.click(action.selector)
                time.sleep(settings.REQUEST_DELAY_MS / 1000)
                
            elif action.action_type == ActionType.NAVIGATE:
                logger.info(f"🌐 Navigating to: {action.url}")
                self.browser.navigate(action.url)
                time.sleep(settings.REQUEST_DELAY_MS / 1000)
                
            elif action.action_type == ActionType.GO_BACK:
                logger.info("⬅️ Going back")
                self.browser.go_back()
                
            # Update current URL
            state["current_url"] = self.browser.get_url()
            
            # Add to visited
            visited = state.get("visited_urls", [])
            if state["current_url"] not in visited:
                visited.append(state["current_url"])
            state["visited_urls"] = visited
                
        except Exception as e:
            error_msg = f"Navigation failed: {e}"
            logger.error(error_msg)
            state["last_error"] = error_msg
            errors = state.get("errors", [])
            errors.append(error_msg)
            state["errors"] = errors
        
        return state
    
    def _node_extract_data(self, state: CrawlerState) -> CrawlerState:
        """Extract faculty profiles from the current page."""
        action_dict = state.get("current_action")
        if not action_dict:
            return state
        
        action = dict_to_action(action_dict)
        html = self.browser.get_html()
        base_url = self.browser.get_url()
        
        found_profiles = state.get("found_profiles", [])
        
        if action.action_type == ActionType.EXTRACT_LIST:
            # Extract from directory listing
            logger.info("📋 Extracting from faculty list...")
            
            if action.card_selector:
                cards = self.browser.query_selector_all(action.card_selector)
                logger.info(f"Found {len(cards)} faculty cards")
                
                for card in cards:
                    try:
                        # Extract basic info from card
                        name_el = card.query_selector(action.name_selector) if action.name_selector else None
                        title_el = card.query_selector(action.title_selector) if action.title_selector else None
                        link_el = card.query_selector(action.link_selector) if action.link_selector else None
                        
                        name = name_el.inner_text().strip() if name_el else "Unknown"
                        title = title_el.inner_text().strip() if title_el else "Unknown"
                        profile_url = ""
                        
                        if link_el:
                            href = link_el.get_attribute("href")
                            if href:
                                profile_url = ensure_absolute_url(base_url, href)
                        
                        # Create partial profile
                        partial = ProfessorProfile(
                            name=name,
                            title=title,
                            profile_url=profile_url
                        )
                        
                        # Navigate to profile page and extract full data
                        if profile_url and profile_url not in state.get("visited_urls", []):
                            profile_page = self.browser.new_page()
                            try:
                                profile_page.goto(profile_url, wait_until="domcontentloaded")
                                time.sleep(settings.REQUEST_DELAY_MS / 1000)
                                
                                profile_html = profile_page.content()
                                
                                # Save profile HTML if debug
                                if self.debug:
                                    safe_name = sanitize_filename(name)
                                    profile_dir = Path(self.output_dirs['output']) / safe_name
                                    profile_dir.mkdir(exist_ok=True)
                                    (profile_dir / "profile.html").write_text(profile_html, encoding='utf-8')
                                
                                # Extract full profile
                                extracted = self.active_backend.extract_profiles(profile_html, [partial])
                                if extracted:
                                    found_profiles.extend(extracted)
                                    
                            except Exception as e:
                                logger.error(f"Failed to extract profile for {name}: {e}")
                                found_profiles.append(partial)  # Save partial data
                            finally:
                                profile_page.close()
                        else:
                            found_profiles.append(partial)
                            
                    except Exception as e:
                        logger.error(f"Error processing card: {e}")
            else:
                # Fallback: extract from full page content
                extracted = self.active_backend.extract_profiles(html)
                found_profiles.extend(extracted)
                
        elif action.action_type == ActionType.EXTRACT_PROFILE:
            # Single profile extraction
            logger.info("👤 Extracting single profile...")
            partial = ProfessorProfile(name="Unknown", title="Unknown", profile_url=base_url)
            extracted = self.active_backend.extract_profiles(html, [partial])
            found_profiles.extend(extracted)
        
        state["found_profiles"] = found_profiles
        logger.info(f"📊 Total profiles collected: {len(found_profiles)}")
        
        return state
    
    def _node_handle_pagination(self, state: CrawlerState) -> CrawlerState:
        """Handle pagination to get more results."""
        action_dict = state.get("current_action")
        if not action_dict:
            return state
        
        action = dict_to_action(action_dict)
        
        # Check for pagination
        pagination_selector = action.next_page_selector or action.load_more_selector
        
        if pagination_selector:
            try:
                next_button = self.browser.query_selector(pagination_selector)
                if next_button:
                    is_visible = next_button.is_visible()
                    is_enabled = next_button.is_enabled() if hasattr(next_button, 'is_enabled') else True
                    
                    if is_visible and is_enabled:
                        logger.info(f"📄 Clicking pagination: {pagination_selector}")
                        next_button.click()
                        self.browser.page.wait_for_load_state("domcontentloaded")
                        time.sleep(settings.REQUEST_DELAY_MS / 1000)
                        
                        state["pagination_status"] = {
                            "has_next": True,
                            "selector": pagination_selector,
                            "type": "load_more" if action.load_more_selector else "numbered"
                        }
                        return state
                        
            except Exception as e:
                logger.warning(f"Pagination failed: {e}")
        
        # No more pagination
        state["pagination_status"] = {"has_next": False, "selector": None, "type": None}
        return state
    
    # ==================== Public API ====================
    
    def run(
        self,
        start_url: str,
        objective: str,
        max_steps: int = 50,
        check_robots: bool = True
    ) -> list[ProfessorProfile]:
        """
        Run the crawler.
        
        Args:
            start_url: URL to start crawling from
            objective: Description of what to scrape
            max_steps: Maximum number of steps
            check_robots: Whether to check robots.txt
        
        Returns:
            List of extracted ProfessorProfile objects
        """
        # Check robots.txt
        if check_robots and not check_robots_txt(start_url):
            logger.warning(f"⚠️ Crawling may not be allowed by robots.txt for {start_url}")
            # Continue anyway but warn user
        
        try:
            # Setup browser and backends
            self.browser.setup()
            self._initialize_backends()
            
            # Navigate to start URL
            self.browser.navigate(start_url)
            time.sleep(1)  # Initial load delay
            
            # Create initial state
            initial_state = create_initial_state(
                start_url=start_url,
                objective=objective,
                backend_mode=self.backend_mode,
                max_steps=max_steps
            )
            
            # Run the graph
            logger.info(f"🚀 Starting crawl with backend: {self.active_backend.name}")
            final_state = self.compiled_graph.invoke(initial_state)
            
            # Get results
            profiles = final_state.get("found_profiles", [])
            
            logger.info(f"\n--- Crawling Finished ---")
            logger.info(f"📊 Extracted {len(profiles)} profiles")
            
            return profiles
            
        except Exception as e:
            logger.error(f"Crawl failed: {e}", exc_info=True)
            return []
            
        finally:
            self.browser.cleanup()
    
    def save_results(self, profiles: list[ProfessorProfile], output_file: str = "faculty_data.json"):
        """Save extracted profiles to JSON file."""
        if not profiles:
            logger.warning("No profiles to save")
            return
        
        output_path = Path(output_file)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([p.model_dump() for p in profiles], f, indent=2)
        
        logger.info(f"💾 Saved {len(profiles)} profiles to {output_path}")
