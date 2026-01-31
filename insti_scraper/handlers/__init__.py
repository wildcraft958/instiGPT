"""
Handlers package for different page types.

Contains:
- pagination_handler: Multi-page extraction
- page_handlers: Abstract handlers for different page types
"""
from .pagination_handler import PaginationHandler, extract_with_pagination, PageResult
from .page_handlers import (
    PageHandler,
    DirectoryPageHandler,
    GatewayPageHandler,
    PaginatedPageHandler,
    ProfilePageHandler,
    ExtractionResult,
    get_handler_for_page_type
)

__all__ = [
    "PaginationHandler", 
    "extract_with_pagination", 
    "PageResult",
    "PageHandler",
    "DirectoryPageHandler",
    "GatewayPageHandler",
    "PaginatedPageHandler",
    "ProfilePageHandler",
    "ExtractionResult",
    "get_handler_for_page_type"
]
