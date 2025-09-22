import os
import io
import time
import threading
from typing import Dict, List, Tuple
from collections import OrderedDict

import cv2
import numpy as np
import requests
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from flask import Flask, Response, render_template_string

# ==== Dlib via face_recognition ====
import face_recognition  # built on top of dlib

# ===================== Config =====================
load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "deepface")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

TOLERANCE = 0.45  # lebih ketat dari default 0.6

# Jika ingin batasi request gambar (detik)
REQUEST_TIMEOUT = 15

# Gym API Configuration
GYM_API_KEY = os.getenv("GYM_API_KEY", "")
GYM_DOOR_ID = os.getenv("GYM_DOOR_ID", "19456")
GYM_LOGIN_URL = os.getenv("GYM_LOGIN_URL", "")
GYM_GATE_URL = os.getenv("GYM_GATE_URL", "")

# Store door IDs per session/device
device_door_ids = {}


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
    Ambil (member_id, first_name, last_name, full_url) untuk foto terbaru per member yang aktif.
    Kita ambil semua kemudian reduce ke 'latest per member_id'.
    """
    sql = """
    SELECT
        m.id AS member_id,
        m.member_id AS gym_member_id,
        COALESCE(m.first_name, CONCAT('Member_', m.id)) AS first_name,
        COALESCE(m.last_name, '') AS last_name,
        CONCAT(f.file_base_url, f.file_base_path, f.file_path, f.file_name) AS full_url,
        f.created_at
    FROM member m
    JOIN member_file f ON f.member_id = m.id
    WHERE m.status = 1
      AND (f.status IS NULL OR f.status = 1)
      AND (f.file_type_id IS NULL OR f.file_type_id = 1)
      AND f.title = 'Profile2'
    ORDER BY m.id ASC, f.created_at DESC
    """
    rows: List[Tuple[int, int, str, str, str, str]] = []
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

    latest_per_member: "OrderedDict[int, Tuple[int,int,str,str,str]]" = OrderedDict()
    for member_id, gym_member_id, first_name, last_name, full_url, created_at in rows:
        if member_id not in latest_per_member:
            latest_per_member[member_id] = (member_id, gym_member_id, first_name, last_name, full_url)
    return list(latest_per_member.values())

# ===================== Image / Encoding =====================
def url_to_rgb_array(url: str) -> np.ndarray:
    """
    Download image from URL (supports querystrings), return RGB numpy array.
    Raises on error / if not an image.
    """
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = np.frombuffer(resp.content, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Gagal decode image dari URL")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb

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

def regenerate_missing_encodings():
    """
    Regenerate ENC for all members who don't have valid encoding in database
    """
    print("[ENC] Starting regeneration of missing encodings...")
    
    # Get all members without valid encodings
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get members with NULL or invalid encodings
        cur.execute("""
            SELECT m.id, m.member_id, COALESCE(m.first_name, CONCAT('Member_', m.id)) as first_name,
                   COALESCE(m.last_name, '') as last_name,
                   CONCAT(f.file_base_url, f.file_base_path, f.file_path, f.file_name) AS full_url
            FROM member m
            JOIN member_file f ON f.member_id = m.id
            WHERE m.status = 1
              AND (f.status IS NULL OR f.status = 1)
              AND (f.file_type_id IS NULL OR f.file_type_id = 1)
              AND f.title = 'Profile2'
              AND (m.enc IS NULL OR LENGTH(m.enc) != 1024)
            ORDER BY m.id ASC
        """)
        
        members = cur.fetchall()
        cur.close()
        conn.close()
        
        print(f"[ENC] Found {len(members)} members without valid encodings")
        
        success_count = 0
        error_count = 0
        
        for member_id, gym_member_id, first_name, last_name, full_url in members:
            try:
                print(f"[ENC] Regenerating encoding for member_id={member_id}")
                img = url_to_rgb_array(full_url)
                boxes = face_recognition.face_locations(img, model="hog")
                
                if not boxes:
                    print(f"[ENC] No face found for member_id={member_id}")
                    error_count += 1
                    continue
                    
                encoding = face_recognition.face_encodings(img, known_face_locations=[boxes[0]])
                if not encoding:
                    print(f"[ENC] Failed to generate encoding for member_id={member_id}")
                    error_count += 1
                    continue
                    
                # Save to database
                save_encoding_to_db(member_id, encoding[0])
                success_count += 1
                print(f"[ENC] Successfully regenerated encoding for member_id={member_id}")
                
            except Exception as e:
                print(f"[ENC] Error regenerating encoding for member_id={member_id}: {e}")
                error_count += 1
        
        print(f"[ENC] Regeneration complete. Success: {success_count}, Errors: {error_count}")
        return {"success": True, "success_count": success_count, "error_count": error_count}
        
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
                boxes = face_recognition.face_locations(img, model="hog")
                
                if not boxes:
                    print(f"[ENC] Wajah tidak ditemukan di member_id={member_id} url={full_url}")
                    skipped.append((member_id, "no_face"))
                    continue
                    
                # Ambil wajah pertama
                encoding = face_recognition.face_encodings(img, known_face_locations=[boxes[0]])
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
        self.cooldown_duration = 5  # 10 seconds cooldown
        # Track loaded member IDs for new data detection
        self.loaded_member_ids: set = set()
        # Auto-check interval for new data (seconds)
        self.auto_check_interval = 10  # Check every 10 seconds
        self.last_auto_check = 0

    def reload(self):
        with self.lock:
            self.known_encodings, self.known_names, self.known_ids, self.gym_member_id_mapping = build_known_encodings()
            self.last_reload = time.time()
            # Update loaded member IDs
            self.loaded_member_ids = set(self.known_ids)
            print(f"[RELOAD] Loaded {len(self.loaded_member_ids)} member encodings")
    
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
                    img = url_to_rgb_array(full_url)
                    boxes = face_recognition.face_locations(img, model="hog")
                    
                    if not boxes:
                        print(f"[AUTO-CHECK] No face found for member_id={member_id}")
                        error_count += 1
                        continue
                        
                    encoding = face_recognition.face_encodings(img, known_face_locations=[boxes[0]])
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
    
    def get_last_successful_member(self, device_id: str = None):
        """Get last successful member name for specific device"""
        if not device_id:
            return ""
        device_data = self.device_cooldowns.get(device_id)
        if not device_data:
            return ""
        return device_data.get('member', "")

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
        boxes = face_recognition.face_locations(rgb, model="hog")
        encs = face_recognition.face_encodings(rgb, boxes)

        for (top, right, bottom, left), enc in zip(boxes, encs):
            # Compute distance to all known encodings
            distances = face_recognition.face_distance(known_encs, enc)
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
    Background thread untuk auto-check data baru
    """
    while True:
        try:
            recognizer.check_for_new_members()
            time.sleep(5)  # Check every 5 seconds (faster than interval)
        except Exception as e:
            print(f"[BACKGROUND] Error in auto-check: {e}")
            time.sleep(30)  # Wait longer on error

# Start background thread
auto_check_thread = threading.Thread(target=background_auto_check, daemon=True)
auto_check_thread.start()
print("[BACKGROUND] Auto-check thread started")

# ===================== Flask App =====================
app = Flask(__name__)

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Face Recognition FTL GYM</title>
  <style>
    :root {
      --bg-primary: #ffffff;
      --bg-secondary: #f8f9fa;
      --text-primary: #212529;
      --text-secondary: #6c757d;
      --border-color: #dee2e6;
      --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    
    [data-theme="dark"] {
      --bg-primary: #1a1a1a;
      --bg-secondary: #2d2d2d;
      --text-primary: #ffffff;
      --text-secondary: #a0a0a0;
      --border-color: #404040;
      --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.2);
    }
    
    * { box-sizing: border-box; }
    
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0;
      padding: 0;
      background: var(--bg-primary);
      color: var(--text-primary);
      transition: background-color 0.3s ease, color 0.3s ease;
      min-height: 100vh;
    }
    
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
    }
    
    .header {
      text-align: center;
      margin-bottom: 30px;
    }
    
    .header h1 {
      margin: 0 0 10px 0;
      font-size: 2.5rem;
      font-weight: 700;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    
    .controls {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    
    .btn {
      padding: 12px 20px;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    
    .btn-primary {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
    }
    
    .btn-primary:hover {
      transform: translateY(-1px);
      box-shadow: var(--shadow-lg);
    }
    
    .btn-secondary {
      background: var(--bg-secondary);
      color: var(--text-primary);
      border: 1px solid var(--border-color);
    }
    
    .btn-secondary:hover {
      background: var(--border-color);
    }
    
    .btn-danger {
      background: #dc3545;
      color: white;
    }
    
    .btn-danger:hover {
      background: #c82333;
    }
    
    .theme-toggle {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      color: var(--text-primary);
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 18px;
    }
    
    .status {
      text-align: center;
      margin: 20px 0;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 500;
    }
    
    .status.success {
      background: #d4edda;
      color: #155724;
      border: 1px solid #c3e6cb;
    }
    
    .status.error {
      background: #f8d7da;
      color: #721c24;
      border: 1px solid #f5c6cb;
    }
    
    .status.info {
      background: #d1ecf1;
      color: #0c5460;
      border: 1px solid #bee5eb;
    }
    
    .camera-container {
      display: flex;
      justify-content: center;
      margin: 30px 0;
    }
    
    .camera-wrapper {
      position: relative;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
      background: #000;
      width: 100%;
      max-width: 960px;
      aspect-ratio: 4/3;
      min-height: 300px;
      max-height: 80vh;
    }
    
    
    .cooldown-display {
      position: absolute;
      top: 20px;
      right: 20px;
      background: linear-gradient(135deg, #ff6b35, #f7931e);
      color: white;
      padding: 12px 20px;
      border-radius: 12px;
      box-shadow: 0 8px 25px rgba(255, 107, 53, 0.3);
      z-index: 10;
      animation: pulse 1s ease-in-out infinite;
    }
    
    .cooldown-display.hidden {
      display: none;
    }
    
    .popup-notification {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 10000;
      padding: 30px 40px;
      border-radius: 20px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
      text-align: center;
      font-weight: 700;
      font-size: 24px;
      color: white;
      animation: popupSlideIn 0.5s ease-out;
      min-width: 300px;
      max-width: 500px;
    }
    
    .popup-notification.granted {
      background: linear-gradient(135deg, #10b981, #059669);
      border: 3px solid #34d399;
    }
    
    .popup-notification.denied {
      background: linear-gradient(135deg, #ef4444, #dc2626);
      border: 3px solid #f87171;
    }
    
    .popup-notification.hidden {
      display: none;
    }
    
    .popup-icon {
      font-size: 48px;
      margin-bottom: 15px;
      display: block;
    }
    
    .popup-title {
      font-size: 28px;
      margin-bottom: 10px;
      font-weight: 800;
    }
    
    .popup-message {
      font-size: 16px;
      opacity: 0.9;
      font-weight: 500;
      line-height: 1.4;
    }
    
    .popup-member-name {
      font-size: 20px;
      margin: 10px 0;
      font-weight: 700;
    }
    
    .popup-member-id {
      font-size: 14px;
      opacity: 0.8;
      margin-top: 5px;
    }
    
    @keyframes popupSlideIn {
      from {
        opacity: 0;
        transform: translate(-50%, -50%) scale(0.8);
      }
      to {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
      }
    }
    
    @keyframes popupSlideOut {
      from {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
      }
      to {
        opacity: 0;
        transform: translate(-50%, -50%) scale(0.8);
      }
    }
    
    .cooldown-content {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    
    .cooldown-icon {
      font-size: 24px;
      animation: spin 1s linear infinite;
    }
    
    .cooldown-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    
    .cooldown-title {
      font-size: 14px;
      font-weight: 600;
      opacity: 0.9;
    }
    
    .cooldown-time {
      font-size: 18px;
      font-weight: 700;
      font-family: 'Courier New', monospace;
    }
    
    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.05); }
    }
    
    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    
    
    /* Fullscreen styles */
    .camera-container:fullscreen {
      background: #000;
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100vw;
      height: 100vh;
    }
    
    .camera-container:fullscreen .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .camera-container:fullscreen #video,
    .camera-container:fullscreen #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    
    /* Fallback CSS fullscreen */
    .fullscreen-mode {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: #000;
      z-index: 9999;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode .camera-container {
      margin: 0;
      width: 100%;
      height: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .fullscreen-mode #video,
    .fullscreen-mode #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    .fullscreen-mode .controls,
    .fullscreen-mode .header,
    .fullscreen-mode #status {
      display: none;
    }
    
    
    .fullscreen-exit {
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 10001;
      background: rgba(0, 0, 0, 0.7);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 12px 20px;
      font-size: 14px;
      cursor: pointer;
      display: none;
    }
    
    .fullscreen-mode .fullscreen-exit {
      display: block;
    }
    
    /* Webkit fullscreen support */
    .camera-container:-webkit-full-screen {
      background: #000;
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100vw;
      height: 100vh;
    }
    
    .camera-container:-webkit-full-screen .camera-wrapper {
      width: 100vw;
      height: 100vh;
      max-width: none;
      max-height: none;
      display: flex;
      justify-content: center;
      align-items: center;
    }
    
    .camera-container:-webkit-full-screen #video,
    .camera-container:-webkit-full-screen #canvas {
      width: 100vw !important;
      height: 100vh !important;
      object-fit: cover;
      max-width: none;
      max-height: none;
    }
    
    
    #video {
      display: none;
      width: 100%;
      height: 100%;
      object-fit: cover;
      position: absolute;
      top: 0;
      left: 0;
    }
    
    #canvas {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      background: #000;
      max-width: 100%;
      max-height: 100%;
    }
    
    /* Mobile canvas adjustments */
    @media (max-width: 768px) {
      #canvas {
        object-fit: cover;
        max-width: 100%;
        max-height: 100%;
        width: auto !important;
        height: auto !important;
      }
      
      .camera-wrapper {
        display: flex;
        justify-content: center;
        align-items: center;
      }
    }
    
    .info-panel {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 20px;
      margin-top: 30px;
      text-align: center;
    }
    
    .info-panel h3 {
      margin: 0 0 15px 0;
      color: var(--text-primary);
    }
    
    .info-panel p {
      margin: 0;
      color: var(--text-secondary);
      line-height: 1.6;
    }
    
    .door-selector {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px 12px;
    }
    
    .door-selector label {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      margin: 0;
    }
    
    .door-selector select {
      background: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: 4px;
      padding: 6px 8px;
      font-size: 14px;
      color: var(--text-primary);
      cursor: pointer;
      min-width: 200px;
    }
    
    .door-selector select:focus {
      outline: none;
      border-color: var(--accent-color);
      box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2);
    }
    
    @media (max-width: 1024px) {
      .container { padding: 15px; }
      .header h1 { font-size: 2rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 4/3;
        max-height: 70vh;
      }
      .controls { flex-direction: column; gap: 8px; }
    }
    
    @media (max-width: 768px) {
      .container { padding: 10px; }
      .header h1 { font-size: 1.5rem; }
      .camera-wrapper { 
        max-width: 100%;
        aspect-ratio: 3/4;
        border-radius: 12px;
        max-height: 70vh;
        min-height: 300px;
      }
      .controls { 
        flex-direction: column; 
        gap: 8px; 
        margin-bottom: 15px;
      }
      .door-selector {
        flex-direction: column;
        align-items: flex-start;
        gap: 5px;
      }
      .door-selector select {
        min-width: 100%;
      }
    }
    
    @media (max-width: 480px) {
      .container { padding: 5px; }
      .header h1 { font-size: 1.2rem; }
      .camera-wrapper { 
        aspect-ratio: 3/4;
        border-radius: 8px;
        max-height: 65vh;
        min-height: 250px;
      }
    }
    
    /* Mobile landscape orientation */
    @media (max-width: 768px) and (orientation: landscape) {
      .camera-wrapper {
        aspect-ratio: 16/9;
        max-height: 80vh;
        min-height: 300px;
      }
      .controls {
        flex-direction: row;
        flex-wrap: wrap;
        gap: 5px;
      }
      .controls .btn {
        padding: 8px 12px;
        font-size: 12px;
      }
    }
    
    /* Very small screens */
    @media (max-width: 360px) {
      .container { padding: 3px; }
      .header h1 { font-size: 1rem; }
      .camera-wrapper { 
        aspect-ratio: 16/9;
        max-height: 45vh;
        min-height: 180px;
        border-radius: 6px;
      }
      .controls .btn {
        padding: 6px 10px;
        font-size: 11px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Face Recognition FTL GYM</h1>
      <p style="color: var(--text-secondary); margin: 0;">Powered by Horrizon</p>
  </div>
    
    <div class="controls">
      <button class="btn btn-primary" onclick="startCamera()">
        <span>📹</span> Start Camera
      </button>
      <button class="btn btn-danger" onclick="stopCamera()">
        <span>⏹️</span> Stop Camera
      </button>
      
      <div class="door-selector">
        <label for="doorSelect">Cabang:</label>
        <select id="doorSelect" onchange="updateDoorId()">
          <option value="">Pilih Cabang</option>
          <option value="19456">FTL - Center / Door 1</option>
          <option value="19418">FTL - Center / Reception - CT</option>
          <option value="19429">FTL - Benhil / Reception - BH</option>
          <option value="4">FTL - Tebet / Reception - TB</option>
        </select>
      </div>
      
      <button class="btn btn-secondary" onclick="toggleFullscreen()" title="Toggle Fullscreen">
        <span id="fullscreen-icon">⛶</span>
        <span id="fullscreen-text">Fullscreen</span>
      </button>
      
      <button class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
        <span id="theme-icon">🌙</span>
      </button>
      
    </div>
    
    <div id="status" class="status info">Click "Start Camera" to begin face recognition</div>
    
    <div class="camera-container">
      <div class="camera-wrapper">
        <video id="video" autoplay muted playsinline></video>
        <canvas id="canvas" width="960" height="720"></canvas>
        <div id="cooldown-display" class="cooldown-display hidden">
          <div class="cooldown-content">
            <div class="cooldown-icon">⏳</div>
            <div class="cooldown-text">
              <div class="cooldown-title">Cooldown</div>
              <div class="cooldown-time"><span id="cooldown-time">0.0</span>s</div>
            </div>
          </div>
        </div>
        <div id="popup-notification" class="popup-notification hidden">
          <div class="popup-icon" id="popup-icon">✅</div>
          <div class="popup-title" id="popup-title">ACCESS GRANTED</div>
          <div class="popup-member-name" id="popup-member-name">Member Name</div>
          <div class="popup-member-id" id="popup-member-id">Member #123456</div>
          <div class="popup-message" id="popup-message">Welcome to FTL Gym!</div>
        </div>
      </div>
    </div>
    
    <button class="fullscreen-exit" onclick="exitFullscreen()">
      <span>✕</span> Exit Fullscreen
    </button>
    
  </div>

  <script>
    // Dark mode functionality
    function toggleTheme() {
      const body = document.body;
      const themeIcon = document.getElementById('theme-icon');
      const currentTheme = body.getAttribute('data-theme');
      
      if (currentTheme === 'dark') {
        body.removeAttribute('data-theme');
        themeIcon.textContent = '🌙';
        localStorage.setItem('theme', 'light');
      } else {
        body.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
        localStorage.setItem('theme', 'dark');
      }
    }
    
    // Generate unique device ID
    function getDeviceId() {
      let deviceId = localStorage.getItem('deviceId');
      if (!deviceId) {
        deviceId = 'device_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('deviceId', deviceId);
      }
      return deviceId;
    }
    
    // Door ID functionality
    function updateDoorId() {
      const doorSelect = document.getElementById('doorSelect');
      const selectedDoorId = doorSelect.value;
      const deviceId = getDeviceId();
      
      // If no door selected, don't send to server
      if (!selectedDoorId) {
        console.log('[DOOR] No door selected');
        return;
      }
      
      console.log(`[DOOR] Updating door ID for device ${deviceId} to: ${selectedDoorId}`);
      
      // Send door ID to server with device ID
      fetch('/update_door_id', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Device-ID': deviceId
        },
        body: JSON.stringify({ 
          door_id: selectedDoorId,
          device_id: deviceId
        })
      })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          console.log(`[DOOR] Device ${deviceId} door ID updated to: ${selectedDoorId}`);
          updateStatus(`Cabang dipilih: ${doorSelect.options[doorSelect.selectedIndex].text}`, 'success');
        } else {
          console.error('[DOOR] Failed to update door ID:', data.error);
          updateStatus(`Failed to update door ID: ${data.error}`, 'error');
        }
      })
      .catch(error => {
        console.error('[DOOR] Error updating door ID:', error);
        updateStatus(`Error updating door ID: ${error}`, 'error');
      });
    }
    
    // Fullscreen functionality
    function toggleFullscreen() {
      if (document.fullscreenElement) {
        exitFullscreen();
      } else {
        enterFullscreen();
      }
    }
    
    function enterFullscreen() {
      const cameraContainer = document.querySelector('.camera-container');
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (cameraContainer.requestFullscreen) {
        cameraContainer.requestFullscreen().then(() => {
          cameraContainer.classList.add('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Exit';
          resizeCanvas();
        }).catch(err => {
          console.error('Error entering fullscreen:', err);
          // Fallback to CSS fullscreen
          document.querySelector('.container').classList.add('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Exit';
          resizeCanvas();
        });
      } else {
        // Fallback for browsers that don't support Fullscreen API
        document.querySelector('.container').classList.add('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Exit';
        resizeCanvas();
      }
    }
    
    function exitFullscreen() {
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (document.fullscreenElement) {
        document.exitFullscreen().then(() => {
          document.querySelector('.camera-container').classList.remove('fullscreen-mode');
          fullscreenIcon.textContent = '⛶';
          fullscreenText.textContent = 'Fullscreen';
          resizeCanvas();
        }).catch(err => {
          console.error('Error exiting fullscreen:', err);
        });
      } else {
        // Fallback for CSS fullscreen
        document.querySelector('.container').classList.remove('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Fullscreen';
        resizeCanvas();
      }
    }
    
    // Handle ESC key to exit fullscreen
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && document.fullscreenElement) {
        exitFullscreen();
      }
    });
    
    // Handle fullscreen change events
    document.addEventListener('fullscreenchange', function() {
      const cameraContainer = document.querySelector('.camera-container');
      const fullscreenIcon = document.getElementById('fullscreen-icon');
      const fullscreenText = document.getElementById('fullscreen-text');
      
      if (document.fullscreenElement) {
        cameraContainer.classList.add('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Exit';
      } else {
        cameraContainer.classList.remove('fullscreen-mode');
        fullscreenIcon.textContent = '⛶';
        fullscreenText.textContent = 'Fullscreen';
      }
      resizeCanvas();
    });
    
    // Handle window resize for responsiveness
    window.addEventListener('resize', function() {
      resizeCanvas();
    });
    
    // Handle orientation change on mobile
    window.addEventListener('orientationchange', function() {
      setTimeout(() => {
        resizeCanvas();
        console.log('[ORIENTATION] Orientation changed, canvas resized');
      }, 300);
    });
    
    // Handle window resize for mobile
    window.addEventListener('resize', function() {
      setTimeout(() => {
        resizeCanvas();
        console.log('[RESIZE] Window resized, canvas resized');
      }, 100);
    });
    
    // Load saved theme on page load
    document.addEventListener('DOMContentLoaded', function() {
      const savedTheme = localStorage.getItem('theme');
      const themeIcon = document.getElementById('theme-icon');
      
      if (savedTheme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
        themeIcon.textContent = '☀️';
      }
      
      // Reset door selection to default on page load
      const doorSelect = document.getElementById('doorSelect');
      if (doorSelect) {
        doorSelect.value = '';
      }
    });

    // Face recognition functionality
    let stream = null;
    let video = document.getElementById('video');
    let canvas = document.getElementById('canvas');
    let ctx = canvas.getContext('2d');
    let status = document.getElementById('status');
    let isProcessing = false;
    let inFlight = false;
    let lastFaces = [];
    let lastFacesTime = 0;
    const FACES_TTL_MS = 1200;
    const SMOOTHING_ALPHA = 0.5;
    const workCanvas = document.createElement('canvas');
    const workCtx = workCanvas.getContext('2d');
    
    // Simple popup control
    let currentPopupTimeout = null;
    

    function updateStatus(message, type = 'info') {
      status.textContent = message;
      status.className = 'status ' + type;
    }

    async function startCamera() {
      // Check if door ID is selected
      const doorSelect = document.getElementById('doorSelect');
      if (!doorSelect.value) {
        alert('Pilih Cabang terlebih dahulu!');
        updateStatus('Silakan pilih cabang sebelum memulai kamera', 'error');
        return;
      }
      
      // Ensure door ID is set for this device
      const deviceId = getDeviceId();
      console.log(`[CAMERA] Starting camera for device: ${deviceId}`);
      
      try {
        updateStatus('Requesting camera access...', 'info');
        stream = await navigator.mediaDevices.getUserMedia({ 
          video: { 
            width: 960, 
            height: 720,
            facingMode: 'user'
          } 
        });
        
        video.srcObject = stream;
        
        // Force video to load for Brave/Chrome
        video.load();
        
        // Wait for video to be ready before starting processing
        video.onloadedmetadata = function() {
          console.log('[CAMERA] Video metadata loaded');
          console.log('[CAMERA] Video dimensions:', video.videoWidth, 'x', video.videoHeight);
          console.log('[CAMERA] Video ready state:', video.readyState);
          console.log('[CAMERA] Canvas dimensions:', canvas.width, 'x', canvas.height);
          updateStatus(`Camera started successfully! (${video.videoWidth}x${video.videoHeight})`, 'success');
          
          // Force video to play for Brave/Chrome compatibility
          setTimeout(() => {
            video.play().then(() => {
              console.log('[CAMERA] Video play started');
              startProcessing();
            }).catch(err => {
              console.error('[CAMERA] Video play failed:', err);
              // Still start processing even if play fails
              startProcessing();
            });
          }, 100); // Small delay to ensure video is ready
        };
        
        video.onerror = function(e) {
          console.error('[CAMERA] Video error:', e);
          updateStatus('Video error occurred', 'error');
        };
        
        video.oncanplay = function() {
          console.log('[CAMERA] Video can play');
        };
        
        video.onplaying = function() {
          console.log('[CAMERA] Video is playing');
        };
        
        video.onloadeddata = function() {
          console.log('[CAMERA] Video data loaded');
        };
      } catch (error) {
        updateStatus('Camera access denied or not available: ' + error.message, 'error');
      }
    }

    function stopCamera() {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        updateStatus('Camera stopped', 'info');
      }
    }

    function startProcessing() {
      if (isProcessing) return;
      isProcessing = true;
      requestAnimationFrame(drawDisplay);
      processFrame();
    }

    let lastProcessTime = 0;
    let PROCESS_INTERVAL = 60; // recognition cadence - will be adjusted dynamically
    let performanceMetrics = {
      avgResponseTime: 0,
      requestCount: 0,
      slowRequests: 0
    };

    function processFrame() {
      if (!stream || !video.videoWidth) {
        if (isProcessing) {
          setTimeout(processFrame, 200);
        }
        return;
      }

      const now = Date.now();
      if (now - lastProcessTime < PROCESS_INTERVAL) {
        if (isProcessing) {
          setTimeout(processFrame, 100);
        }
        return;
      }
      lastProcessTime = now;

      // Downscale for recognition to reduce bandwidth/CPU
      const targetW = 320;  // Reduced from 640 to 320 for faster processing
      const scale = targetW / video.videoWidth;
      const targetH = Math.round(video.videoHeight * scale);
      workCanvas.width = targetW;
      workCanvas.height = targetH;
      workCtx.drawImage(video, 0, 0, targetW, targetH);

      if (inFlight) {
        if (isProcessing) setTimeout(processFrame, 50);
        return;
      }
      inFlight = true;

      // Send frame to server for face recognition
      const requestStartTime = Date.now();
      
      workCanvas.toBlob(function(blob) {
        const formData = new FormData();
        formData.append('frame', blob);
        
        const deviceId = getDeviceId();
        
        fetch('/recognize', {
          method: 'POST',
          headers: {
            'X-Device-ID': deviceId
          },
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          const responseTime = Date.now() - requestStartTime;
          updatePerformanceMetrics(responseTime);
          
          if (data.success) {
            updateFaces(data.faces, scale);
            updateCooldownDisplay(data.cooldown);
            console.log('[DEBUG] Received popup data:', data.popup);
            showPopupNotification(data.popup);
          } else {
            console.error('Recognition failed:', data.error);
          }
        })
        .catch(error => {
          console.error('Recognition error:', error);
        })
        .finally(() => { inFlight = false; });
      }, 'image/jpeg', 0.4);  // Reduced quality from 0.6 to 0.4 for faster upload

      if (isProcessing) {
        setTimeout(processFrame, 200);
      }
    }

    function updateFaces(newFaces, scale) {
      const upscaled = newFaces.map(f => ({
        x: Math.round(f.x / scale),
        y: Math.round(f.y / scale),
        width: Math.round(f.width / scale),
        height: Math.round(f.height / scale),
        name: f.name,
        confidence: f.confidence
      }));
      if (lastFaces.length === 0) {
        lastFaces = upscaled;
      } else {
        lastFaces = smoothFaces(lastFaces, upscaled);
      }
      lastFacesTime = Date.now();
    }
    

    function updateCooldownDisplay(cooldownInfo) {
      const cooldownDisplay = document.getElementById('cooldown-display');
      const cooldownTime = document.getElementById('cooldown-time');
      
      console.log('[COOLDOWN] Received cooldown info:', cooldownInfo);
      
      if (cooldownInfo && cooldownInfo.show) {
        console.log('[COOLDOWN] Showing cooldown for:', cooldownInfo.remaining);
        cooldownTime.textContent = cooldownInfo.remaining.toFixed(1);
        cooldownDisplay.classList.remove('hidden');
      } else {
        // Only hide if cooldown is explicitly false or not provided
        if (cooldownInfo === false || cooldownInfo === null) {
          cooldownDisplay.classList.add('hidden');
        }
        // If cooldownInfo is undefined, don't change display state
      }
    }
    
    function showPopupNotification(popupInfo) {
      console.log('[POPUP] Received popup info:', popupInfo);
      
      if (!popupInfo || !popupInfo.show) {
        console.log('[POPUP] No popup to show');
        return;
      }
      
      const popup = document.getElementById('popup-notification');
      const popupIcon = document.getElementById('popup-icon');
      const popupTitle = document.getElementById('popup-title');
      const popupMemberName = document.getElementById('popup-member-name');
      const popupMemberId = document.getElementById('popup-member-id');
      const popupMessage = document.getElementById('popup-message');
      
      // Clear any existing timeout
      if (currentPopupTimeout) {
        clearTimeout(currentPopupTimeout);
        currentPopupTimeout = null;
      }
      
      console.log('[POPUP] Showing popup:', popupInfo.style, 'for', popupInfo.member_name);
      
      // Set popup style
      popup.className = 'popup-notification';
      if (popupInfo.style === 'GRANTED') {
        popup.classList.add('granted');
        popupIcon.textContent = '✅';
        popupTitle.textContent = 'ACCESS GRANTED';
      } else if (popupInfo.style === 'DENIED') {
        popup.classList.add('denied');
        popupIcon.textContent = '❌';
        popupTitle.textContent = 'ACCESS DENIED';
      }
      
      // Set member information
      popupMemberName.textContent = popupInfo.member_name || 'Unknown Member';
      popupMemberId.textContent = `Member #${popupInfo.member_id || 'N/A'}`;
      popupMessage.textContent = popupInfo.message || 'Welcome to FTL Gym!';
      
      // Show popup
      popup.classList.remove('hidden');
      console.log('[POPUP] Popup displayed at:', new Date().toLocaleTimeString());
      
      // Hide after 5 seconds
      currentPopupTimeout = setTimeout(() => {
        console.log('[POPUP] Auto-hiding popup after 5 seconds at:', new Date().toLocaleTimeString());
        popup.classList.add('hidden');
        currentPopupTimeout = null;
      }, 5000);
    }
    
    
    function updatePerformanceMetrics(responseTime) {
      performanceMetrics.requestCount++;
      performanceMetrics.avgResponseTime = (performanceMetrics.avgResponseTime * (performanceMetrics.requestCount - 1) + responseTime) / performanceMetrics.requestCount;
      
      if (responseTime > 1000) {  // Consider > 1 second as slow
        performanceMetrics.slowRequests++;
      }
      
      // Adjust processing interval based on performance
      if (performanceMetrics.requestCount > 10) {  // After 10 requests, start adjusting
        const slowRequestRatio = performanceMetrics.slowRequests / performanceMetrics.requestCount;
        
        if (slowRequestRatio > 0.3) {  // If more than 30% are slow
          PROCESS_INTERVAL = Math.min(PROCESS_INTERVAL + 10, 100);  // Increase interval
          console.log(`[PERF] Performance degraded, increasing interval to ${PROCESS_INTERVAL}ms`);
        } else if (slowRequestRatio < 0.1 && performanceMetrics.avgResponseTime < 500) {  // If less than 10% slow and avg < 500ms
          PROCESS_INTERVAL = Math.max(PROCESS_INTERVAL - 5, 20);  // Decrease interval
          console.log(`[PERF] Performance good, decreasing interval to ${PROCESS_INTERVAL}ms`);
        }
      }
      
      console.log(`[PERF] Response time: ${responseTime}ms, Avg: ${performanceMetrics.avgResponseTime.toFixed(1)}ms, Slow: ${performanceMetrics.slowRequests}/${performanceMetrics.requestCount}`);
    }

    function smoothFaces(prev, curr) {
      const result = [];
      const used = new Array(curr.length).fill(false);
      for (let p of prev) {
        let bestIdx = -1;
        let bestIou = 0;
        for (let i = 0; i < curr.length; i++) {
          if (used[i]) continue;
          const iou = boxIoU(p, curr[i]);
          if (iou > bestIou) { bestIou = iou; bestIdx = i; }
        }
        if (bestIdx >= 0 && bestIou > 0.1) {
          const c = curr[bestIdx];
          used[bestIdx] = true;
          result.push({
            x: Math.round(p.x * (1-SMOOTHING_ALPHA) + c.x * SMOOTHING_ALPHA),
            y: Math.round(p.y * (1-SMOOTHING_ALPHA) + c.y * SMOOTHING_ALPHA),
            width: Math.round(p.width * (1-SMOOTHING_ALPHA) + c.width * SMOOTHING_ALPHA),
            height: Math.round(p.height * (1-SMOOTHING_ALPHA) + c.height * SMOOTHING_ALPHA),
            name: c.name || p.name,
            confidence: c.confidence
          });
        }
      }
      for (let i = 0; i < curr.length; i++) if (!used[i]) result.push(curr[i]);
      return result;
    }

    function boxIoU(a, b) {
      const x1 = Math.max(a.x, b.x);
      const y1 = Math.max(a.y, b.y);
      const x2 = Math.min(a.x + a.width, b.x + b.width);
      const y2 = Math.min(a.y + a.height, b.y + b.height);
      const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
      const areaA = a.width * a.height;
      const areaB = b.width * b.height;
      const union = areaA + areaB - inter;
      return union > 0 ? inter / union : 0;
    }

    function resizeCanvas() {
      if (!video || !canvas || !video.videoWidth || !video.videoHeight) return;
      
      const container = canvas.parentElement;
      const containerWidth = container.clientWidth;
      const containerHeight = container.clientHeight;
      const videoAspectRatio = video.videoWidth / video.videoHeight;
      
      console.log('[RESIZE] Container:', containerWidth, 'x', containerHeight);
      console.log('[RESIZE] Video:', video.videoWidth, 'x', video.videoHeight, 'aspect:', videoAspectRatio);
      
      // For fullscreen mode, use viewport dimensions
      if (container.classList.contains('fullscreen-mode') || document.fullscreenElement) {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        canvas.style.width = '100vw';
        canvas.style.height = '100vh';
        return;
      }
      
      // For mobile devices, use different aspect ratio handling
      const isMobile = window.innerWidth <= 768;
      const isLandscape = window.innerWidth > window.innerHeight;
      
      if (isMobile) {
        // Mobile: use 3:4 aspect ratio for portrait, 4:3 for landscape
        const isPortrait = window.innerHeight > window.innerWidth;
        const targetAspectRatio = isPortrait ? 3/4 : 4/3;
        
        let canvasWidth = containerWidth;
        let canvasHeight = containerWidth / targetAspectRatio;
        
        // If height exceeds container, scale down
        if (canvasHeight > containerHeight) {
          canvasHeight = containerHeight;
          canvasWidth = containerHeight * targetAspectRatio;
        }
        
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
        canvas.style.width = canvasWidth + 'px';
        canvas.style.height = canvasHeight + 'px';
        
        // Center the canvas
        canvas.style.margin = '0 auto';
        canvas.style.display = 'block';
        
        console.log('[RESIZE] Mobile canvas:', canvasWidth, 'x', canvasHeight, 'aspect:', targetAspectRatio, 'portrait:', isPortrait);
      } else {
        // Desktop: fill the entire container
        canvas.width = containerWidth;
        canvas.height = containerHeight;
        canvas.style.width = '100%';
        canvas.style.height = '100%';
      }
      
      console.log('[RESIZE] Canvas set to:', canvas.width, 'x', canvas.height, 'Mobile:', isMobile);
    }

    function drawDisplay() {
      if (!isProcessing) return;
      
      // Check if video is ready and has dimensions
      if (!video || !video.videoWidth || !video.videoHeight || video.readyState < 2) {
        // Video not ready, show loading message
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#fff';
        ctx.font = '20px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Loading camera...', canvas.width / 2, canvas.height / 2);
        requestAnimationFrame(drawDisplay);
        return;
      }
      
      // Additional check for Brave/Chrome - ensure video is actually playing
      if (video.paused || video.ended) {
        console.log('[CAMERA] Video is paused or ended, attempting to play');
        video.play().catch(err => console.error('[CAMERA] Play failed:', err));
        requestAnimationFrame(drawDisplay);
        return;
      }
      
      // Resize canvas to match video aspect ratio
      resizeCanvas();
      
      // Clear canvas first
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      
      // Draw video frame
      try {
        // Debug video state
        console.log('[DRAW] Video state:', {
          videoWidth: video.videoWidth,
          videoHeight: video.videoHeight,
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          readyState: video.readyState,
          paused: video.paused,
          ended: video.ended
        });
        
        // Ensure video is ready before drawing
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          // Try different drawing methods for better compatibility
          try {
            // For mobile, use cover method to maintain aspect ratio
            const isMobile = window.innerWidth <= 768;
            if (isMobile) {
              // Calculate aspect ratio preserving scaling
              const videoAspect = video.videoWidth / video.videoHeight;
              const canvasAspect = canvas.width / canvas.height;
              
              let sourceX = 0, sourceY = 0, sourceWidth = video.videoWidth, sourceHeight = video.videoHeight;
              let destX = 0, destY = 0, destWidth = canvas.width, destHeight = canvas.height;
              
              if (videoAspect > canvasAspect) {
                // Video is wider, crop sides
                sourceWidth = video.videoHeight * canvasAspect;
                sourceX = (video.videoWidth - sourceWidth) / 2;
              } else {
                // Video is taller, crop top/bottom
                sourceHeight = video.videoWidth / canvasAspect;
                sourceY = (video.videoHeight - sourceHeight) / 2;
              }
              
              // Save context state
              ctx.save();
              // Flip horizontally by scaling and translating
              ctx.scale(-1, 1);
              ctx.translate(-canvas.width, 0);
              // Draw video with horizontal flip
              ctx.drawImage(video, sourceX, sourceY, sourceWidth, sourceHeight, destX, destY, destWidth, destHeight);
              // Restore context state
              ctx.restore();
              console.log('[DRAW] Mobile video frame drawn with aspect ratio preservation and horizontal flip');
            } else {
              // Save context state
              ctx.save();
              // Flip horizontally by scaling and translating
              ctx.scale(-1, 1);
              ctx.translate(-canvas.width, 0);
              // Draw video with horizontal flip
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              // Restore context state
              ctx.restore();
              console.log('[DRAW] Desktop video frame drawn successfully with horizontal flip');
            }
          } catch (drawError) {
            console.error('[DRAW] drawImage failed:', drawError);
            // Fallback: try with source dimensions and horizontal flip
            ctx.save();
            ctx.scale(-1, 1);
            ctx.translate(-canvas.width, 0);
            ctx.drawImage(video, 0, 0, video.videoWidth, video.videoHeight, 0, 0, canvas.width, canvas.height);
            ctx.restore();
            console.log('[DRAW] Video frame drawn with fallback method and horizontal flip');
          }
        } else {
          console.log('[DRAW] Video not ready, skipping draw');
          ctx.fillStyle = '#ff0000';
          ctx.font = '16px Arial';
          ctx.textAlign = 'center';
          ctx.fillText('Video not ready', canvas.width / 2, canvas.height / 2);
        }
      } catch (e) {
        console.error('[DRAW] Error drawing video:', e);
        ctx.fillStyle = '#ff0000';
        ctx.font = '16px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Video drawing error: ' + e.message, canvas.width / 2, canvas.height / 2);
      }
      
      const now = Date.now();
      const showFaces = (now - lastFacesTime) < FACES_TTL_MS ? lastFaces : [];
      
      // Calculate scaling factors based on actual video dimensions
      const sx = video.videoWidth ? canvas.width / video.videoWidth : 1;
      const sy = video.videoHeight ? canvas.height / video.videoHeight : 1;
      
      for (const face of showFaces) {
        const { x, y, width, height, name, confidence, cooldown, cooldown_remaining } = face;
        // Adjust coordinates for horizontal flip
        const dx = Math.round((video.videoWidth - x - width) * sx);
        const dy = Math.round(y * sy);
        const dw = Math.round(width * sx);
        const dh = Math.round(height * sy);
        
        // Different colors for different states
        let color = '#ff0000'; // Default red for unknown
        if (cooldown) {
          color = '#ffa500'; // Orange for cooldown
        } else if (name !== 'Unknown') {
          color = '#00ff00'; // Green for recognized
        }
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(dx, dy, dw, dh);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(dx, dy + dh - 25, dw, 25);
        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        
        // Display different text based on state
        if (cooldown) {
          // Don't show cooldown in bounding box, it will be shown on screen
          ctx.fillText(`${name}`, dx + 5, dy + dh - 8);
        } else {
          ctx.fillText(`${name}`, dx + 5, dy + dh - 8);
        }
      }
      requestAnimationFrame(drawDisplay);
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', stopCamera);
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, tol=TOLERANCE)

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
        
        
        if not known_encs:
            return {"success": True, "faces": [], "debug": "No known encodings loaded"}
        
        # Detect faces with faster model
        boxes = face_recognition.face_locations(rgb, model="hog", number_of_times_to_upsample=0)
        
        if not boxes:
            return {"success": True, "faces": [], "debug": "No faces detected"}
        
        # Sort faces by size (largest first) and take only the first one
        face_sizes = [(i, (box[2] - box[0]) * (box[3] - box[1])) for i, box in enumerate(boxes)]
        face_sizes.sort(key=lambda x: x[1], reverse=True)  # Sort by area, largest first
        
        # Take only the largest face (most front)
        largest_face_idx = face_sizes[0][0]
        largest_box = boxes[largest_face_idx]
        
        # Generate encoding only for the largest face
        encs = face_recognition.face_encodings(rgb, [largest_box])
        
        if not encs:
            return {"success": True, "faces": [], "debug": "No face encoding generated"}
        
        faces = []
        # Process only the largest face
        (top, right, bottom, left) = largest_box
        enc = encs[0]  # Only one encoding for the largest face
        
        distances = face_recognition.face_distance(known_encs, enc)
        if len(distances) == 0:
            name = "Unknown"
            confidence = 1.0
            member_id = None
        else:
            idx = int(np.argmin(distances))
            confidence = float(distances[idx])
            name = known_names[idx] if confidence <= TOLERANCE else "Unknown"
            member_id = known_ids[idx] if confidence <= TOLERANCE else None
        
        # Get device ID for cooldown check
        device_id = request.headers.get('X-Device-ID', f"{request.remote_addr}_{request.headers.get('User-Agent', '')[:50]}")
        
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
                        "member_id": member_id,
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
    threading.Thread(target=recognizer.reload, daemon=True).start()
    return "Reload encodings dipicu. Tunggu 1-3 detik lalu refresh stream."

@app.route("/regenerate_enc")
def regenerate_enc_route():
    """
    Manually trigger regeneration of missing encodings
    """
    try:
        result = regenerate_missing_encodings()
        if result["success"]:
            return {
                "success": True,
                "message": f"ENC regeneration completed. Success: {result['success_count']}, Errors: {result['error_count']}",
                "success_count": result["success_count"],
                "error_count": result["error_count"]
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
              AND f.title = 'Profile2'
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
              AND f.title = 'Profile2'
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

@app.route("/check_new_members")
def check_new_members_route():
    """
    Manually trigger check for new members
    """
    try:
        # Force check by resetting last check time
        recognizer.last_auto_check = 0
        recognizer.check_for_new_members()
        
        return {
            "success": True,
            "message": "New members check completed",
            "loaded_members": len(recognizer.loaded_member_ids)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/debug_members")
def debug_members_route():
    """
    Debug endpoint to see current member status
    """
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

# ===================== Main =====================
if __name__ == "__main__":
    # Ensure ENC field exists and regenerate missing encodings
    print("[STARTUP] Ensuring ENC field exists...")
    add_enc_field_to_member_table()
    
    print("[STARTUP] Checking for missing encodings...")
    enc_status = regenerate_missing_encodings()
    if enc_status["success"]:
        print(f"[STARTUP] ENC regeneration: {enc_status['success_count']} success, {enc_status['error_count']} errors")
    else:
        print(f"[STARTUP] ENC regeneration failed: {enc_status['error']}")
    
    # Initial load
    print("[STARTUP] Loading encodings...")
    recognizer.reload()
    
    print(f"[STARTUP] Auto-check interval: {recognizer.auto_check_interval} seconds")
    print(f"[STARTUP] Loaded {len(recognizer.loaded_member_ids)} member encodings")
    print("[STARTUP] Server starting...")
    # Jalankan Flask
    # Akses di: http://127.0.0.1:8001/
    app.run(host="0.0.0.0", port=8001, debug=True, threaded=True)
