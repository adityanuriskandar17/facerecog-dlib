import mysql.connector
from mysql.connector import Error
from typing import List, Tuple, Dict, Optional
import numpy as np

from ..config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

def get_conn():
    """Get database connection"""
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
        return conn
    except Error as e:
        print(f"[DB] Connection error: {e}")
        raise

def fetch_member_images() -> List[Tuple[int, int, str, str, str]]:
    """Fetch member images from database"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT m.id, m.member_id, m.first_name, m.last_name, m.memberphoto
            FROM member m
            WHERE m.memberphoto IS NOT NULL 
            AND m.memberphoto != '' 
            AND m.memberphoto != 'NULL'
            AND m.status = 'active'
            ORDER BY m.id
        """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        return results
    except Error as e:
        print(f"[DB] Error fetching member images: {e}")
        return []

def load_encoding_from_db(member_id: int) -> Optional[np.ndarray]:
    """Load face encoding from database"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT enc FROM member WHERE id = %s", (member_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result and result[0]:
            encoding = np.frombuffer(result[0], dtype=np.float64)
            if len(encoding) == 128:
                return encoding
            else:
                print(f"[DB] Invalid encoding size for member_id={member_id}: {len(encoding)}")
                return None
        return None
    except Error as e:
        print(f"[DB] Error loading encoding for member_id={member_id}: {e}")
        return None

def save_encoding_to_db(member_id: int, encoding: np.ndarray):
    """Save face encoding to database"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Convert numpy array to binary
        encoding_bytes = encoding.tobytes()
        
        cur.execute(
            "UPDATE member SET enc = %s WHERE id = %s",
            (encoding_bytes, member_id)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[DB] Saved encoding for member_id={member_id}")
    except Error as e:
        print(f"[DB] Error saving encoding for member_id={member_id}: {e}")
        raise

def build_known_encodings_fast() -> Tuple[List[np.ndarray], List[str], List[int], Dict[int, int]]:
    """Build known encodings from database"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get all active members with encodings
        cur.execute("""
            SELECT m.id, m.member_id, m.first_name, m.last_name, m.enc
            FROM member m
            WHERE m.enc IS NOT NULL 
            AND m.status = 'active'
            ORDER BY m.id
        """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        encodings = []
        names = []
        member_ids = []
        gym_member_mapping = {}
        
        for db_member_id, gym_member_id, first_name, last_name, enc_data in results:
            if enc_data:
                try:
                    encoding = np.frombuffer(enc_data, dtype=np.float64)
                    if len(encoding) == 128:
                        encodings.append(encoding)
                        
                        # Create full name
                        full_name = f"{first_name.strip()} {last_name.strip()}".strip()
                        if not full_name or full_name == " ":
                            full_name = first_name.strip() or f"Member_{db_member_id}"
                        
                        names.append(full_name)
                        member_ids.append(db_member_id)
                        gym_member_mapping[db_member_id] = gym_member_id
                    else:
                        print(f"[DB] Invalid encoding size for member_id={db_member_id}: {len(encoding)}")
                except Exception as e:
                    print(f"[DB] Error processing encoding for member_id={db_member_id}: {e}")
        
        print(f"[DB] Loaded {len(encodings)} encodings from database")
        return encodings, names, member_ids, gym_member_mapping
        
    except Error as e:
        print(f"[DB] Error building known encodings: {e}")
        return [], [], [], {}

def add_enc_field_to_member_table():
    """Add enc field to member table if it doesn't exist"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if field already exists
        cur.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'member' AND COLUMN_NAME = 'enc'
        """, (DB_NAME,))
        
        if cur.fetchone():
            print("[DB] ENC field already exists")
            cur.close()
            conn.close()
            return
        
        # Add the enc field
        cur.execute("ALTER TABLE member ADD COLUMN enc LONGBLOB NULL")
        
        # Add index for better performance
        cur.execute("CREATE INDEX idx_member_enc ON member(enc(100))")
        
        conn.commit()
        cur.close()
        conn.close()
        
        print("[DB] Added ENC field to member table")
        
    except Error as e:
        print(f"[DB] Error adding ENC field: {e}")

def regenerate_missing_encodings(batch_size: int, regenerate_all: bool = False) -> Dict:
    """Regenerate missing encodings"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        if regenerate_all:
            # Regenerate all encodings
            cur.execute("""
                SELECT m.id, m.member_id, m.first_name, m.last_name, m.memberphoto
                FROM member m
                WHERE m.memberphoto IS NOT NULL 
                AND m.memberphoto != '' 
                AND m.memberphoto != 'NULL'
                AND m.status = 'active'
                LIMIT %s
            """, (batch_size,))
        else:
            # Only regenerate missing encodings
            cur.execute("""
                SELECT m.id, m.member_id, m.first_name, m.last_name, m.memberphoto
                FROM member m
                WHERE m.memberphoto IS NOT NULL 
                AND m.memberphoto != '' 
                AND m.memberphoto != 'NULL'
                AND m.status = 'active'
                AND (m.enc IS NULL OR m.enc = '')
                LIMIT %s
            """, (batch_size,))
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if not results:
            return {"success": True, "message": "No encodings to regenerate"}
        
        # Process encodings
        processed = 0
        errors = 0
        
        for db_member_id, gym_member_id, first_name, last_name, photo_url in results:
            try:
                # Check if encoding already exists and we're not regenerating all
                if not regenerate_all:
                    existing_encoding = load_encoding_from_db(db_member_id)
                    if existing_encoding is not None:
                        continue
                
                # Generate new encoding
                from .face_recognition_service import url_to_rgb_array, safe_face_recognition, force_garbage_collection
                
                img = url_to_rgb_array(photo_url)
                boxes = safe_face_recognition("face_locations", img, model="hog")
                
                if not boxes:
                    print(f"[REGEN] No face found for member_id={db_member_id}")
                    errors += 1
                    continue
                
                encoding = safe_face_recognition("face_encodings", img, known_face_locations=[boxes[0]])
                if not encoding:
                    print(f"[REGEN] Failed to generate encoding for member_id={db_member_id}")
                    errors += 1
                    continue
                
                # Save to database
                save_encoding_to_db(db_member_id, encoding[0])
                processed += 1
                
                # Clean up memory
                del img, boxes, encoding
                force_garbage_collection()
                
            except Exception as e:
                print(f"[REGEN] Error processing member_id={db_member_id}: {e}")
                errors += 1
        
        return {
            "success": True,
            "processed": processed,
            "errors": errors,
            "total": len(results)
        }
        
    except Error as e:
        print(f"[DB] Error regenerating encodings: {e}")
        return {"success": False, "error": str(e)}
