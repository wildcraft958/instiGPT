"""
Enhanced database operations with advanced querying and batch operations.

Extends the basic SQLModel functionality with specialized queries
and bulk operations for better performance.
"""

import logging
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone

from sqlmodel import Session, select, func, or_, and_
from sqlalchemy import distinct

from .models import Professor, University, Department, get_engine, init_database

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Advanced database operations manager.
    
    Provides:
    - Bulk insert/update operations
    - Advanced queries with filters
    - Statistics and analytics
    - Deduplication logic
    """
    
    def __init__(self):
        """Initialize database manager."""
        self.engine = get_engine()
        init_database()
    
    def get_session(self) -> Session:
        """Get a database session."""
        return Session(self.engine)
    
    # =========================================================================
    # Bulk Operations
    # =========================================================================
    
    def bulk_insert_professors(
        self,
        professors: List[Professor],
        university_name: str,
        department_name: str,
        skip_duplicates: bool = True
    ) -> Dict[str, int]:
        """
        Bulk insert professors with automatic deduplication.
        
        Args:
            professors: List of Professor objects
            university_name: University name
            department_name: Department name
            skip_duplicates: Skip if professor already exists
        
        Returns:
            Statistics dict: {"inserted": N, "updated": M, "skipped": K}
        """
        stats = {"inserted": 0, "updated": 0, "skipped": 0}
        
        with self.get_session() as session:
            # Get or create university
            university = self._get_or_create_university(
                session, university_name
            )
            
            # Get or create department
            department = self._get_or_create_department(
                session, department_name, university.id
            )
            
            for prof in professors:
                # Check for duplicate
                existing = session.exec(
                    select(Professor).where(
                        Professor.name == prof.name,
                        Professor.department_id == department.id
                    )
                ).first()
                
                if existing:
                    if skip_duplicates:
                        stats["skipped"] += 1
                        continue
                    else:
                        # Update existing
                        self._update_professor(existing, prof)
                        stats["updated"] += 1
                else:
                    # Insert new
                    prof.department_id = department.id
                    prof.created_at = datetime.now(timezone.utc)
                    prof.updated_at = datetime.now(timezone.utc)
                    session.add(prof)
                    stats["inserted"] += 1
            
            session.commit()
        
        logger.info(f"Bulk insert: {stats}")
        return stats
    
    def _get_or_create_university(
        self,
        session: Session,
        name: str,
        website: str = None
    ) -> University:
        """Get or create university."""
        university = session.exec(
            select(University).where(University.name == name)
        ).first()
        
        if not university:
            university = University(
                name=name,
                website=website or f"https://{name.lower().replace(' ', '')}.edu"
            )
            session.add(university)
            session.commit()
            session.refresh(university)
        
        return university
    
    def _get_or_create_department(
        self,
        session: Session,
        name: str,
        university_id: int
    ) -> Department:
        """Get or create department."""
        department = session.exec(
            select(Department).where(
                Department.name == name,
                Department.university_id == university_id
            )
        ).first()
        
        if not department:
            department = Department(
                name=name,
                university_id=university_id
            )
            session.add(department)
            session.commit()
            session.refresh(department)
        
        return department
    
    def _update_professor(self, existing: Professor, new_data: Professor):
        """Update existing professor with new data."""
        # Only update if new data is not None
        if new_data.email and not existing.email:
            existing.email = new_data.email
        if new_data.phone and not existing.phone:
            existing.phone = new_data.phone
        if new_data.office and not existing.office:
            existing.office = new_data.office
        if new_data.profile_url and not existing.profile_url:
            existing.profile_url = new_data.profile_url
        if new_data.image_url and not existing.image_url:
            existing.image_url = new_data.image_url
        if new_data.website_url and not existing.website_url:
            existing.website_url = new_data.website_url
        
        # Merge research interests
        if new_data.research_interests:
            current = set(existing.research_interests)
            for interest in new_data.research_interests:
                if interest not in current:
                    existing.research_interests.append(interest)
        
        # Update Scholar data if better
        if new_data.google_scholar_id and not existing.google_scholar_id:
            existing.google_scholar_id = new_data.google_scholar_id
            existing.h_index = new_data.h_index
            existing.total_citations = new_data.total_citations
            existing.top_papers = new_data.top_papers
        
        existing.updated_at = datetime.now(timezone.utc)
    
    # =========================================================================
    # Advanced Queries
    # =========================================================================
    
    def search_professors(
        self,
        name: str = None,
        university: str = None,
        department: str = None,
        min_h_index: int = None,
        has_email: bool = None,
        limit: int = 100
    ) -> List[Professor]:
        """
        Advanced search with multiple filters.
        
        Args:
            name: Search by professor name (partial match)
            university: Filter by university name
            department: Filter by department name
            min_h_index: Minimum h-index threshold
            has_email: Filter by email presence
            limit: Max results
        
        Returns:
            List of matching professors
        """
        with self.get_session() as session:
            query = select(Professor)
            
            filters = []
            
            if name:
                filters.append(Professor.name.ilike(f"%{name}%"))
            
            if min_h_index is not None:
                filters.append(Professor.h_index >= min_h_index)
            
            if has_email is not None:
                if has_email:
                    filters.append(Professor.email.isnot(None))
                else:
                    filters.append(Professor.email.is_(None))
            
            # Join filters for university/department
            if university or department:
                query = query.join(Department).join(University)
                
                if university:
                    filters.append(University.name.ilike(f"%{university}%"))
                if department:
                    filters.append(Department.name.ilike(f"%{department}%"))
            
            if filters:
                query = query.where(and_(*filters))
            
            query = query.limit(limit)
            
            return session.exec(query).all()
    
    def get_statistics(self) -> Dict:
        """
        Get database statistics.
        
        Returns:
            Dict with counts and metrics
        """
        with self.get_session() as session:
            stats = {
                "total_universities": session.exec(
                    select(func.count(University.id))
                ).one(),
                "total_departments": session.exec(
                    select(func.count(Department.id))
                ).one(),
                "total_professors": session.exec(
                    select(func.count(Professor.id))
                ).one(),
                "professors_with_email": session.exec(
                    select(func.count(Professor.id)).where(
                        Professor.email.isnot(None)
                    )
                ).one(),
                "professors_with_scholar": session.exec(
                    select(func.count(Professor.id)).where(
                        Professor.google_scholar_id.isnot(None)
                    )
                ).one(),
                "avg_h_index": session.exec(
                    select(func.avg(Professor.h_index)).where(
                        Professor.h_index > 0
                    )
                ).one() or 0,
            }
            
            return stats
    
    def get_top_professors(
        self,
        metric: str = "h_index",
        limit: int = 10
    ) -> List[Professor]:
        """
        Get top professors by metric.
        
        Args:
            metric: 'h_index' or 'total_citations'
            limit: Number of results
        
        Returns:
            List of top professors
        """
        with self.get_session() as session:
            if metric == "h_index":
                query = select(Professor).where(
                    Professor.h_index > 0
                ).order_by(Professor.h_index.desc())
            else:
                query = select(Professor).where(
                    Professor.total_citations > 0
                ).order_by(Professor.total_citations.desc())
            
            query = query.limit(limit)
            return session.exec(query).all()
    
    def find_duplicates(self) -> List[Tuple[str, int]]:
        """
        Find potential duplicate professors (same name, different records).
        
        Returns:
            List of (name, count) tuples
        """
        with self.get_session() as session:
            query = select(
                Professor.name,
                func.count(Professor.id).label('count')
            ).group_by(
                Professor.name
            ).having(
                func.count(Professor.id) > 1
            ).order_by(
                func.count(Professor.id).desc()
            )
            
            return session.exec(query).all()
    
    def get_universities_with_counts(self) -> List[Dict]:
        """
        Get all universities with professor counts.
        
        Returns:
            List of dicts with university info and counts
        """
        with self.get_session() as session:
            results = session.exec(
                select(
                    University,
                    func.count(distinct(Department.id)).label('dept_count'),
                    func.count(Professor.id).label('prof_count')
                )
                .outerjoin(Department)
                .outerjoin(Professor)
                .group_by(University.id)
            ).all()
            
            return [
                {
                    "id": uni.id,
                    "name": uni.name,
                    "website": uni.website,
                    "departments": dept_count,
                    "professors": prof_count
                }
                for uni, dept_count, prof_count in results
            ]
    
    # =========================================================================
    # Maintenance Operations
    # =========================================================================
    
    def cleanup_empty_departments(self) -> int:
        """
        Remove departments with no professors.
        
        Returns:
            Number of departments removed
        """
        with self.get_session() as session:
            empty_depts = session.exec(
                select(Department)
                .outerjoin(Professor)
                .group_by(Department.id)
                .having(func.count(Professor.id) == 0)
            ).all()
            
            count = len(empty_depts)
            for dept in empty_depts:
                session.delete(dept)
            
            session.commit()
            logger.info(f"Cleaned up {count} empty departments")
            return count
    
    def merge_duplicate_professors(
        self,
        keep_id: int,
        remove_id: int
    ) -> bool:
        """
        Merge two professor records, keeping the better data.
        
        Args:
            keep_id: ID of professor to keep
            remove_id: ID of professor to remove
        
        Returns:
            Success status
        """
        with self.get_session() as session:
            keep = session.get(Professor, keep_id)
            remove = session.get(Professor, remove_id)
            
            if not keep or not remove:
                return False
            
            # Merge data
            self._update_professor(keep, remove)
            
            # Delete duplicate
            session.delete(remove)
            session.commit()
            
            logger.info(f"Merged professor {remove_id} into {keep_id}")
            return True


# Singleton instance
_db_manager = None

def get_db_manager() -> DatabaseManager:
    """Get singleton database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
