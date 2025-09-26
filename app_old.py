import os
import io
import time
import threading
import gc
import signal
from typing import Dict, List, Tuple
from collections import OrderedDict

import cv2
import numpy as np
import requests
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from flask import Flask, Response, render_template, render_template_string, session, redirect, url_for
import redis
import pickle
import json

# ==== Dlib via face_recognition ====
import face_recognition  # built on top of dlib

# ===================== Config =====================
load_dotenv()

MYSQL_HOST = os.getenv("DB_HOST", "")
MYSQL_PORT = int(os.getenv("DB_PORT", ""))
MYSQL_DATABASE = os.getenv("DB_NAME", "")
MYSQL_USER = os.getenv("DB_USER", "")
MYSQL_PASSWORD = os.getenv("DB_PASSWORD", "")

TOLERANCE = 0.40  # tighten threshold to reduce false positives
TOP2_MARGIN = 0.06  # require best vs second-best distance gap
REQUIRED_CONSISTENT_FRAMES = 2  # require N consecutive frames for same identity

# Jika ingin batasi request gambar (detik)
REQUEST_TIMEOUT = 15

# Ukuran batch regenerasi encoding
BATCH_SIZE = int(os.getenv("ENC_BATCH_SIZE", "50"))

# Redis Configuration
REDIS_HOST = "localhost "
REDIS_PORT = 6379
REDIS_PASSWORD = ""
REDIS_DB = 0
REDIS_ENABLED = True

# Gym API Configuration
GYM_API_KEY = os.getenv("API_KEY", "")
GYM_DOOR_ID = os.getenv("DOOR_", "19456")
GYM_LOGIN_URL = os.getenv("LOGIN_URL", "")
GYM_GATE_URL = ""
CHECKIN_ENABLED = False
GYM_PROFILE_URL = "https://ftl.gymmasteronline.com//portal/api/v1/member/profile"

# Auth Configuration
AUTH_EMAIL = os.getenv("AUTH_EMAIL", "admin@example.com").strip().lower()
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "admin123")

# Flask session secret key
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")

# Store door IDs per session/device
device_door_ids = {}

# Track member IDs that returned 404 during this runtime to skip in next batches
failed_404_member_ids = set()

# Redis connection
redis_client = None

# Rate limiting for face recognition to prevent memory overload
last_face_recognition_time = 0
FACE_RECOGNITION_COOLDOWN = 0.1  # 100ms cooldown between face recognition calls

# Memory management for dlib
def force_garbage_collection():
    """Force garbage collection to prevent memory issues"""
    gc.collect()
    gc.collect()  # Call twice to ensure cleanup

def check_memory_usage():
    """Check current memory usage and force cleanup if needed"""
    try:
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        print(f"[MEMORY] Current memory usage: {memory_mb:.1f} MB")
        
        # If memory usage is too high, force cleanup
        if memory_mb > 1000:  # 1GB threshold
            print(f"[MEMORY] High memory usage detected, forcing cleanup...")
            force_garbage_collection()
            
        return memory_mb
    except ImportError:
        print(f"[MEMORY] psutil not available, skipping memory check")
        return 0
    except Exception as e:
        print(f"[MEMORY] Error checking memory usage: {e}")
        return 0

def safe_face_recognition(func_name, *args, **kwargs):
    """Safe wrapper for face_recognition functions with aggressive memory management"""
    global last_face_recognition_time
    
    # Rate limiting to prevent memory overload
    current_time = time.time()
    time_since_last = current_time - last_face_recognition_time
    if time_since_last < FACE_RECOGNITION_COOLDOWN:
        sleep_time = FACE_RECOGNITION_COOLDOWN - time_since_last
        time.sleep(sleep_time)
    
    last_face_recognition_time = time.time()
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Force cleanup before each attempt
            force_garbage_collection()
            
            if func_name == "face_locations":
                result = face_recognition.face_locations(*args, **kwargs)
            elif func_name == "face_encodings":
                result = face_recognition.face_encodings(*args, **kwargs)
            elif func_name == "face_distance":
                result = face_recognition.face_distance(*args, **kwargs)
            else:
                raise ValueError(f"Unknown function: {func_name}")
            
            # Force cleanup after successful call
            force_garbage_collection()
            return result
            
        except Exception as e:
            print(f"[MEMORY] Error in {func_name} (attempt {attempt + 1}): {e}")
            force_garbage_collection()
            
            # If it's a memory corruption error, try to recover
            if "malloc" in str(e) or "corrupted" in str(e) or "double linked" in str(e):
                print(f"[MEMORY] Memory corruption detected, attempting recovery...")
                force_garbage_collection()
                time.sleep(0.2)  # Longer delay for memory corruption
                
                if attempt == max_retries - 1:
                    print(f"[MEMORY] Max retries reached, returning empty result")
                    if func_name == "face_locations":
                        return []
                    elif func_name == "face_encodings":
                        return []
                    elif func_name == "face_distance":
                        return []
                    else:
                        return None
            else:
                raise

def signal_handler(signum, frame):
    """Handle signals gracefully"""
    print(f"[SIGNAL] Received signal {signum}, cleaning up...")
    force_garbage_collection()
    exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ===================== Redis Functions =====================

def get_redis_client():
    """Get Redis client connection"""
    global redis_client
    if redis_client is None and REDIS_ENABLED:
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD if REDIS_PASSWORD else None,
                db=REDIS_DB,
                decode_responses=False,  # Keep binary for numpy arrays
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            redis_client.ping()
            print(f"[REDIS] Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"[REDIS] Failed to connect to Redis: {e}")
            redis_client = None
    return redis_client

def cache_encodings(encodings: List[np.ndarray], names: List[str], member_ids: List[int], cache_key: str = "face_encodings"):
    """Cache encodings to Redis"""
    if not REDIS_ENABLED:
        return False
    
    try:
        client = get_redis_client()
        if client is None:
            return False
        
        # Serialize data
        data = {
            'encodings': [enc.tobytes() for enc in encodings],
            'names': names,
            'member_ids': member_ids,
            'timestamp': time.time()
        }
        
        # Store with 1 hour expiration
        serialized_data = pickle.dumps(data)
        client.setex(cache_key, 3600, serialized_data)
        print(f"[REDIS] Cached {len(encodings)} encodings with key: {cache_key}")
        return True
    except Exception as e:
        print(f"[REDIS] Failed to cache encodings: {e}")
        return False

def get_cached_encodings(cache_key: str = "face_encodings") -> Tuple[List[np.ndarray], List[str], List[int]]:
    """Get cached encodings from Redis"""
    if not REDIS_ENABLED:
        return [], [], []
    
    try:
        client = get_redis_client()
        if client is None:
            return [], [], []
        
        # Get cached data
        cached_data = client.get(cache_key)
        if cached_data is None:
            print(f"[REDIS] No cached encodings found with key: {cache_key}")
            return [], [], []
        
        # Deserialize data
        data = pickle.loads(cached_data)
        
        # Convert bytes back to numpy arrays
        encodings = [np.frombuffer(enc_bytes, dtype=np.float64) for enc_bytes in data['encodings']]
        names = data['names']
        member_ids = data['member_ids']
        
        print(f"[REDIS] Retrieved {len(encodings)} cached encodings (cached at: {data.get('timestamp', 'unknown')})")
        return encodings, names, member_ids
    except Exception as e:
        print(f"[REDIS] Failed to get cached encodings: {e}")
        return [], [], []

def invalidate_encodings_cache(cache_key: str = "face_encodings"):
    """Invalidate encodings cache"""
    if not REDIS_ENABLED:
        return False
    
    try:
        client = get_redis_client()
        if client is None:
            return False
        
        client.delete(cache_key)
        print(f"[REDIS] Invalidated cache with key: {cache_key}")
        return True
    except Exception as e:
        print(f"[REDIS] Failed to invalidate cache: {e}")
        return False


# ===================== DB Helpers =====================
def get_conn():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        autocommit=True,
    )

def fetch_member_images() -> List[Tuple[int, str, str, str]]:
    """
    Ambil (member_id, first_name, last_name, full_url) untuk foto terbaru per member Staff Membership (EA1M-FTL).
    """
    sql = """
    WITH latest_profile AS (
      SELECT
        f2.*,
        ROW_NUMBER() OVER (
          PARTITION BY f2.member_id
          ORDER BY f2.created_at DESC, f2.id DESC
        ) AS rn
      FROM member_file f2
      WHERE (f2.status IS NULL OR f2.status = 1)
        AND (f2.file_type_id IS NULL OR f2.file_type_id = 1)
        AND f2.title = 'Profile'
        AND f2.file_base_url LIKE 'https://ftlhorizon.com/%'
    )
    SELECT
      m.id AS member_pk,
      m.member_id AS gym_member_id,
      COALESCE(m.first_name, CONCAT('Member_', m.id)) AS first_name,
      COALESCE(m.last_name, '') AS last_name,
      CONCAT_WS('', f.file_base_url, f.file_base_path, f.file_path, f.file_name) AS full_url
    FROM member m
    JOIN member_package mp ON mp.member_id = m.id
    JOIN package p        ON p.id = mp.package_id AND p.code = 'EA1M-FTL'
    JOIN latest_profile f ON f.member_id = m.id AND f.rn = 1
    WHERE m.status = 1
    ORDER BY m.id ASC
    """
    rows: List[Tuple[int, int, str, str, str]] = []
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Error as e:
        print(f"[DB] Error: {e}")
        return []

    return [(member_id, gym_member_id, first_name, last_name, full_url) for member_id, gym_member_id, first_name, last_name, full_url in rows]

# ===================== Image / Encoding =====================
def url_to_rgb_array(url: str) -> np.ndarray:
    """
    Download image from URL (supports querystrings), return RGB numpy array.
    Raises on error / if not an image.
    """
    resp = None
    data = None
    bgr = None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = np.frombuffer(resp.content, dtype=np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Gagal decode image dari URL")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return rgb
    finally:
        # Clean up memory
        if resp is not None:
            del resp
        if data is not None:
            del data
        if bgr is not None:
            del bgr
        force_garbage_collection()

def add_enc_field_to_member_table():
    """
    Add 'enc' field to member table if it doesn't exist
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if enc field exists
        cur.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'member' AND COLUMN_NAME = 'enc'
        """, (MYSQL_DATABASE,))
        
        if not cur.fetchone():
            print("[DB] Adding 'enc' field to member table...")
            cur.execute("ALTER TABLE member ADD COLUMN enc LONGBLOB NULL")
            conn.commit()
            print("[DB] 'enc' field added successfully")
        else:
            print("[DB] 'enc' field already exists")
        
        cur.close()
        conn.close()
    except Error as e:
        print(f"[DB] Error adding enc field: {e}")

def save_encoding_to_db(member_id: int, encoding: np.ndarray):
    """
    Save face encoding to member table
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Convert numpy array to binary
        encoding_bytes = encoding.tobytes()
        
        cur.execute("UPDATE member SET enc = %s WHERE id = %s", (encoding_bytes, member_id))
        conn.commit()
        
        cur.close()
        conn.close()
        print(f"[DB] Saved encoding for member_id={member_id}")
    except Error as e:
        print(f"[DB] Error saving encoding for member_id={member_id}: {e}")

def load_encoding_from_db(member_id: int) -> np.ndarray:
    """
    Load face encoding from member table
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT enc FROM member WHERE id = %s", (member_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result and result[0]:
            encoding = np.frombuffer(result[0], dtype=np.float64)
            # Validate encoding size (should be 128 for face_recognition)
            if len(encoding) == 128:
                return encoding
            else:
                print(f"[DB] Invalid encoding size for member_id={member_id}: {len(encoding)}")
                return None
        return None
    except Error as e:
        print(f"[DB] Error loading encoding for member_id={member_id}: {e}")
        return None

 

def regenerate_missing_encodings(batch_size: int = BATCH_SIZE, regenerate_all: bool = False):
    """
    Regenerate ENC in batches.
    If regenerate_all is True, process all active members regardless of existing enc.
    Otherwise, only members missing or with invalid enc are processed.
    """
    mode_text = "all members" if regenerate_all else "members missing encodings"
    print(f"[ENC] Starting regeneration for {mode_text} in batches of {batch_size}...")
    try:
        total_success = 0
        total_error = 0
        batch_index = 0
        total_to_process = None

        try:
            conn_count = get_conn()
            cur_count = conn_count.cursor()
            count_sql = """
                SELECT COUNT(*)
                FROM member m
                JOIN member_package mp ON mp.member_id = m.id
                JOIN package p ON p.id = mp.package_id
                WHERE p.code = 'EA1M-FTL'
                  AND m.status = 1
            """
            params_count = []
            if not regenerate_all:
                count_sql += "\n                  AND (m.enc IS NULL OR LENGTH(m.enc) != 1024)\n"
            cur_count.execute(count_sql, params_count)
            row = cur_count.fetchone()
            total_to_process = int(row[0]) if row else 0
            cur_count.close()
            conn_count.close()
            print(f"[ENC] Total members to process: {total_to_process}")
        except Exception as e:
            print(f"[ENC] Unable to compute total to process: {e}")
            total_to_process = None

        processed_total = 0
        while True:
            conn = get_conn()
            cur = conn.cursor()
            base_sql = """
                WITH latest_profile AS (
                  SELECT
                    f2.*,
                    ROW_NUMBER() OVER (
                      PARTITION BY f2.member_id
                      ORDER BY f2.created_at DESC, f2.id DESC
                    ) AS rn
                  FROM member_file f2
                  WHERE (f2.status IS NULL OR f2.status = 1)
                    AND (f2.file_type_id IS NULL OR f2.file_type_id = 1)
                    AND f2.title = 'Profile'
                    AND f2.file_base_url LIKE 'https://ftlhorizon.com/%'
                )
                SELECT 
                  m.id AS member_pk,
                  m.member_id AS gym_member_id,
                  COALESCE(m.first_name, CONCAT('Member_', m.id)) AS first_name,
                  COALESCE(m.last_name, '') AS last_name,
                  CONCAT_WS('', f.file_base_url, f.file_base_path, f.file_path, f.file_name) AS full_url
                FROM member m
                JOIN member_package mp ON mp.member_id = m.id
                JOIN package p ON p.id = mp.package_id
                JOIN latest_profile f ON f.member_id = m.id AND f.rn = 1
                WHERE p.code = 'EA1M-FTL'
                  AND m.status = 1
 """
            params = []
            if not regenerate_all:
                base_sql += "\n                  AND (m.enc IS NULL OR LENGTH(m.enc) != 1024)\n"
            if failed_404_member_ids:
                placeholders = ",".join(["%s"] * len(failed_404_member_ids))
                base_sql += f" AND m.id NOT IN ({placeholders})"
                params.extend(list(failed_404_member_ids))
            base_sql += " ORDER BY m.id ASC LIMIT %s"
            params.append(int(batch_size))
            cur.execute(base_sql, params)
            members = cur.fetchall()
            cur.close()
            conn.close()

            if not members:
                print("[ENC] No more members to process")
                break

            batch_index += 1
            print(f"[ENC] Processing batch {batch_index} with {len(members)} members...")
            batch_success = 0
            batch_error = 0

            for member_id, gym_member_id, first_name, last_name, full_url in members:
                try:
                    img = url_to_rgb_array(full_url)
                    boxes = safe_face_recognition("face_locations", img, model="hog")
                    if not boxes:
                        batch_error += 1
                        processed_total += 1
                        if total_to_process and total_to_process > 0:
                            pct = int(processed_total * 100 / total_to_process)
                            print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} no-face")
                        else:
                            print(f"[ENC] Progress {processed_total} processed member_id={member_id} no-face")
                        continue
                    encoding = safe_face_recognition("face_encodings", img, known_face_locations=[boxes[0]])
                    if not encoding:
                        batch_error += 1
                        processed_total += 1
                        if total_to_process and total_to_process > 0:
                            pct = int(processed_total * 100 / total_to_process)
                            print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} encode-failed")
                        else:
                            print(f"[ENC] Progress {processed_total} processed member_id={member_id} encode-failed")
                        continue
                    save_encoding_to_db(member_id, encoding[0])
                    batch_success += 1
                    processed_total += 1
                    if total_to_process and total_to_process > 0:
                        pct = int(processed_total * 100 / total_to_process)
                        print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} success")
                    else:
                        print(f"[ENC] Progress {processed_total} processed member_id={member_id} success")
                except requests.exceptions.HTTPError as e:
                    status = getattr(e.response, 'status_code', None)
                    if status == 404 or '404' in str(e):
                        failed_404_member_ids.add(member_id)
                        batch_error += 1
                        processed_total += 1
                        if total_to_process and total_to_process > 0:
                            pct = int(processed_total * 100 / total_to_process)
                            print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} http-404")
                        else:
                            print(f"[ENC] Progress {processed_total} processed member_id={member_id} http-404")
                        continue
                    print(f"[ENC] HTTP error for member_id={member_id}: {e}")
                    batch_error += 1
                    processed_total += 1
                    if total_to_process and total_to_process > 0:
                        pct = int(processed_total * 100 / total_to_process)
                        print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} http-error")
                    else:
                        print(f"[ENC] Progress {processed_total} processed member_id={member_id} http-error")
                except Exception as e:
                    print(f"[ENC] Error regenerating encoding for member_id={member_id}: {e}")
                    batch_error += 1
                    processed_total += 1
                    if total_to_process and total_to_process > 0:
                        pct = int(processed_total * 100 / total_to_process)
                        print(f"[ENC] Progress {processed_total}/{total_to_process} ({pct}%) member_id={member_id} error")
                    else:
                        print(f"[ENC] Progress {processed_total} processed member_id={member_id} error")

            total_success += batch_success
            total_error += batch_error
            print(f"[ENC] Batch {batch_index} done. Success: {batch_success}, Errors: {batch_error}")

            if batch_success == 0 and len(members) > 0:
                print("[ENC] No successful encodings in this batch, stopping to avoid loop")
                break

        print(f"[ENC] Regeneration complete. Success: {total_success}, Errors: {total_error}")
        return {"success": True, "success_count": total_success, "error_count": total_error}
    except Error as e:
        print(f"[ENC] Database error during regeneration: {e}")
        return {"success": False, "error": str(e)}

def build_known_encodings() -> Tuple[List[np.ndarray], List[str], List[int], Dict[int, int]]:
    """
    Return (encodings, names, member_ids, gym_member_id_mapping)
    - Load from database first, generate if not exists
    """
    # Ensure enc field exists
    add_enc_field_to_member_table()
    
    sources = fetch_member_images()
    encodings: List[np.ndarray] = []
    names: List[str] = []
    member_ids: List[int] = []
    gym_member_id_mapping: Dict[int, int] = {}  # member_id -> gym_member_id
    skipped: List[Tuple[int, str]] = []

    print(f"[ENC] Mulai load {len(sources)} member image(s)")
    for member_id, gym_member_id, first_name, last_name, full_url in sources:
        try:
            # Try to load from database first
            stored_encoding = load_encoding_from_db(member_id)
            
            # Create full name
            full_name = f"{first_name.strip()} {last_name.strip()}".strip()
            if not full_name or full_name == " ":
                full_name = first_name.strip() or f"Member_{member_id}"
            
            if stored_encoding is not None:
                # Use stored encoding
                encodings.append(stored_encoding)
                names.append(full_name)
                member_ids.append(member_id)
                gym_member_id_mapping[member_id] = gym_member_id
                print(f"[ENC] Loaded from DB member_id={member_id} name={names[-1]}")
            else:
                # Generate new encoding from image if not in DB
                print(f"[ENC] Generating new encoding for member_id={member_id}")
                img = url_to_rgb_array(full_url)
                boxes = safe_face_recognition("face_locations", img, model="hog")
                
                if not boxes:
                    print(f"[ENC] Wajah tidak ditemukan di member_id={member_id} url={full_url}")
                    skipped.append((member_id, "no_face"))
                    continue
                    
                # Ambil wajah pertama
                encoding = safe_face_recognition("face_encodings", img, known_face_locations=[boxes[0]])
                if not encoding:
                    print(f"[ENC] Encoding gagal di member_id={member_id}")
                    skipped.append((member_id, "no_encoding"))
                    continue
                    
                # Save to database
                save_encoding_to_db(member_id, encoding[0])
                
                encodings.append(encoding[0])
                names.append(full_name)
                member_ids.append(member_id)
                gym_member_id_mapping[member_id] = gym_member_id
                print(f"[ENC] Generated & saved member_id={member_id} name={names[-1]}")
                
        except Exception as e:
            print(f"[ENC] Error for member_id={member_id}: {e}")
            skipped.append((member_id, "error"))

    print(f"[ENC] Selesai. OK={len(encodings)} Skip={len(skipped)}")
    return encodings, names, member_ids, gym_member_id_mapping

def build_known_encodings_fast() -> Tuple[List[np.ndarray], List[str], List[int], Dict[int, int]]:
    """
    Ultra fast version - bulk load all encodings from database with cache
    """
    sources = fetch_member_images()
    encodings: List[np.ndarray] = []
    names: List[str] = []
    member_ids: List[int] = []
    gym_member_id_mapping: Dict[int, int] = {}  # member_id -> gym_member_id
    skipped = 0

    print(f"[ENC] Ultra fast load {len(sources)} member(s) - bulk DB query")
    
    # Create mapping of member_id to source data
    source_map = {}
    for member_id, gym_member_id, first_name, last_name, full_url in sources:
        source_map[member_id] = (gym_member_id, first_name, last_name)
    
    # Bulk load all encodings from database
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get all member IDs that have sources
        member_id_list = list(source_map.keys())
        placeholders = ','.join(['%s'] * len(member_id_list))
        
        cur.execute(
            f"""
            SELECT id, enc 
            FROM member 
            WHERE id IN ({placeholders}) 
            AND enc IS NOT NULL 
            AND LENGTH(enc) = 1024
            """,
            member_id_list
        )
        
        # Create encoding cache
        encoding_cache = {}
        for db_member_id, enc_data in cur.fetchall():
            try:
                # Decode the encoding
                encoding_array = np.frombuffer(enc_data, dtype=np.float64)
                encoding_cache[db_member_id] = encoding_array
            except Exception as e:
                print(f"[ENC] Error decoding encoding for member_id={db_member_id}: {e}")
        
        cur.close()
        conn.close()
        
        print(f"[ENC] Loaded {len(encoding_cache)} encodings from DB cache")
        
        # Process each source with cached encoding
        for member_id in member_id_list:
            try:
                if member_id in encoding_cache:
                    # Use cached encoding
                    stored_encoding = encoding_cache[member_id]
                    gym_member_id, first_name, last_name = source_map[member_id]
                    
                    # Create full name
                    full_name = f"{first_name.strip()} {last_name.strip()}".strip()
                    if not full_name or full_name == " ":
                        full_name = first_name.strip() or f"Member_{member_id}"
                    
                    encodings.append(stored_encoding)
                    names.append(full_name)
                    member_ids.append(member_id)
                    gym_member_id_mapping[member_id] = gym_member_id
                    print(f"[ENC] Loaded from cache member_id={member_id} name={full_name}")
                else:
                    skipped += 1
                    
            except Exception as e:
                print(f"[ENC] Error for member_id={member_id}: {e}")
                skipped += 1
                
    except Exception as e:
        print(f"[ENC] Database error during bulk load: {e}")
        skipped = len(sources)

    print(f"[ENC] Ultra fast load complete. OK={len(encodings)} Skip={skipped}")
    return encodings, names, member_ids, gym_member_id_mapping

# ===================== Gym API Integration =====================
def gym_login(member_id: int) -> dict:
    """
    Login to gym system and get token
    """
    try:
        payload = {
            "api_key": GYM_API_KEY,
            "memberid": member_id
        }
        
        response = requests.post(GYM_LOGIN_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None and data.get("result"):
            token = data["result"]["token"]
            expires = data["result"]["expires"]
            print(f"[GYM] Login successful for member_id={member_id}")
            return {"success": True, "token": token, "expires": expires}
        else:
            print(f"[GYM] Login failed for member_id={member_id}: {data.get('error', 'Unknown error')}")
            return {"success": False, "error": data.get("error", "Unknown error")}
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Login request failed for member_id={member_id}: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Login error for member_id={member_id}: {e}")
        return {"success": False, "error": str(e)}

def gym_open_gate(token: str) -> dict:
    """
    Open gym gate using token
    """
    try:
        if not CHECKIN_ENABLED or not GYM_GATE_URL:
            print("[GYM] GYM_GATE_URL is empty, skip calling gate API")
            return {
                "success": True,
                "message": "Gate call skipped (URL empty)",
                "popup": {
                    "show": True,
                    "style": "INFO",
                    "member_name": "Unknown Member",
                    "member_id": "N/A",
                    "message": "Gate API disabled",
                    "cooldown_duration": 10
                }
            }
        payload = {
            "api_key": GYM_API_KEY,
            "doorid": GYM_DOOR_ID,
            "token": token
        }
        
        
        response = requests.post(GYM_GATE_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None:
            print(f"[GYM] Gate opened successfully")
            return {"success": True, "message": "Gate opened successfully"}
        else:
            print(f"[GYM] Gate open failed: {data.get('error', 'Unknown error')}")
            return {"success": False, "error": data.get("error", "Unknown error")}
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Gate open request failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Gate open error: {e}")
        return {"success": False, "error": str(e)}

def gym_open_gate_with_door(token: str, door_id: str) -> dict:
    """
    Open gym gate using token with specific door ID
    """
    try:
        if not CHECKIN_ENABLED or not GYM_GATE_URL:
            print(f"[GYM] GYM_GATE_URL is empty, skip calling gate API for door {door_id}")
            return {
                "success": True,
                "message": "Gate call skipped (URL empty)",
                "popup": {
                    "show": True,
                    "style": "INFO",
                    "member_name": "Unknown Member",
                    "member_id": "N/A",
                    "message": "Gate API disabled",
                    "cooldown_duration": 10
                }
            }
        payload = {
            "api_key": GYM_API_KEY,
            "doorid": door_id,
            "token": token
        }
        
        print(f"[GYM] Opening gate with door ID: {door_id}")
        response = requests.post(GYM_GATE_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None:
            print(f"[GYM] Gate {door_id} opened successfully")
            result = data.get("result", {}).get("response", {})
            popup_style = result.get("popup_style", "GRANTED")
            member_name = result.get("member_name", "Unknown Member")
            member_id = result.get("member_id", "N/A")
            message = result.get("message", f"Gate {door_id} opened successfully")
            
            return {
                "success": True, 
                "message": message,
                "popup": {
                    "show": True,
                    "style": popup_style,
                    "member_name": member_name,
                    "member_id": member_id,
                    "message": message,
                    "cooldown_duration": 10  # 10 seconds cooldown
                }
            }
        else:
            print(f"[GYM] Gate {door_id} open failed: {data.get('error', 'Unknown error')}")
            result = data.get("result", {}).get("response", {})
            popup_style = result.get("popup_style", "DENIED")
            member_name = result.get("member_name", "Unknown Member")
            member_id = result.get("member_id", "N/A")
            message = result.get("message", f"Gate {door_id} access denied")
            
            return {
                "success": False, 
                "error": data.get("error", "Unknown error"),
                "popup": {
                    "show": True,
                    "style": popup_style,
                    "member_name": member_name,
                    "member_id": member_id,
                    "message": message
                }
            }
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Gate {door_id} open request failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Gate {door_id} open error: {e}")
        return {"success": False, "error": str(e)}

def process_member_detection(member_id: int, member_name: str) -> dict:
    """
    Process member detection: login and open gate
    """
    print(f"[GYM] Processing detection for {member_name} (ID: {member_id})")
    
    # Step 1: Login to get token
    login_result = gym_login(member_id)
    if not login_result["success"]:
        return {"success": False, "error": f"Login failed: {login_result['error']}"}
    
    # Step 2: Open gate using token
    gate_result = gym_open_gate(login_result["token"])
    if not gate_result["success"]:
        return {"success": False, "error": f"Gate open failed: {gate_result['error']}"}
    
    return {"success": True, "message": f"Welcome {member_name}! Gate opened successfully."}

def process_member_detection_with_door(member_id: int, member_name: str, door_id: str) -> dict:
    """
    Process member detection with specific door ID: login and open gate
    """
    print(f"[GYM] Processing detection for {member_name} (ID: {member_id}) with door {door_id}")
    
    # Step 1: Login to get token
    login_result = gym_login(member_id)
    if not login_result["success"]:
        return {"success": False, "error": f"Login failed: {login_result['error']}"}
    
    # Step 2: Open gate using token with specific door ID
    gate_result = gym_open_gate_with_door(login_result["token"], door_id)
    
    # Return the result with popup information
    if gate_result["success"]:
        return {
            "success": True, 
            "message": gate_result["message"],
            "popup": gate_result.get("popup")
        }
    else:
        return {
            "success": False, 
            "error": gate_result["error"],
            "popup": gate_result.get("popup")
        }

# ===================== Video / Recognition =====================
class Recognizer:
    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_names: List[str] = []
        self.known_ids: List[int] = []
        self.gym_member_id_mapping: Dict[int, int] = {}  # member_id -> gym_member_id
        self.lock = threading.Lock()
        self.last_reload = 0
        # Cooldown per device
        self.device_cooldowns: Dict[str, Dict] = {}  # device_id -> {last_login: timestamp, member: name}
        self.cooldown_duration = 5
        self.denied_cooldown_duration = 5
        # Prediction streak per device for multi-frame confirmation
        self.device_prediction_streak: Dict[str, Dict] = {}  # device_id -> {name: str, count: int}
        # Track loaded member IDs for new data detection
        self.loaded_member_ids: set = set()
        # Auto-check interval for new data (seconds)
        self.auto_check_interval = 10  # Check every 10 seconds
        self.last_auto_check = 0

    def reload(self):
        with self.lock:
            # Try to get from Redis cache first
            if REDIS_ENABLED:
                cached_encodings, cached_names, cached_member_ids = get_cached_encodings()
                if cached_encodings:
                    print(f"[RELOAD] Using cached encodings from Redis: {len(cached_encodings)}")
                    self.known_encodings = cached_encodings
                    self.known_names = cached_names
                    self.known_ids = cached_member_ids
                    self.loaded_member_ids = set(self.known_ids)
                    # Build gym_member_id_mapping from database
                    self.gym_member_id_mapping = self._build_gym_member_mapping()
                    self.last_reload = time.time()
                    return
            
            # Fallback to database if no cache
            self.known_encodings, self.known_names, self.known_ids, self.gym_member_id_mapping = build_known_encodings_fast()
            self.last_reload = time.time()
            # Update loaded member IDs
            self.loaded_member_ids = set(self.known_ids)
            print(f"[RELOAD] Loaded {len(self.loaded_member_ids)} member encodings from database")
            
            # Cache to Redis
            if REDIS_ENABLED and self.known_encodings:
                cache_encodings(self.known_encodings, self.known_names, self.known_ids)
    
    def _build_gym_member_mapping(self) -> Dict[int, int]:
        """Build gym_member_id_mapping from database"""
        try:
            conn = get_conn()
            cur = conn.cursor()
            
            if not self.known_ids:
                return {}
            
            placeholders = ','.join(['%s'] * len(self.known_ids))
            cur.execute(
                f"""
                SELECT m.id, m.member_id 
                FROM member m
                WHERE m.id IN ({placeholders})
                """,
                list(self.known_ids)
            )
            
            mapping = {}
            for db_member_id, gym_member_id in cur.fetchall():
                mapping[db_member_id] = gym_member_id
            
            cur.close()
            conn.close()
            return mapping
        except Exception as e:
            print(f"[MAPPING] Error building gym member mapping: {e}")
            return {}
    
    def check_for_new_members(self):
        """
        Check for new members that don't have encodings yet
        """
        current_time = time.time()
        if current_time - self.last_auto_check < self.auto_check_interval:
            return
        
        self.last_auto_check = current_time
        
        try:
            print(f"[AUTO-CHECK] Checking for new members... (loaded: {len(self.loaded_member_ids)})")
            
            # Get all active members with images
            sources = fetch_member_images()
            current_member_ids = {member_id for member_id, _, _, _, _ in sources}
            
            print(f"[AUTO-CHECK] Current DB members: {len(current_member_ids)}")
            print(f"[AUTO-CHECK] Loaded members: {len(self.loaded_member_ids)}")
            
            # Find new members
            new_member_ids = current_member_ids - self.loaded_member_ids
            
            if new_member_ids:
                print(f"[AUTO-CHECK] Found {len(new_member_ids)} new members: {new_member_ids}")
                self.process_new_members(new_member_ids, sources)
            else:
                print(f"[AUTO-CHECK] No new members found")
                
        except Exception as e:
            print(f"[AUTO-CHECK] Error checking for new members: {e}")
            import traceback
            traceback.print_exc()
    
    def process_new_members(self, new_member_ids: set, all_sources: List[Tuple[int, int, str, str, str]]):
        """
        Process new members and generate their encodings
        """
        new_encodings = []
        new_names = []
        new_member_ids_list = []
        new_gym_member_id_mapping = {}
        processed_count = 0
        error_count = 0
        
        print(f"[AUTO-CHECK] Processing {len(new_member_ids)} new members...")
        
        for member_id, gym_member_id, first_name, last_name, full_url in all_sources:
            if member_id not in new_member_ids:
                continue
                
            try:
                # Check if encoding already exists in DB
                stored_encoding = load_encoding_from_db(member_id)
                
                # Create full name
                full_name = f"{first_name.strip()} {last_name.strip()}".strip()
                if not full_name or full_name == " ":
                    full_name = first_name.strip() or f"Member_{member_id}"
                
                if stored_encoding is not None:
                    # Use existing encoding
                    new_encodings.append(stored_encoding)
                    new_names.append(full_name)
                    new_member_ids_list.append(member_id)
                    new_gym_member_id_mapping[member_id] = gym_member_id
                    print(f"[AUTO-CHECK] Loaded existing encoding for member_id={member_id}")
                else:
                    # Generate new encoding
                    print(f"[AUTO-CHECK] Generating new encoding for member_id={member_id}")
                    img = None
                    boxes = None
                    encoding = None
                    try:
                        img = url_to_rgb_array(full_url)
                        boxes = safe_face_recognition("face_locations", img, model="hog")
                        
                        if not boxes:
                            print(f"[AUTO-CHECK] No face found for member_id={member_id}")
                            error_count += 1
                            continue
                            
                        encoding = safe_face_recognition("face_encodings", img, known_face_locations=[boxes[0]])
                        if not encoding:
                            print(f"[AUTO-CHECK] Failed to generate encoding for member_id={member_id}")
                            error_count += 1
                            continue
                            
                        # Save to database
                        save_encoding_to_db(member_id, encoding[0])
                        
                        new_encodings.append(encoding[0])
                        new_names.append(full_name)
                        new_member_ids_list.append(member_id)
                        new_gym_member_id_mapping[member_id] = gym_member_id
                        print(f"[AUTO-CHECK] Generated & saved encoding for member_id={member_id}")
                    finally:
                        # Clean up memory
                        if img is not None:
                            del img
                        if boxes is not None:
                            del boxes
                        if encoding is not None:
                            del encoding
                        force_garbage_collection()
                
                processed_count += 1
                
            except Exception as e:
                print(f"[AUTO-CHECK] Error processing member_id={member_id}: {e}")
                error_count += 1
        
        # Add new encodings to existing ones
        if new_encodings:
            with self.lock:
                self.known_encodings.extend(new_encodings)
                self.known_names.extend(new_names)
                self.known_ids.extend(new_member_ids_list)
                self.gym_member_id_mapping.update(new_gym_member_id_mapping)
                self.loaded_member_ids.update(new_member_ids)
            
            # Update Redis cache
            if REDIS_ENABLED:
                cache_encodings(self.known_encodings, self.known_names, self.known_ids)
            
            print(f"[AUTO-CHECK] Successfully added {processed_count} new encodings. Errors: {error_count}")
        else:
            print(f"[AUTO-CHECK] No new encodings added. Errors: {error_count}")
    
    def is_in_cooldown(self, device_id: str = None):
        """Check if system is in cooldown period for specific device"""
        if not device_id:
            return False
        current_time = time.time()
        device_data = self.device_cooldowns.get(device_id)
        if not device_data:
            return False
        return (current_time - device_data.get('last_login', 0)) < self.cooldown_duration
    
    def get_cooldown_remaining(self, device_id: str = None):
        """Get remaining cooldown time in seconds for specific device"""
        if not device_id:
            return 0
        current_time = time.time()
        device_data = self.device_cooldowns.get(device_id)
        if not device_data:
            return 0
        elapsed = current_time - device_data.get('last_login', 0)
        remaining = self.cooldown_duration - elapsed
        return max(0, remaining)
    
    def set_successful_login(self, member_name: str, device_id: str = None):
        """Mark successful login timestamp and store member name for specific device"""
        if not device_id:
            return
        current_time = time.time()
        self.device_cooldowns[device_id] = {
            'last_login': current_time,
            'member': member_name
        }
        print(f"[COOLDOWN] Device {device_id} cooldown set for {member_name}")
    
    def set_denied(self, member_name: str, reason: str = "Access denied", device_id: str = None):
        if not device_id:
            return
        current_time = time.time()
        entry = self.device_cooldowns.get(device_id, {})
        entry['last_denied'] = current_time
        entry['denied_member'] = member_name
        entry['denied_reason'] = reason
        self.device_cooldowns[device_id] = entry
        print(f"[DENIED] Device {device_id} denied set for {member_name}: {reason}")
    
    def is_in_denied_cooldown(self, device_id: str = None) -> bool:
        if not device_id:
            return False
        entry = self.device_cooldowns.get(device_id)
        if not entry:
            return False
        last_denied = entry.get('last_denied', 0)
        return (time.time() - last_denied) < self.denied_cooldown_duration
    
    def get_denied_remaining(self, device_id: str = None) -> float:
        if not device_id:
            return 0.0
        entry = self.device_cooldowns.get(device_id, {})
        last_denied = entry.get('last_denied', 0)
        elapsed = time.time() - last_denied
        remaining = self.denied_cooldown_duration - elapsed
        return max(0.0, remaining)
    
    def get_last_successful_member(self, device_id: str = None):
        """Get last successful member name for specific device"""
        if not device_id:
            return ""
        device_data = self.device_cooldowns.get(device_id)
        if not device_data:
            return ""
        return device_data.get('member', "")

    def update_prediction_streak(self, device_id: str, predicted_name: str) -> bool:
        if not device_id or not predicted_name or predicted_name == "Unknown":
            self.device_prediction_streak.pop(device_id, None)
            return False
        entry = self.device_prediction_streak.get(device_id, {"name": "", "count": 0})
        if entry.get("name") == predicted_name:
            entry["count"] = entry.get("count", 0) + 1
        else:
            entry = {"name": predicted_name, "count": 1}
        self.device_prediction_streak[device_id] = entry
        return entry["count"] >= REQUIRED_CONSISTENT_FRAMES

    def recognize_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Detect & recognize faces in BGR frame. Draw boxes & labels.
        """
        # Check for new members periodically
        self.check_for_new_members()
        
        with self.lock:
            known_encs = self.known_encodings
            known_names = self.known_names

        if not known_encs:
            # just display info text
            h, w = frame_bgr.shape[:2]
            cv2.putText(frame_bgr, "No encodings loaded. Hit /reload to load.",
                        (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            return frame_bgr

        # Convert to RGB for face_recognition
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Detect all faces (hog = CPU cepat; cnn = lebih akurat tapi butuh CUDA)
        boxes = safe_face_recognition("face_locations", rgb, model="hog")
        encs = safe_face_recognition("face_encodings", rgb, boxes)

        for (top, right, bottom, left), enc in zip(boxes, encs):
            # Compute distance to all known encodings
            distances = safe_face_recognition("face_distance", known_encs, enc)
            if len(distances) == 0:
                name = "Unknown"
                best_dist = 1.0
            else:
                idx = int(np.argmin(distances))
                best_dist = float(distances[idx])
                name = known_names[idx] if best_dist <= TOLERANCE else "Unknown"

            # Draw
            cv2.rectangle(frame_bgr, (left, top), (right, bottom), (0, 255, 0) if name != "Unknown" else (0, 0, 255), 2)
            label = f"{name} ({best_dist:.2f})" if name != "Unknown" else f"Unknown ({best_dist:.2f})"
            cv2.rectangle(frame_bgr, (left, bottom - 22), (right, bottom), (0, 0, 0), -1)
            cv2.putText(frame_bgr, label, (left + 5, bottom - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, lineType=cv2.LINE_AA)
        return frame_bgr

recognizer = Recognizer()

def background_auto_check():
    """
    Background thread untuk auto-check data baru dengan memory management
    """
    while True:
        try:
            recognizer.check_for_new_members()
            # Force garbage collection after each check
            force_garbage_collection()
            time.sleep(10)  # Increased interval to reduce load
        except Exception as e:
            print(f"[BACKGROUND] Error in auto-check: {e}")
            force_garbage_collection()
            time.sleep(60)  # Wait longer on error

# Background thread will be started after initial load in __main__

# ===================== Flask App =====================
app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
app.secret_key = FLASK_SECRET_KEY


def require_login():
    return bool(session.get("logged_in"))


def gym_login_with_email(email: str, password: str) -> dict:
    try:
        payload = {
            "api_key": GYM_API_KEY,
            "email": email,
            "password": password
        }
        response = requests.post(GYM_LOGIN_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("error") is None and data.get("result"):
            token = data["result"].get("token")
            expires = data["result"].get("expires")
            return {"success": True, "token": token, "expires": expires}
        return {"success": False, "error": data.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_member_profile(token: str) -> dict:
    try:
        params = {"token": token, "api_key": GYM_API_KEY}
        r = requests.get(GYM_PROFILE_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@app.route("/login", methods=["GET", "POST"])
def login():
    from flask import request
    if request.method == "POST":
        email = (request.form.get("email") or '').strip().lower()
        password = request.form.get("password") or ''
        result = gym_login_with_email(email, password)
        if result.get("success") and result.get("token"):
            session["logged_in"] = True
            session["gm_token"] = result.get("token")
            return redirect(url_for("retake"))
        return render_template("login.html", error="Invalid email or password")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if not require_login():
        return redirect(url_for("login"))
    return redirect(url_for("retake"))


@app.route("/recognition")
def recognition_page():
    if not require_login():
        return redirect(url_for("login"))
    try:
        print("[RECOG] Preparing encodings on-demand...")
        add_enc_field_to_member_table()
        enc_status = regenerate_missing_encodings(BATCH_SIZE, regenerate_all=False)
        if not enc_status.get("success"):
            print(f"[RECOG] ENC regeneration skip/error: {enc_status.get('error')}")
        recognizer.reload()
    except Exception as e:
        print(f"[RECOG] Prepare error: {e}")
    return render_template("recognition.html", tol=TOLERANCE)




@app.route("/retake")
def retake():
    if not require_login():
        return redirect(url_for("login"))
    token = session.get("gm_token", "")
    current_photo = ""
    if token:
        prof = fetch_member_profile(token)
        try:
            if not prof.get("error") and prof.get("result"):
                current_photo = prof["result"].get("memberphoto") or ""
        except Exception:
            current_photo = ""
    return render_template("retake.html", current_photo=current_photo)

@app.route('/update_door_id', methods=['POST'])
def update_door_id():
    try:
        from flask import request
        data = request.get_json()
        door_id = data.get('door_id')
        device_id = data.get('device_id')  # Get device identifier
        
        if not door_id:
            return {"success": False, "error": "Door ID is required"}
        
        # Generate device ID if not provided (using IP + User Agent)
        if not device_id:
            device_id = f"{request.remote_addr}_{request.headers.get('User-Agent', '')[:50]}"
        
        # Store door ID per device
        device_door_ids[device_id] = door_id
        
        print(f"[DOOR] Device {device_id} door ID updated to: {door_id}")
        print(f"[DOOR] Current device door IDs: {device_door_ids}")
        return {"success": True, "door_id": door_id, "device_id": device_id}
        
    except Exception as e:
        print(f"[DOOR] Error updating door ID: {e}")
        return {"success": False, "error": str(e)}

@app.route("/recognize", methods=["POST"])
def recognize():
    try:
        from flask import request
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401
        
        if 'frame' not in request.files:
            return {"success": False, "error": "No frame provided"}
        
        file = request.files['frame']
        if file.filename == '':
            return {"success": False, "error": "No file selected"}
        
        # Read image data
        image_data = file.read()
        nparr = np.frombuffer(image_data, np.uint8)
        frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame_bgr is None:
            return {"success": False, "error": "Invalid image"}
        
        # Resize image for faster processing if too large
        height, width = frame_bgr.shape[:2]
        if width > 640:  # If image is larger than 640px, resize it
            scale = 640 / width
            new_width = 640
            new_height = int(height * scale)
            frame_bgr = cv2.resize(frame_bgr, (new_width, new_height))
            print(f"[PERF] Resized image from {width}x{height} to {new_width}x{new_height}")
        
        # Convert to RGB for face detection
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        
        # Detect faces and get recognition results
        with recognizer.lock:
            known_encs = recognizer.known_encodings
            known_names = recognizer.known_names
            known_ids = recognizer.known_ids
        
        # For GCP: Load encodings on-demand if not loaded
        if not known_encs:
            print(f"[RECOGNIZE] No known encodings loaded. Total: {len(known_encs)}. Attempting to load on-demand...")
            try:
                recognizer.reload()
                known_encs = recognizer.known_encodings
                known_names = recognizer.known_names
                known_ids = recognizer.known_ids
                print(f"[RECOGNIZE] On-demand load completed. Loaded: {len(known_encs)} encodings")
            except Exception as e:
                print(f"[RECOGNIZE] On-demand load failed: {e}")
                return {"success": True, "faces": [], "debug": "Failed to load encodings on-demand", "error": str(e)}
        
        if not known_encs:
            print(f"[RECOGNIZE] Still no known encodings after on-demand load. Total: {len(known_encs)}")
            return {"success": True, "faces": [], "debug": "No known encodings loaded after on-demand attempt", "total_encodings": len(known_encs)}
        
        # Detect faces with fallback pipeline
        boxes = safe_face_recognition("face_locations", rgb, model="hog", number_of_times_to_upsample=0)
        used_image = rgb
        if not boxes:
            boxes = safe_face_recognition("face_locations", rgb, model="hog", number_of_times_to_upsample=1)
        if not boxes:
            ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
            y, cr, cb = cv2.split(ycrcb)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            y_eq = clahe.apply(y)
            ycrcb_eq = cv2.merge([y_eq, cr, cb])
            rgb_eq = cv2.cvtColor(ycrcb_eq, cv2.COLOR_YCrCb2RGB)
            used_image = rgb_eq
            boxes = safe_face_recognition("face_locations", rgb_eq, model="hog", number_of_times_to_upsample=1)
        if not boxes:
            try:
                boxes = safe_face_recognition("face_locations", rgb, model="cnn", number_of_times_to_upsample=1)
                used_image = rgb
            except Exception:
                boxes = []
        
        if not boxes:
            return {"success": True, "faces": [], "debug": "No faces detected after fallback"}
        
        # Sort faces by size (largest first) and take only the first one
        face_sizes = [(i, (box[2] - box[0]) * (box[3] - box[1])) for i, box in enumerate(boxes)]
        face_sizes.sort(key=lambda x: x[1], reverse=True)  # Sort by area, largest first
        
        # Take only the largest face (most front)
        largest_face_idx = face_sizes[0][0]
        largest_box = boxes[largest_face_idx]
        
        # Generate encoding only for the largest face on the image used for detection
        encs = safe_face_recognition("face_encodings", used_image, [largest_box])
        
        if not encs:
            return {"success": True, "faces": [], "debug": "No face encoding generated"}
        
        faces = []
        # Process only the largest face
        (top, right, bottom, left) = largest_box
        enc = encs[0]  # Only one encoding for the largest face
        
        distances = safe_face_recognition("face_distance", known_encs, enc)
        if len(distances) == 0:
            name = "Unknown"
            confidence = 1.0
            member_id = None
        else:
            # Compute best and second-best distances
            order = np.argsort(distances)
            best_idx = int(order[0])
            best_dist = float(distances[best_idx])
            second_dist = float(distances[order[1]]) if len(distances) > 1 else 1.0
            margin_ok = (second_dist - best_dist) >= TOP2_MARGIN
            if best_dist <= TOLERANCE and margin_ok:
                name = known_names[best_idx]
                member_id = known_ids[best_idx]
                confidence = best_dist
            else:
                name = "Unknown"
                member_id = None
                confidence = best_dist
        
        # Get device ID for cooldown check
        device_id = request.headers.get('X-Device-ID', f"{request.remote_addr}_{request.headers.get('User-Agent', '')[:50]}")

        # Require consecutive frame confirmations
        confirmed = recognizer.update_prediction_streak(device_id, name)
        if name != "Unknown" and not confirmed:
            faces.append({
                "x": int(left),
                "y": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "name": "Verifying...",
                "confidence": confidence,
            })
            return {
                "success": True,
                "faces": faces,
                "cooldown": None,
                "popup": {
                    "show": True,
                    "style": "INFO",
                    "member_name": name,
                    "member_id": None,
                    "message": "Verifying identity..."
                },
                "debug": "Waiting for consecutive frame confirmation"
            }

        # Short-circuit if device is in denied cooldown window
        if recognizer.is_in_denied_cooldown(device_id):
            denied_remaining = recognizer.get_denied_remaining(device_id)
            faces.append({
                "x": int(left),
                "y": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "name": "Access Denied",
                "confidence": confidence,
            })
            return {
                "success": True,
                "faces": faces,
                "cooldown": None,
                "popup": {
                    "show": True,
                    "style": "DENIED",
                    "member_name": name,
                    "member_id": None,
                    "message": f"Please wait {denied_remaining:.1f}s before retry"
                },
                "debug": "Denied cooldown active"
            }
        
        # Always add face data for display (bounding box should always show)
        face_data = {
            "x": int(left),
            "y": int(top),
            "width": int(right - left),
            "height": int(bottom - top),
            "name": name,
            "confidence": confidence,
            "member_id": member_id
        }
        
        # Process gym gate if member is recognized
        popup_info = None
        if member_id and confidence <= TOLERANCE:
            # Check cooldown for this specific device
            if recognizer.is_in_cooldown(device_id):
                cooldown_remaining = recognizer.get_cooldown_remaining(device_id)
                print(f"[GYM] ⏳ Device {device_id} cooldown active: {cooldown_remaining:.1f}s remaining")
                # Add cooldown info to face data
                face_data["cooldown"] = True
                face_data["cooldown_remaining"] = cooldown_remaining
            else:
                # Get gym_member_id for API call
                gym_member_id = recognizer.gym_member_id_mapping.get(member_id)
                if gym_member_id:
                    # Get device-specific door ID
                    current_door_id = device_door_ids.get(device_id, GYM_DOOR_ID)
                    
                    print(f"[GYM] Using door ID {current_door_id} for device {device_id}")
                    
                    gym_result = process_member_detection_with_door(gym_member_id, name, current_door_id)
                    if gym_result["success"]:
                        print(f"[GYM] ✅ {gym_result['message']}")
                        # Mark successful login to start cooldown for this device only
                        recognizer.set_successful_login(name, device_id)
                    else:
                        print(f"[GYM] ❌ {gym_result['error']}")
                        # Set denied cooldown to prevent immediate re-grant on next frame
                        recognizer.set_denied(name, gym_result.get('error') or 'Access denied', device_id)
                    
                    # Get popup info from gym result and add cooldown duration
                    popup_info = gym_result.get("popup")
                    if popup_info and popup_info.get("style") == "GRANTED":
                        popup_info["cooldown_duration"] = recognizer.cooldown_duration
                else:
                    print(f"[GYM] ❌ No gym_member_id found for member_id={member_id}")
                
                # Fallback popup for testing if no gym popup
                if not popup_info:
                    print(f"[DEBUG] Creating fallback popup for {name}")
                    popup_info = {
                        "show": True,
                        "style": "GRANTED",
                        "member_name": name,
                        "member_id": recognizer.gym_member_id_mapping.get(member_id),
                        "message": f"Access Granted for {name}"
                    }
        
        # Always add face data to faces array
        faces.append(face_data)
        
        # Add cooldown info if this device is in cooldown
        cooldown_info = None
        if recognizer.is_in_cooldown(device_id):
            cooldown_remaining = recognizer.get_cooldown_remaining(device_id)
            cooldown_info = {
                "show": True,
                "remaining": cooldown_remaining
            }
            print(f"[COOLDOWN] Device {device_id} showing cooldown: {cooldown_remaining:.1f}s remaining")
        
        return {
            "success": True, 
            "faces": faces, 
            "cooldown": cooldown_info,
            "popup": popup_info,
            "debug": f"Processed {len(faces)} faces"
        }
        
    except Exception as e:
        print(f"[RECOG] Error: {e}")
        return {"success": False, "error": str(e)}

@app.route("/reload")
def reload_route():
    if not require_login():
        return redirect(url_for("login"))
    threading.Thread(target=recognizer.reload, daemon=True).start()
    return "Reload encodings dipicu. Tunggu 1-3 detik lalu refresh stream."

@app.route("/check_new_members")
def check_new_members_route():
    """
    Manual check for new members (auto-check disabled to prevent memory issues)
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        result = recognizer.check_for_new_members()
        return f"New members checked. Result: {result}"
    except Exception as e:
        return f"Error checking new members: {str(e)}"

@app.route("/regenerate_enc")
def regenerate_enc_route():
    """
    Manually trigger regeneration of missing encodings
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        from flask import request
        limit = request.args.get('limit') or request.args.get('batch') or request.args.get('size')
        batch = int(limit) if limit and str(limit).isdigit() else BATCH_SIZE
        result = regenerate_missing_encodings(batch)
        if result["success"]:
            return {
                "success": True,
                "message": f"ENC regeneration completed. Success: {result['success_count']}, Errors: {result['error_count']}",
                "success_count": result["success_count"],
                "error_count": result["error_count"],
                "batch_size": batch
            }
        else:
            return {"success": False, "error": result["error"]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/enc_status")
def enc_status_route():
    """
    Check ENC status for all members
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Count members with valid encodings
        cur.execute("""
            SELECT COUNT(*) as total_members
            FROM member m
            JOIN member_file f ON f.member_id = m.id
            WHERE m.status = 1
              AND (f.status IS NULL OR f.status = 1)
              AND (f.file_type_id IS NULL OR f.file_type_id = 1)
              AND LOWER(f.file_base_url) LIKE '%https://ftlhorizon.com/%'
        """)
        total_members = cur.fetchone()[0]
        
        # Count members with valid encodings
        cur.execute("""
            SELECT COUNT(*) as members_with_enc
            FROM member m
            JOIN member_file f ON f.member_id = m.id
            WHERE m.status = 1
              AND (f.status IS NULL OR f.status = 1)
              AND (f.file_type_id IS NULL OR f.file_type_id = 1)
              AND LOWER(f.file_base_url) LIKE '%https://ftlhorizon.com/%'
              AND m.enc IS NOT NULL 
              AND LENGTH(m.enc) = 1024
        """)
        members_with_enc = cur.fetchone()[0]
        
        # Count members without encodings
        members_without_enc = total_members - members_with_enc
        
        cur.close()
        conn.close()
        
        return {
            "success": True,
            "total_members": total_members,
            "members_with_enc": members_with_enc,
            "members_without_enc": members_without_enc,
            "enc_percentage": round((members_with_enc / total_members * 100) if total_members > 0 else 0, 2),
            "loaded_members": len(recognizer.loaded_member_ids),
            "auto_check_interval": recognizer.auto_check_interval
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/debug_members")
def debug_members_route():
    """
    Debug endpoint to see current member status
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        # Get current members from DB
        sources = fetch_member_images()
        current_member_ids = {member_id for member_id, _, _, _, _ in sources}
        
        # Get loaded members
        loaded_member_ids = recognizer.loaded_member_ids
        
        # Find differences
        new_members = current_member_ids - loaded_member_ids
        missing_members = loaded_member_ids - current_member_ids
        
        return {
            "success": True,
            "current_db_members": list(current_member_ids),
            "loaded_members": list(loaded_member_ids),
            "new_members": list(new_members),
            "missing_members": list(missing_members),
            "total_db": len(current_member_ids),
            "total_loaded": len(loaded_member_ids),
            "auto_check_interval": recognizer.auto_check_interval,
            "last_auto_check": recognizer.last_auto_check
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/set_auto_check_interval", methods=['POST'])
def set_auto_check_interval_route():
    """
    Set auto-check interval for new members (in seconds)
    """
    try:
        from flask import request
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401
        data = request.get_json()
        interval = data.get('interval', 30)
        
        if not isinstance(interval, (int, float)) or interval < 10:
            return {"success": False, "error": "Interval must be a number >= 10 seconds"}
        
        recognizer.auto_check_interval = int(interval)
        
        return {
            "success": True,
            "message": f"Auto-check interval set to {interval} seconds",
            "new_interval": recognizer.auto_check_interval
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/health")
def health():
    with recognizer.lock:
        n = len(recognizer.known_encodings)
        last = recognizer.last_reload
    return {
        "ok": True,
        "encodings": n,
        "last_reload_epoch": last,
        "tolerance": TOLERANCE
    }

@app.route("/gcp_debug")
def gcp_debug_route():
    """
    GCP specific debug endpoint to check database and encoding status
    """
    try:
        # Check database connection
        db_status = "connected"
        member_count = 0
        encoding_count = 0
        member_files_count = 0
        try:
            conn = get_conn()
            cur = conn.cursor()
            
            # Count total members
            cur.execute("SELECT COUNT(*) FROM member WHERE status = 1")
            member_count = cur.fetchone()[0]
            
            # Count members with encodings
            cur.execute("SELECT COUNT(*) FROM member WHERE status = 1 AND enc IS NOT NULL AND LENGTH(enc) = 1024")
            encoding_count = cur.fetchone()[0]
            
            # Count member files that match our criteria
            cur.execute("""
                SELECT COUNT(*) 
                FROM member m
                JOIN member_file f ON f.member_id = m.id
                WHERE m.status = 1
                  AND (f.status IS NULL OR f.status = 1)
                  AND (f.file_type_id IS NULL OR f.file_type_id = 1)
                  AND LOWER(f.file_base_url) LIKE '%https://ftlhorizon.com/%'
            """)
            member_files_count = cur.fetchone()[0]
            
            cur.close()
            conn.close()
        except Exception as e:
            db_status = f"error: {str(e)}"
        
        # Check environment variables
        env_vars = {
            "DB_HOST": bool(os.getenv("DB_HOST")),
            "DB_PORT": bool(os.getenv("DB_PORT")),
            "DB_NAME": bool(os.getenv("DB_NAME")),
            "DB_USER": bool(os.getenv("DB_USER")),
            "DB_PASSWORD": bool(os.getenv("DB_PASSWORD")),
            "API_KEY": bool(os.getenv("API_KEY")),
        }
        
        return {
            "success": True,
            "environment": "GCP",
            "database_status": db_status,
            "total_members": member_count,
            "members_with_encodings": encoding_count,
            "member_files_matching_criteria": member_files_count,
            "environment_variables": env_vars,
            "recognizer_status": {
                "loaded_members": len(recognizer.loaded_member_ids),
                "known_encodings": len(recognizer.known_encodings),
                "known_names": len(recognizer.known_names)
            },
            "note": "GCP Cloud Run uses stateless instances, so in-memory caching may not persist between requests"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/gcp_load_on_demand")
def gcp_load_on_demand_route():
    """
    Load encodings on-demand for GCP (since caching doesn't work well)
    """
    try:
        print("[GCP] Loading encodings on-demand...")
        
        # Force reload from database
        recognizer.reload()
        
        return {
            "success": True,
            "message": "Encodings loaded on-demand",
            "loaded_count": len(recognizer.known_encodings),
            "recognizer_status": {
                "loaded_members": len(recognizer.loaded_member_ids),
                "known_encodings": len(recognizer.known_encodings),
                "known_names": len(recognizer.known_names)
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/redis_status")
def redis_status_route():
    """
    Check Redis connection and cache status
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        if not REDIS_ENABLED:
            return {
                "success": True,
                "redis_enabled": False,
                "message": "Redis is disabled"
            }
        
        client = get_redis_client()
        if client is None:
            return {
                "success": False,
                "redis_enabled": True,
                "message": "Failed to connect to Redis"
            }
        
        # Test connection
        client.ping()
        
        # Check cache
        cached_encodings, cached_names, cached_member_ids = get_cached_encodings()
        
        return {
            "success": True,
            "redis_enabled": True,
            "redis_connected": True,
            "cache_status": {
                "has_cached_data": len(cached_encodings) > 0,
                "cached_encodings_count": len(cached_encodings),
                "cached_names_count": len(cached_names),
                "cached_member_ids_count": len(cached_member_ids)
            },
            "redis_config": {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password_set": bool(REDIS_PASSWORD)
            }
        }
    except Exception as e:
        return {
            "success": False,
            "redis_enabled": REDIS_ENABLED,
            "error": str(e)
        }

@app.route("/redis_clear_cache")
def redis_clear_cache_route():
    """
    Clear Redis cache
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        if not REDIS_ENABLED:
            return {
                "success": False,
                "message": "Redis is disabled"
            }
        
        success = invalidate_encodings_cache()
        return {
            "success": success,
            "message": "Cache cleared successfully" if success else "Failed to clear cache"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/redis_reload")
def redis_reload_route():
    """
    Force reload encodings and update Redis cache
    """
    if not require_login():
        return redirect(url_for("login"))
    try:
        print("[REDIS] Force reloading encodings...")
        
        # Clear cache first
        if REDIS_ENABLED:
            invalidate_encodings_cache()
        
        # Force reload from database
        recognizer.reload()
        
        return {
            "success": True,
            "message": "Encodings reloaded and cached",
            "loaded_count": len(recognizer.known_encodings),
            "redis_cached": REDIS_ENABLED and len(recognizer.known_encodings) > 0
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# @app.route("/recognize_gcp", methods=["POST"])
# def recognize_gcp():
#     """
#     GCP optimized recognition - load encodings directly from DB without caching
#     """
#     if not require_login():
#         return {"success": False, "error": "Unauthorized"}, 401
#     try:
#         from flask import request
        
#         if 'frame' not in request.files:
#             return {"success": False, "error": "No frame provided"}
        
#         file = request.files['frame']
#         if file.filename == '':
#             return {"success": False, "error": "No file selected"}
        
#         # Read image data
#         image_data = file.read()
#         nparr = np.frombuffer(image_data, np.uint8)
#         frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
#         if frame_bgr is None:
#             return {"success": False, "error": "Invalid image"}
        
#         # Resize image for faster processing if too large
#         height, width = frame_bgr.shape[:2]
#         if width > 640:
#             scale = 640 / width
#             new_width = 640
#             new_height = int(height * scale)
#             frame_bgr = cv2.resize(frame_bgr, (new_width, new_height))
        
#         # Convert to RGB for face detection
#         rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        
#         # Load encodings directly from database (no caching)
#         print("[GCP] Loading encodings directly from database...")
#         conn = get_conn()
#         cur = conn.cursor()
        
#         # Get all encodings with member info
#         cur.execute("""
#             SELECT m.id, m.member_id, m.first_name, m.last_name, m.enc
#             FROM member m
#             JOIN member_file f ON f.member_id = m.id
#             WHERE m.status = 1
#               AND (f.status IS NULL OR f.status = 1)
#               AND (f.file_type_id IS NULL OR f.file_type_id = 1)
#               AND LOWER(f.file_base_url) LIKE '%https://ftlhorizon.com/%'
#               AND m.enc IS NOT NULL 
#               AND LENGTH(m.enc) = 1024
#         """)
        
#         rows = cur.fetchall()
#         cur.close()
#         conn.close()
        
#         if not rows:
#             return {"success": True, "faces": [], "debug": "No encodings found in database"}
        
#         # Process encodings
#         known_encs = []
#         known_names = []
#         known_ids = []
        
#         for member_id, gym_member_id, first_name, last_name, enc_bytes in rows:
#             try:
#                 # Convert bytes to numpy array
#                 encoding = np.frombuffer(enc_bytes, dtype=np.float64)
#                 if len(encoding) == 128:  # Valid face encoding
#                     known_encs.append(encoding)
#                     full_name = f"{first_name.strip()} {last_name.strip()}".strip()
#                     if not full_name or full_name == " ":
#                         full_name = first_name.strip() or f"Member_{member_id}"
#                     known_names.append(full_name)
#                     known_ids.append(member_id)
#             except Exception as e:
#                 print(f"[GCP] Error processing encoding for member {member_id}: {e}")
#                 continue
        
#         print(f"[GCP] Loaded {len(known_encs)} encodings directly from database")
        
#         if not known_encs:
#             return {"success": True, "faces": [], "debug": "No valid encodings processed"}
        
#         # Detect faces
#         boxes = safe_face_recognition("face_locations", rgb, model="hog", number_of_times_to_upsample=0)
        
#         if not boxes:
#             return {"success": True, "faces": [], "debug": "No faces detected"}
        
#         # Process largest face
#         face_sizes = [(i, (box[2] - box[0]) * (box[3] - box[1])) for i, box in enumerate(boxes)]
#         face_sizes.sort(key=lambda x: x[1], reverse=True)
#         largest_face_idx = face_sizes[0][0]
#         largest_box = boxes[largest_face_idx]
        
#         # Generate encoding for detected face
#         encs = safe_face_recognition("face_encodings", rgb, [largest_box])
        
#         if not encs:
#             return {"success": True, "faces": [], "debug": "No face encoding generated"}
        
#         # Compare with known encodings
#         (top, right, bottom, left) = largest_box
#         enc = encs[0]
        
#         distances = safe_face_recognition("face_distance", known_encs, enc)
#         if len(distances) == 0:
#             name = "Unknown"
#             confidence = 1.0
#             member_id = None
#         else:
#             idx = int(np.argmin(distances))
#             confidence = float(distances[idx])
#             name = known_names[idx] if confidence <= TOLERANCE else "Unknown"
#             member_id = known_ids[idx] if confidence <= TOLERANCE else None
        
#         # Get device ID for cooldown check
#         device_id = request.headers.get('X-Device-ID', f"{request.remote_addr}_{request.headers.get('User-Agent', '')[:50]}")
        
#         # Check cooldown
#         current_time = time.time()
#         if device_id in device_door_ids:
#             last_access = device_door_ids[device_id].get('last_access', 0)
#             if current_time - last_access < 2.0:  # 2 second cooldown
#                 return {"success": True, "faces": [], "debug": "Cooldown active"}
        
#         # Update device info
#         device_door_ids[device_id] = {
#             'last_access': current_time,
#             'door_id': request.args.get('doorid', GYM_DOOR_ID)
#         }
        
#         faces = []
#         if name != "Unknown":
#             faces.append({
#                 "name": name,
#                 "confidence": confidence,
#                 "member_id": member_id,
#                 "box": [int(left), int(top), int(right), int(bottom)]
#             })
        
#         return {"success": True, "faces": faces, "debug": f"Processed {len(known_encs)} encodings"}
        
#     except Exception as e:
#         print(f"[GCP] Recognition error: {e}")
#         return {"success": False, "error": str(e)}

# ===================== Main =====================
if __name__ == "__main__":
    if REDIS_ENABLED:
        print("[STARTUP] Initializing Redis connection...")
        get_redis_client()
    print("[STARTUP] Server starting...")
    app.run(host="0.0.0.0", port=8001, debug=True, threaded=True)
