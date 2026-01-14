"""
SQLite-backed schema cache for CSS extraction schemas.

Caches successful schemas per domain to avoid repeated LLM calls.
"""

import json
import sqlite3
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse


@dataclass
class SelectorSchema:
    """CSS selector schema for faculty extraction."""
    base_selector: str
    fields: Dict[str, str]
    
    def to_dict(self) -> dict:
        return {
            "base_selector": self.base_selector,
            "fields": self.fields
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SelectorSchema":
        return cls(
            base_selector=data.get("base_selector", ""),
            fields=data.get("fields", {})
        )


class SchemaCache:
    """
    SQLite-backed cache for CSS extraction schemas.
    
    Features:
    - Stores successful schemas per domain
    - Auto-invalidates after TTL (default 7 days)
    - Tracks success/failure counts for quality scoring
    """
    
    def __init__(self, db_path: str = None, ttl_days: int = 7):
        """
        Initialize the schema cache.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.insti_scraper/schema_cache.db
            ttl_days: Number of days before schema expires
        """
        if db_path is None:
            cache_dir = Path.home() / ".insti_scraper"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / "schema_cache.db")
        
        self.db_path = db_path
        self.ttl_days = ttl_days
        self._init_db()
    
    def _init_db(self):
        """Create the schemas table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schemas (
                    domain TEXT PRIMARY KEY,
                    schema_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    fail_count INTEGER DEFAULT 0,
                    avg_items_extracted REAL DEFAULT 0
                )
            """)
            conn.commit()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def get(self, url_or_domain: str) -> Optional[SelectorSchema]:
        """
        Get cached schema for a domain.
        
        Args:
            url_or_domain: URL or domain to look up
            
        Returns:
            SelectorSchema if found and not expired, None otherwise
        """
        domain = self._get_domain(url_or_domain) if "://" in url_or_domain else url_or_domain
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT schema_json, created_at, success_count, fail_count FROM schemas WHERE domain = ?",
                (domain,)
            )
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            schema_json, created_at, success_count, fail_count = row
            
            # Check if expired
            created = datetime.fromisoformat(created_at)
            if datetime.now() - created > timedelta(days=self.ttl_days):
                # Expired, delete and return None
                conn.execute("DELETE FROM schemas WHERE domain = ?", (domain,))
                conn.commit()
                return None
            
            # Check quality - invalidate if too many failures
            if fail_count > 3 and fail_count > success_count:
                conn.execute("DELETE FROM schemas WHERE domain = ?", (domain,))
                conn.commit()
                return None
            
            try:
                schema_data = json.loads(schema_json)
                return SelectorSchema.from_dict(schema_data)
            except json.JSONDecodeError:
                return None
    
    def save(
        self, 
        url_or_domain: str, 
        schema: SelectorSchema,
        items_extracted: int = 0
    ):
        """
        Save a schema to the cache.
        
        Args:
            url_or_domain: URL or domain
            schema: The selector schema to cache
            items_extracted: Number of items successfully extracted (for quality tracking)
        """
        domain = self._get_domain(url_or_domain) if "://" in url_or_domain else url_or_domain
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Check if exists
            cursor = conn.execute(
                "SELECT success_count, avg_items_extracted FROM schemas WHERE domain = ?",
                (domain,)
            )
            row = cursor.fetchone()
            
            if row:
                # Update existing
                old_count, old_avg = row
                new_count = old_count + 1
                new_avg = ((old_avg * old_count) + items_extracted) / new_count
                
                conn.execute("""
                    UPDATE schemas 
                    SET schema_json = ?, updated_at = ?, success_count = ?, avg_items_extracted = ?
                    WHERE domain = ?
                """, (json.dumps(schema.to_dict()), now, new_count, new_avg, domain))
            else:
                # Insert new
                conn.execute("""
                    INSERT INTO schemas (domain, schema_json, created_at, updated_at, success_count, avg_items_extracted)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (domain, json.dumps(schema.to_dict()), now, now, items_extracted))
            
            conn.commit()
    
    def record_failure(self, url_or_domain: str):
        """Record a failed extraction for quality tracking."""
        domain = self._get_domain(url_or_domain) if "://" in url_or_domain else url_or_domain
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE schemas SET fail_count = fail_count + 1 WHERE domain = ?
            """, (domain,))
            conn.commit()
    
    def invalidate(self, url_or_domain: str):
        """Force invalidate a cached schema."""
        domain = self._get_domain(url_or_domain) if "://" in url_or_domain else url_or_domain
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM schemas WHERE domain = ?", (domain,))
            conn.commit()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_schemas,
                    SUM(success_count) as total_successes,
                    SUM(fail_count) as total_failures,
                    AVG(avg_items_extracted) as avg_items
                FROM schemas
            """)
            row = cursor.fetchone()
            
            return {
                "total_schemas": row[0] or 0,
                "total_successes": row[1] or 0,
                "total_failures": row[2] or 0,
                "avg_items_extracted": row[3] or 0,
                "cache_file": self.db_path
            }
    
    def list_domains(self) -> list:
        """List all cached domains."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT domain, success_count, fail_count, created_at FROM schemas ORDER BY success_count DESC"
            )
            return [
                {
                    "domain": row[0],
                    "success_count": row[1],
                    "fail_count": row[2],
                    "created_at": row[3]
                }
                for row in cursor.fetchall()
            ]


# Global cache instance
_cache_instance: Optional[SchemaCache] = None


def get_schema_cache() -> SchemaCache:
    """Get or create the global schema cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SchemaCache()
    return _cache_instance
