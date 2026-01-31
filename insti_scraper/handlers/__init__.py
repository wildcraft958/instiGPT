"""
Handlers package for different page types.

Contains:
- pagination_handler: Multi-page extraction
"""
from .pagination_handler import PaginationHandler, extract_with_pagination, PageResult

__all__ = ["PaginationHandler", "extract_with_pagination", "PageResult"]
