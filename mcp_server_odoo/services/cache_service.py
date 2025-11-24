"""Cache service for Odoo MCP Server."""

import time
from typing import Any, Dict, Optional, Union
from threading import Lock
from ..config import get_config
from ..logger import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """Cache entry with TTL support."""
    
    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        if self.ttl <= 0:  # Never expires
            return False
        return time.time() - self.created_at > self.ttl


class CacheService:
    """Simple in-memory cache service with TTL support."""
    
    def __init__(self):
        self.config = get_config().cache
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        logger.info(f"Cache service initialized - enabled: {self.config.enabled}, TTL: {self.config.ttl}s, max_size: {self.config.max_size}")
    
    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        if not self.config.enabled:
            return
            
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def _evict_lru(self) -> None:
        """Evict least recently used entries if cache is full."""
        if len(self._cache) <= self.config.max_size:
            return
            
        # Simple LRU: remove oldest entries
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].created_at
        )
        
        entries_to_remove = len(self._cache) - self.config.max_size + 1
        for i in range(entries_to_remove):
            key = sorted_entries[i][0]
            del self._cache[key]
            
        logger.debug(f"Evicted {entries_to_remove} LRU cache entries")
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self.config.enabled:
            return None
            
        with self._lock:
            self._cleanup_expired()
            
            entry = self._cache.get(key)
            if entry is None:
                logger.debug(f"Cache miss: {key}")
                return None
                
            if entry.is_expired():
                del self._cache[key]
                logger.debug(f"Cache expired: {key}")
                return None
                
            logger.debug(f"Cache hit: {key}")
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache."""
        if not self.config.enabled:
            return
            
        if ttl is None:
            ttl = self.config.ttl
            
        with self._lock:
            self._cleanup_expired()
            self._evict_lru()
            
            self._cache[key] = CacheEntry(value, ttl)
            logger.debug(f"Cache set: {key} (TTL: {ttl}s)")
    
    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        if not self.config.enabled:
            return False
            
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache delete: {key}")
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {count} entries removed")
    
    def stats(self) -> Dict[str, Union[int, bool]]:
        """Get cache statistics."""
        with self._lock:
            self._cleanup_expired()
            return {
                "enabled": self.config.enabled,
                "size": len(self._cache),
                "max_size": self.config.max_size,
                "ttl": self.config.ttl,
            }
    
    def generate_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments."""
        key_parts = []
        
        # Add positional arguments
        for arg in args:
            if isinstance(arg, (str, int, float, bool)):
                key_parts.append(str(arg))
            elif isinstance(arg, (list, tuple)):
                key_parts.append(str(sorted(arg) if isinstance(arg, list) else arg))
            elif isinstance(arg, dict):
                key_parts.append(str(sorted(arg.items())))
            else:
                key_parts.append(str(arg))
        
        # Add keyword arguments
        for k, v in sorted(kwargs.items()):
            if isinstance(v, (str, int, float, bool)):
                key_parts.append(f"{k}:{v}")
            elif isinstance(v, (list, tuple)):
                key_parts.append(f"{k}:{sorted(v) if isinstance(v, list) else v}")
            elif isinstance(v, dict):
                key_parts.append(f"{k}:{sorted(v.items())}")
            else:
                key_parts.append(f"{k}:{v}")
        
        return "|".join(key_parts)


# Global cache service instance
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get or create global cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
