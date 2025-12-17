"""
LangGraph state definitions for the crawler.
"""
from typing import TypedDict, List, Optional, Literal, Set
from dataclasses import dataclass, field
from enum import Enum

import sys
sys.path.insert(0, '..')
from models import ProfessorProfile


class ActionType(str, Enum):
    """Types of navigation actions the crawler can take."""
    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    EXTRACT_LIST = "EXTRACT_LIST"
    EXTRACT_PROFILE = "EXTRACT_PROFILE"
    NEXT_PAGE = "NEXT_PAGE"
    LOAD_MORE = "LOAD_MORE"
    GO_BACK = "GO_BACK"
    FINISH = "FINISH"


@dataclass
class NavigationAction:
    """Represents a navigation action to be executed."""
    action_type: ActionType
    selector: Optional[str] = None
    url: Optional[str] = None
    reason: str = ""
    
    # For EXTRACT_LIST action
    card_selector: Optional[str] = None
    link_selector: Optional[str] = None
    name_selector: Optional[str] = None
    title_selector: Optional[str] = None
    
    # For pagination
    next_page_selector: Optional[str] = None
    load_more_selector: Optional[str] = None


class CrawlerState(TypedDict, total=False):
    """
    State object for the LangGraph crawler.
    Tracks all information needed across the crawl session.
    """
    # Core state
    current_url: str
    objective: str
    backend_mode: Literal["auto", "gemini", "local"]
    
    # Collected data
    found_profiles: List[ProfessorProfile]
    pending_profile_urls: List[str]
    visited_urls: List[str]  # Using List instead of Set for serialization
    
    # Navigation state
    current_action: Optional[dict]  # Serialized NavigationAction
    pagination_status: dict  # {has_next: bool, selector: str, type: 'numbered'|'load_more'}
    
    # Step tracking
    step_count: int
    max_steps: int
    
    # Error handling
    errors: List[str]
    retry_count: int
    last_error: Optional[str]
    
    # Debug info
    last_screenshot_path: Optional[str]
    last_html_path: Optional[str]
    last_markdown: Optional[str]


def create_initial_state(
    start_url: str,
    objective: str,
    backend_mode: Literal["auto", "gemini", "local"] = "auto",
    max_steps: int = 50
) -> CrawlerState:
    """
    Create the initial crawler state.
    
    Args:
        start_url: URL to start crawling from
        objective: Description of the crawling objective
        backend_mode: Which backend to use
        max_steps: Maximum crawl steps
    
    Returns:
        Initialized CrawlerState
    """
    return CrawlerState(
        current_url=start_url,
        objective=objective,
        backend_mode=backend_mode,
        found_profiles=[],
        pending_profile_urls=[],
        visited_urls=[],
        current_action=None,
        pagination_status={"has_next": False, "selector": None, "type": None},
        step_count=0,
        max_steps=max_steps,
        errors=[],
        retry_count=0,
        last_error=None,
        last_screenshot_path=None,
        last_html_path=None,
        last_markdown=None,
    )


def action_to_dict(action: NavigationAction) -> dict:
    """Serialize NavigationAction for state storage."""
    return {
        "action_type": action.action_type.value,
        "selector": action.selector,
        "url": action.url,
        "reason": action.reason,
        "card_selector": action.card_selector,
        "link_selector": action.link_selector,
        "name_selector": action.name_selector,
        "title_selector": action.title_selector,
        "next_page_selector": action.next_page_selector,
        "load_more_selector": action.load_more_selector,
    }


def dict_to_action(data: dict) -> NavigationAction:
    """Deserialize NavigationAction from state storage."""
    return NavigationAction(
        action_type=ActionType(data["action_type"]),
        selector=data.get("selector"),
        url=data.get("url"),
        reason=data.get("reason", ""),
        card_selector=data.get("card_selector"),
        link_selector=data.get("link_selector"),
        name_selector=data.get("name_selector"),
        title_selector=data.get("title_selector"),
        next_page_selector=data.get("next_page_selector"),
        load_more_selector=data.get("load_more_selector"),
    )
