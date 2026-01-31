"""Batch processing pipelines."""

from .process_universities import UniversityProcessor, process_universities_batch

__all__ = ["UniversityProcessor", "process_universities_batch"]
