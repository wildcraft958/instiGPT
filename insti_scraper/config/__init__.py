"""
Configuration package.

Contains university profiles and custom configurations.
"""
from .profile_loader import (
    ProfileLoader,
    UniversityProfile,
    SelectorConfig,
    PaginationConfig,
    get_profile_loader,
    get_university_profile
)

__all__ = [
    "ProfileLoader",
    "UniversityProfile", 
    "SelectorConfig",
    "PaginationConfig",
    "get_profile_loader",
    "get_university_profile"
]
