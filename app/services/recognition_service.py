import time
import threading
import numpy as np
import cv2
from typing import List, Dict, Tuple

from ..config import TOLERANCE, BATCH_SIZE, MIN_SIMILARITY_PERCENT
from .database_service import (
    get_conn, fetch_member_images, load_encoding_from_db, save_encoding_to_db,
    build_known_encodings_fast, add_enc_field_to_member_table, regenerate_missing_encodings
)
from .redis_service import get_cached_encodings, cache_encodings, REDIS_ENABLED
from .face_recognition_service import (
    safe_face_recognition, url_to_rgb_array, force_garbage_collection
)

# Constants
REQUIRED_CONSISTENT_FRAMES = 3

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
        """Check for new members that don't have encodings yet"""
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
        """Process new members and generate their encodings"""
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
        """Detect & recognize faces in BGR frame. Draw boxes & labels."""
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

# Global recognizer instance
recognizer = Recognizer()

# Service functions
def prepare_encodings():
    """Prepare encodings for recognition"""
    add_enc_field_to_member_table()
    enc_status = regenerate_missing_encodings(BATCH_SIZE, regenerate_all=False)
    if not enc_status.get("success"):
        print(f"[RECOG] ENC regeneration skip/error: {enc_status.get('error')}")
    recognizer.reload()

def reload_encodings():
    """Reload encodings"""
    recognizer.reload()

def check_new_members():
    """Check for new members"""
    return recognizer.check_for_new_members()

def regenerate_encodings_manual():
    """Manually regenerate encodings"""
    return regenerate_missing_encodings(BATCH_SIZE, regenerate_all=False)

def get_enc_status():
    """Get encoding status"""
    # Implementation needed
    return {"status": "ok"}

def get_debug_members():
    """Get debug members info"""
    # Implementation needed
    return {"members": []}

def set_auto_check_interval(interval):
    """Set auto check interval"""
    recognizer.auto_check_interval = interval
    return {"success": True, "interval": interval}

def get_gcp_debug():
    """Get GCP debug info"""
    # Implementation needed
    return {"status": "ok"}

def gcp_load_on_demand():
    """GCP load on demand"""
    # Implementation needed
    return {"status": "ok"}

def get_health_status():
    """Get health status"""
    with recognizer.lock:
        n = len(recognizer.known_encodings)
        last = recognizer.last_reload
    return {
        "encodings_count": n,
        "last_reload": last,
        "status": "healthy"
    }

def process_recognition(request, device_id):
    """Process recognition request - implements face recognition logic from app_old.py"""
    try:
        from flask import request
        import numpy as np
        import cv2
        import time
        
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
        
        # Load encodings on-demand if not loaded
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
                return {"success": False, "error": "Failed to load encodings"}
        
        # Face detection
        face_locations = safe_face_recognition("face_locations", rgb, model="hog")
        if not face_locations:
            return {"success": True, "faces": [], "debug": "No faces detected"}
        
        # Get face encodings
        face_encodings = safe_face_recognition("face_encodings", rgb, known_face_locations=face_locations)
        if not face_encodings:
            return {"success": True, "faces": [], "debug": "No face encodings computed"}
        
        faces = []
        current_time = time.time()
        
        # Check device cooldown
        if device_id in recognizer.device_cooldowns:
            last_access = recognizer.device_cooldowns[device_id].get('last_access', 0)
            if current_time - last_access < 2.0:  # 2 second cooldown
                return {"success": True, "faces": [], "debug": "Cooldown active"}
        
        # Process each detected face
        for i, (face_encoding, face_location) in enumerate(zip(face_encodings, face_locations)):
            # Compare with known faces
            if known_encs:
                matches = safe_face_recognition("compare_faces", known_encs, face_encoding, tolerance=TOLERANCE)
                face_distances = safe_face_recognition("face_distance", known_encs, face_encoding)
            else:
                matches = []
                face_distances = []
            
            name = "Unknown"
            confidence = 0.0
            member_id = None
            
            if matches and any(matches):
                # Find the best match with strict distance checking
                best_match_idx = None
                best_distance = float('inf')
                
                for j, (match, distance) in enumerate(zip(matches, face_distances)):
                    if match and distance < best_distance:
                        best_distance = distance
                        best_match_idx = j
                
                # Only accept if distance is below tolerance AND confidence is high enough
                if best_match_idx is not None:
                    confidence = max(0.0, 1.0 - best_distance) * 100
                    
                    # Double check: distance must be below tolerance AND confidence above threshold
                    if best_distance <= TOLERANCE and confidence >= MIN_SIMILARITY_PERCENT:
                        name = known_names[best_match_idx]
                        member_id = known_ids[best_match_idx]
                        print(f"[RECOG] Match found: {name} (distance: {best_distance:.3f}, confidence: {confidence:.1f}%)")
                    else:
                        print(f"[RECOG] Match too weak: distance={best_distance:.3f} (tolerance={TOLERANCE}), confidence={confidence:.1f}% (min={MIN_SIMILARITY_PERCENT}%)")
                        # Keep as Unknown
                        name = "Unknown"
                        confidence = 0.0
                        member_id = None
            
            # Check device cooldown for this specific person
            cooldown_info = None
            if device_id in recognizer.device_cooldowns:
                device_info = recognizer.device_cooldowns[device_id]
                if device_info.get('member') == name:
                    last_login = device_info.get('last_login', 0)
                    remaining = max(0, recognizer.cooldown_duration - (current_time - last_login))
                    if remaining > 0:
                        cooldown_info = {
                            "show": True,
                            "remaining": remaining
                        }
            
            # Update prediction streak for multi-frame confirmation
            if name != "Unknown":
                if device_id not in recognizer.device_prediction_streak:
                    recognizer.device_prediction_streak[device_id] = {"name": name, "count": 0}
                
                current_streak = recognizer.device_prediction_streak[device_id]
                if current_streak["name"] == name:
                    current_streak["count"] += 1
                else:
                    current_streak["name"] = name
                    current_streak["count"] = 1
            
            # Extract face coordinates
            top, right, bottom, left = face_location
            faces.append({
                "x": int(left),
                "y": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
                "name": name,
                "confidence": confidence,
                "member_id": member_id,
                "cooldown": cooldown_info is not None,
                "cooldown_remaining": cooldown_info["remaining"] if cooldown_info else 0
            })
        
        # Update device info
        recognizer.device_cooldowns[device_id] = {
            'last_access': current_time
        }
        
        # Check if we should show popup (granted access)
        popup_info = None
        if faces:
            best_face = max(faces, key=lambda f: f["confidence"])
            if best_face["name"] != "Unknown" and best_face["confidence"] > 50:
                # Check if we have enough consistent frames
                current_streak = recognizer.device_prediction_streak.get(device_id, {"name": "", "count": 0})
                if current_streak["count"] >= REQUIRED_CONSISTENT_FRAMES:
                    # Show access granted popup
                    popup_info = {
                        "show": True,
                        "style": "GRANTED",
                        "member_name": best_face["name"],
                        "member_id": best_face["member_id"],
                        "message": "Welcome to FTL Gym!"
                    }
                    
                    # Update cooldown
                    recognizer.device_cooldowns[device_id] = {
                        'last_access': current_time,
                        'last_login': current_time,
                        'member': best_face["name"]
                    }
                    
                    # Reset prediction streak
                    recognizer.device_prediction_streak[device_id] = {"name": "", "count": 0}
        
        # Force garbage collection
        force_garbage_collection()
        
        return {
            "success": True, 
            "faces": faces, 
            "popup": popup_info,
            "cooldown": None,
            "debug": f"Processed {len(known_encs)} encodings"
        }
        
    except Exception as e:
        print(f"[RECOGNIZE] Recognition error: {e}")
        return {"success": False, "error": str(e)}
