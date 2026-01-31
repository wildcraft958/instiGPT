"""
University profile loader and matcher.

Loads university-specific configurations from YAML and matches
domains to provide custom selectors and settings.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from insti_scraper.core.logger import logger


@dataclass
class PaginationConfig:
    """Pagination configuration for a university."""
    type: str = "auto"  # datatable, click, alpha, infinite_scroll, auto
    max_pages: int = 50
    items_per_page: int = 10
    scroll_pause: float = 1.0


@dataclass
class SelectorConfig:
    """CSS selectors for a university's faculty pages."""
    container: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    profile_link: Optional[str] = None
    department: Optional[str] = None
    
    def has_selectors(self) -> bool:
        return any([self.container, self.name, self.title, self.email])


@dataclass
class UniversityProfile:
    """Complete profile for a university."""
    domain_pattern: str
    name: str
    faculty_urls: List[str] = field(default_factory=list)
    discovery_hints: List[str] = field(default_factory=list)
    selectors: Optional[SelectorConfig] = None
    pagination: Optional[PaginationConfig] = None
    
    def matches(self, url: str) -> bool:
        """Check if URL matches this university's domain pattern."""
        return bool(re.search(self.domain_pattern, url, re.IGNORECASE))


class ProfileLoader:
    """
    Loads and matches university profiles from YAML configuration.
    
    Usage:
        loader = ProfileLoader()
        profile = loader.get_profile("https://cs.princeton.edu/people")
        if profile:
            print(f"Using {profile.name} configuration")
    """
    
    _instance: Optional['ProfileLoader'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self.profiles: List[UniversityProfile] = []
            self._load_profiles()
            self._loaded = True
    
    def _load_profiles(self):
        """Load profiles from YAML configuration."""
        config_path = Path(__file__).parent / "university_profiles.yaml"
        
        if not config_path.exists():
            logger.warning(f"University profiles not found at {config_path}")
            return
        
        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f)
            
            if not data or 'profiles' not in data:
                return
            
            for p in data['profiles']:
                selectors = None
                if p.get('selectors'):
                    selectors = SelectorConfig(**p['selectors'])
                
                pagination = None
                if p.get('pagination'):
                    pagination = PaginationConfig(**p['pagination'])
                
                profile = UniversityProfile(
                    domain_pattern=p['domain_pattern'],
                    name=p['name'],
                    faculty_urls=p.get('faculty_urls', []),
                    discovery_hints=p.get('discovery_hints', []),
                    selectors=selectors,
                    pagination=pagination
                )
                self.profiles.append(profile)
            
            logger.info(f"Loaded {len(self.profiles)} university profiles")
            
        except Exception as e:
            logger.error(f"Failed to load university profiles: {e}")
    
    def get_profile(self, url: str) -> Optional[UniversityProfile]:
        """
        Get matching profile for a URL.
        
        Returns the most specific matching profile (non-generic first).
        """
        matches = [p for p in self.profiles if p.matches(url)]
        
        if not matches:
            return None
        
        # Prefer specific patterns over generic ones
        # Sort by pattern specificity (more specific = longer pattern without wildcards)
        def specificity(p: UniversityProfile) -> int:
            pattern = p.domain_pattern
            # Penalize wildcards
            if pattern.startswith(".*"):
                return -1
            return len(pattern.replace("\\", "").replace(".", ""))
        
        matches.sort(key=specificity, reverse=True)
        return matches[0]
    
    def get_known_urls(self, url: str) -> List[str]:
        """Get known faculty URLs for a university (bypasses discovery)."""
        profile = self.get_profile(url)
        return profile.faculty_urls if profile else []
    
    def get_selectors(self, url: str) -> Optional[SelectorConfig]:
        """Get custom CSS selectors for a university."""
        profile = self.get_profile(url)
        return profile.selectors if profile else None


# Convenience functions
def get_profile_loader() -> ProfileLoader:
    """Get the singleton profile loader instance."""
    return ProfileLoader()


def get_university_profile(url: str) -> Optional[UniversityProfile]:
    """Get profile for a URL."""
    return get_profile_loader().get_profile(url)
