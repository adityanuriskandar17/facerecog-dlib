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
    """Deprecated: Local memberphoto no longer used. Use GymMaster profile API for photos."""
    try:
        # Intentionally return empty list to avoid relying on local memberphoto column
        return []
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
    """Build known encodings from database - compatible with app_old.py structure"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Try different query structures to match the database
        # First try: check if we have the same structure as app_old.py
        try:
            # Check if status column exists and what type it is
            cur.execute("DESCRIBE member")
            columns = cur.fetchall()
            column_names = [col[0] for col in columns]
            
            print(f"[DB] Available columns: {column_names}")
            
            # Build query based on available columns
            if 'status' in column_names:
                # Try with status = 1 (integer) first
                cur.execute("""
                    SELECT id, member_id, first_name, last_name, enc
                    FROM member
                    WHERE enc IS NOT NULL 
                    AND status = 1
                    AND LENGTH(enc) = 1024
                    ORDER BY id
                """)
            else:
                # No status column, just get all with encodings
                cur.execute("""
                    SELECT id, member_id, first_name, last_name, enc
                    FROM member
                    WHERE enc IS NOT NULL 
                    AND LENGTH(enc) = 1024
                    ORDER BY id
                """)
                
        except Exception as e:
            print(f"[DB] Error with status query, trying without status: {e}")
            # Fallback: get all members with encodings
            cur.execute("""
                SELECT id, member_id, first_name, last_name, enc
                FROM member
                WHERE enc IS NOT NULL 
                AND LENGTH(enc) = 1024
                ORDER BY id
            """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        encodings = []
        names = []
        member_ids = []
        gym_member_mapping = {}
        
        print(f"[DB] Found {len(results)} members with encodings")
        
        for db_member_id, gym_member_id, first_name, last_name, enc_data in results:
            if enc_data:
                try:
                    # Decode encoding (should be 128 float64 values = 1024 bytes)
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
                        print(f"[DB] Loaded encoding for member_id={db_member_id} name={full_name}")
                    else:
                        print(f"[DB] Invalid encoding size for member_id={db_member_id}: {len(encoding)} (expected 128)")
                except Exception as e:
                    print(f"[DB] Error processing encoding for member_id={db_member_id}: {e}")
        
        print(f"[DB] Successfully loaded {len(encodings)} encodings from database")
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
        # Disable regeneration based on local memberphoto; photos are sourced from GymMaster
        return {"success": True, "message": "Regeneration disabled; using GymMaster photos"}
    except Error as e:
        print(f"[DB] Error regenerating encodings: {e}")
        return {"success": False, "error": str(e)}
