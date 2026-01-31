"""
Configuration updater service.

Handles updating the university_profiles.yaml file with learned information
such as valid CSS selectors (from successful strategies) and new faculty URLs.
"""
import yaml
import os
from typing import Dict, Any, Optional, List
from threading import Lock

from insti_scraper.core.logger import logger
from insti_scraper.core.selector_strategies import SelectorStrategy

# Thread-safe lock for file writing
_config_lock = Lock()

class ProfileUpdater:
    """Updates university profiles with learned information."""
    
    def __init__(self, config_path: str = "insti_scraper/config/university_profiles.yaml"):
        # Ensure path is absolute if needed, or relative to cwd
        if not os.path.exists(config_path):
            # Try finding it relative to package
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config/university_profiles.yaml")
            
        self.config_path = config_path
    
    def update_profile_selectors(self, domain_pattern: str, strategy: SelectorStrategy):
        """
        Update a university profile with working selectors from a successful strategy.
        
        Args:
            domain_pattern: The regex pattern identifying the university
            strategy: The successful SelectorStrategy
        """
        if strategy.name.startswith("custom_"):
            # Don't update if it was already the custom strategy
            return
            
        with _config_lock:
            try:
                data = self._load_yaml()
                updated = False
                
                for profile in data.get('profiles', []):
                    if profile.get('domain_pattern') == domain_pattern:
                        # Found the profile
                        logger.info(f"   [Config] Updating selectors for {profile.get('name')} based on valid strategy '{strategy.name}'")
                        
                        profile['selectors'] = {
                            'container': strategy.container,
                            'name': strategy.name_selector,
                            'title': strategy.title_selector,
                            'email': strategy.email_selector,
                            'profile_link': strategy.link_selector
                        }
                        
                        # Remove keys that are None
                        profile['selectors'] = {k: v for k, v in profile['selectors'].items() if v}
                        
                        updated = True
                        break
                
                if updated:
                    self._save_yaml(data)
                    logger.info("   [Config] Saved updated profile configuration.")
                    
            except Exception as e:
                logger.error(f"   ❌ Failed to update profile config: {e}")

    def add_faculty_url(self, domain_pattern: str, url: str):
        """
        Add a newly discovered faculty URL to the profile.
        """
        with _config_lock:
            try:
                data = self._load_yaml()
                updated = False
                
                for profile in data.get('profiles', []):
                    if profile.get('domain_pattern') == domain_pattern:
                        urls = profile.get('faculty_urls', [])
                        if url not in urls:
                            logger.info(f"   [Config] Adding new known URL to {profile.get('name')}: {url}")
                            urls.append(url)
                            profile['faculty_urls'] = urls
                            updated = True
                        break
                
                if updated:
                    self._save_yaml(data)
            except Exception as e:
                logger.error(f"   ❌ Failed to update profile URL: {e}")

    def _load_yaml(self) -> Dict:
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f) or {'profiles': []}
    
    def _save_yaml(self, data: Dict):
        with open(self.config_path, 'w') as f:
            # Dump with some style preservation
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, indent=2)

# Global instance
profile_updater = ProfileUpdater()
