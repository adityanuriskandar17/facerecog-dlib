import redis
import pickle
import numpy as np
from typing import List, Tuple, Optional

from ..config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD

# Redis configuration
REDIS_ENABLED = True
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=False
    )
    # Test connection
    redis_client.ping()
    print("[REDIS] Connected successfully")
except Exception as e:
    print(f"[REDIS] Connection failed: {e}")
    REDIS_ENABLED = False
    redis_client = None

def get_cached_encodings() -> Tuple[List[np.ndarray], List[str], List[int]]:
    """Get cached encodings from Redis"""
    if not REDIS_ENABLED:
        return [], [], []
    
    try:
        # Get cached data
        cached_encodings = redis_client.get('face_encodings')
        cached_names = redis_client.get('face_names')
        cached_member_ids = redis_client.get('face_member_ids')
        
        if cached_encodings and cached_names and cached_member_ids:
            encodings = pickle.loads(cached_encodings)
            names = pickle.loads(cached_names)
            member_ids = pickle.loads(cached_member_ids)
            
            print(f"[REDIS] Retrieved cached encodings: {len(encodings)}")
            return encodings, names, member_ids
        else:
            print("[REDIS] No cached encodings found")
            return [], [], []
            
    except Exception as e:
        print(f"[REDIS] Error getting cached encodings: {e}")
        return [], [], []

def cache_encodings(encodings: List[np.ndarray], names: List[str], member_ids: List[int]):
    """Cache encodings to Redis"""
    if not REDIS_ENABLED:
        return
    
    try:
        # Serialize data
        encodings_bytes = pickle.dumps(encodings)
        names_bytes = pickle.dumps(names)
        member_ids_bytes = pickle.dumps(member_ids)
        
        # Store in Redis with expiration (1 hour)
        redis_client.setex('face_encodings', 3600, encodings_bytes)
        redis_client.setex('face_names', 3600, names_bytes)
        redis_client.setex('face_member_ids', 3600, member_ids_bytes)
        
        print(f"[REDIS] Cached {len(encodings)} encodings")
        
    except Exception as e:
        print(f"[REDIS] Error caching encodings: {e}")

def clear_redis_cache():
    """Clear Redis cache"""
    if not REDIS_ENABLED:
        return {"success": False, "error": "Redis not available"}
    
    try:
        redis_client.delete('face_encodings', 'face_names', 'face_member_ids')
        return {"success": True, "message": "Cache cleared"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_redis_status():
    """Get Redis status"""
    if not REDIS_ENABLED:
        return {"connected": False, "error": "Redis not available"}
    
    try:
        # Test connection
        redis_client.ping()
        
        # Get cache info
        cached_encodings = redis_client.get('face_encodings')
        cache_size = len(cached_encodings) if cached_encodings else 0
        
        return {
            "connected": True,
            "cache_size": cache_size,
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "db": REDIS_DB
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}

def redis_reload():
    """Reload Redis cache"""
    if not REDIS_ENABLED:
        return {"success": False, "error": "Redis not available"}
    
    try:
        from .recognition_service import recognizer
        recognizer.reload()
        return {"success": True, "message": "Redis cache reloaded"}
    except Exception as e:
        return {"success": False, "error": str(e)}
