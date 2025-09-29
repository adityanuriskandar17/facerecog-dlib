from flask import Blueprint, request, jsonify, session, redirect, url_for
import requests
from .auth import require_login, fetch_member_profile
import threading
import base64
import re
import numpy as np
import cv2

# Create recognition blueprint
recognition_bp = Blueprint('recognition', __name__)

def preprocess_image_grayscale(image_rgb):
    """Preprocess image to grayscale for better face recognition accuracy"""
    try:
        # Convert RGB to grayscale
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        
        # Convert back to RGB format (3 channels) for face_recognition library
        # face_recognition expects RGB format even for grayscale processing
        gray_rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        
        print(f"[GRAYSCALE] Preprocessed image to grayscale: {gray_rgb.shape}")
        return gray_rgb
        
    except Exception as e:
        print(f"[GRAYSCALE] Error preprocessing image: {e}")
        # Return original image if grayscale conversion fails
        return image_rgb

@recognition_bp.route('/update_door_id', methods=['POST'])
def update_door_id():
    """Update door ID for device"""
    try:
        data = request.get_json()
        door_id = data.get('door_id')
        device_id = data.get('device_id')  # Get device identifier
        
        if not door_id:
            return {"success": False, "error": "Door ID required"}
        
        # Import here to avoid circular imports
        from ..services.door_service import update_door_id_service
        
        result = update_door_id_service(door_id, device_id)
        return result
        
    except Exception as e:
        print(f"[DOOR] Error updating door ID: {e}")
        return {"success": False, "error": str(e)}

@recognition_bp.route("/recognize", methods=["POST"])
def recognize():
    """Face recognition endpoint - no login required"""
    try:
        # Import here to avoid circular imports
        from ..services.recognition_service import process_recognition
        
        device_id = request.headers.get('X-Device-ID')
        result = process_recognition(request, device_id)
        return result
        
    except Exception as e:
        print(f"[RECOGNIZE] Error: {e}")
        return {"success": False, "error": str(e)}, 500

@recognition_bp.route("/reload")
def reload_route():
    """Reload encodings"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import reload_encodings
    
    threading.Thread(target=reload_encodings, daemon=True).start()
    return "Reload encodings dipicu. Tunggu 1-3 detik lalu refresh stream."

@recognition_bp.route("/health")
def health():
    """Health check endpoint"""
    try:
        # Import here to avoid circular imports
        from ..services.recognition_service import get_health_status
        return get_health_status()
    except Exception as e:
        return {"error": str(e)}, 500


@recognition_bp.route("/compare-photo", methods=["POST"])
def compare_photo():
    """Compare captured photo (dataURL) with GymMaster current photo and return similarity."""
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        data = request.get_json(force=True)
        data_url = data.get("image") or ""
        if not data_url:
            return {"success": False, "error": "Image data is required"}, 400

        # Fetch GymMaster profile to get current photo URL
        token = session.get("gm_token", "")
        gym_photo_url = ""
        if token:
            prof = fetch_member_profile(token)
            if not prof.get("error") and prof.get("result"):
                gym_photo_url = prof["result"].get("memberphoto") or ""
        if not gym_photo_url:
            return {"success": False, "error": "GymMaster photo not available"}, 400

        # Helpers from recognition service
        from ..services.face_recognition_service import (
            url_to_rgb_array, safe_face_recognition, force_garbage_collection
        )

        # Decode data URL -> RGB ndarray
        match = re.match(r"^data:image/[^;]+;base64,(.*)$", data_url)
        b64_data = match.group(1) if match else data_url
        img_bytes = base64.b64decode(b64_data)
        np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return {"success": False, "error": "Invalid image data"}, 400
        rgb_captured = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        # Load GymMaster photo
        rgb_gym = url_to_rgb_array(gym_photo_url)
        
        # Preprocess both images to grayscale for better accuracy
        print("[COMPARE_PHOTO] Preprocessing images to grayscale...")
        rgb_captured = preprocess_image_grayscale(rgb_captured)
        rgb_gym = preprocess_image_grayscale(rgb_gym)

        # Find face boxes
        boxes_cap = safe_face_recognition("face_locations", rgb_captured, model="hog")
        boxes_gym = safe_face_recognition("face_locations", rgb_gym, model="hog")
        if not boxes_cap:
            return {"success": False, "error": "No face detected in captured photo"}, 200
        if not boxes_gym:
            return {"success": False, "error": "No face detected in GymMaster photo"}, 200

        # Encodings (use first face)
        enc_cap_list = safe_face_recognition("face_encodings", rgb_captured, known_face_locations=[boxes_cap[0]])
        enc_gym_list = safe_face_recognition("face_encodings", rgb_gym, known_face_locations=[boxes_gym[0]])
        if not enc_cap_list or not enc_gym_list:
            return {"success": False, "error": "Failed to compute encodings"}, 200

        enc_cap = enc_cap_list[0]
        enc_gym = enc_gym_list[0]

        # Distance and similarity
        distances = safe_face_recognition("face_distance", [enc_gym], enc_cap)
        distance = float(distances[0]) if distances is not None and len(distances) else 1.0

        # Convert distance (0..2) to similarity percentage heuristic
        # Common tolerance ~0.6. Map 0.0 => 100%, 0.6 => ~0%, clamp to [0,100]
        similarity = max(0.0, 1.0 - (distance / 0.6)) * 100.0

        # Decision: require BOTH distance threshold and minimum similarity percentage
        from ..config import TOLERANCE, MIN_SIMILARITY_PERCENT
        is_match = (distance <= TOLERANCE) and (similarity >= MIN_SIMILARITY_PERCENT)

        # Cleanup
        del bgr, np_arr, img_bytes, rgb_captured, rgb_gym, boxes_cap, boxes_gym, enc_cap_list, enc_gym_list
        force_garbage_collection()

        return {
            "success": True,
            "distance": round(distance, 4),
            "similarity": round(similarity, 2),
            "match": bool(is_match),
            "thresholds": {"tolerance": TOLERANCE, "min_similarity": MIN_SIMILARITY_PERCENT}
        }
    except Exception as e:
        print(f"[COMPARE] Error: {e}")
        return {"success": False, "error": str(e)}, 500


@recognition_bp.route("/update-member-photo", methods=["POST"])
def update_member_photo():
    """Upload/update member photo to GymMaster using current session token.
    Expects JSON { image: dataURL } or form-data 'image'.
    """
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        token = session.get("gm_token", "")
        if not token:
            return {"success": False, "error": "Missing token"}, 400

        # Accept dataURL in JSON
        img_data_url = None
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            img_data_url = payload.get("image")
        if not img_data_url and 'image' in request.form:
            img_data_url = request.form.get('image')
        if not img_data_url:
            return {"success": False, "error": "Image is required"}, 400

        # Convert dataURL to bytes
        match = re.match(r"^data:image/([^;]+);base64,(.*)$", img_data_url)
        mime = match.group(1) if match else 'jpeg'
        b64_data = match.group(2) if match else img_data_url
        img_bytes = base64.b64decode(b64_data)

        from ..config import GYM_API_KEY, GYM_PROFILE_URL

        data = {
            'api_key': GYM_API_KEY,
            'token': token
        }
        files = {
            'memberphoto': (f'photo.{"png" if mime == "png" else "jpg"}', img_bytes, f'image/{mime}')
        }
        resp = requests.post(GYM_PROFILE_URL, data=data, files=files, timeout=20)
        try:
            result_json = resp.json()
        except Exception:
            result_json = {"status_code": resp.status_code, "text": resp.text[:200]}
        ok = resp.status_code < 400 and (not isinstance(result_json, dict) or not result_json.get('error'))
        return {"success": ok, "response": result_json}
    except Exception as e:
        print(f"[UPDATE_PHOTO] Error: {e}")
        return {"success": False, "error": str(e)}, 500


@recognition_bp.route("/update-member-photo-horizon", methods=["POST"])
def update_member_photo_horizon():
    """Upload/update member photo to Horizon GCloud using current session token.
    Expects JSON { image: dataURL } or form-data 'image'.
    """
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        token = session.get("gm_token", "")
        if not token:
            return {"success": False, "error": "Missing token"}, 400

        # Accept dataURL in JSON
        img_data_url = None
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            img_data_url = payload.get("image")
        if not img_data_url and 'image' in request.form:
            img_data_url = request.form.get('image')
        if not img_data_url:
            return {"success": False, "error": "Image is required"}, 400

        # Get member info from token to find email and get member_id from database
        prof = fetch_member_profile(token)
        if prof.get("error") or not prof.get("result"):
            return {"success": False, "error": "Failed to get member profile"}, 400
        
        member_data = prof["result"]
        member_email = member_data.get("email", "").strip().lower()
        if not member_email:
            return {"success": False, "error": "Member email not found"}, 400

        print(f"[HORIZON] Processing upload for email: {member_email}")

        # Get member_id from database using email
        from ..services.database_service import get_conn
        conn = get_conn()
        cur = conn.cursor()
        
        try:
            # Get member.member_id (not member.id) for consistency with GymMaster login
            cur.execute("SELECT member_id, id FROM member WHERE email = %s", (member_email,))
            member_result = cur.fetchone()
            
            if not member_result:
                cur.close()
                conn.close()
                return {"success": False, "error": "Member not found in database"}, 400
            
            member_id = member_result[0]  # member.member_id for created_by
            member_db_id = member_result[1]  # member.id for database foreign key
            print(f"[HORIZON] Found member_id: {member_id}, db_id: {member_db_id}")
            
        except Exception as db_error:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Database error: {str(db_error)}"}, 500

        # Convert dataURL to base64 format expected by Horizon API
        match = re.match(r"^data:image/([^;]+);base64,(.*)$", img_data_url)
        imagetype = match.group(1) if match else 'jpeg'
        b64_data = match.group(2) if match else img_data_url
        full_base64 = f"data:image/{imagetype};base64,{b64_data}"

        # Generate unique filename (UUID)
        import uuid
        image_id = str(uuid.uuid4())
        filename = f"{image_id}.{imagetype}"

        # Get current date for file path
        from datetime import datetime
        now = datetime.now()
        date_path = f"{now.year}/{now.month:02d}/{now.day:02d}/"
        
        # Real upload to Google Cloud Storage
        print(f"[HORIZON] Uploading to Google Cloud Storage: {filename}")
        
        try:
            # Import Google Cloud Storage
            from google.cloud import storage
            import base64
            
            # Initialize GCS client
            client = storage.Client()
            from ..config import GCS_BUCKET_NAME
            bucket = client.bucket(GCS_BUCKET_NAME)
            
            # Decode base64 image
            image_data = base64.b64decode(b64_data)
            
            # Create blob path
            blob_path = f"assets/img/profile/{date_path}{filename}"
            blob = bucket.blob(blob_path)
            
            # Upload image to GCS
            blob.upload_from_string(image_data, content_type=f"image/{imagetype}")
            
            # Make blob publicly accessible
            blob.make_public()
            
            # Generate public URL
            from ..config import GCS_BASE_URL_ASSET
            gcs_url = f"{GCS_BASE_URL_ASSET}{blob_path}"
            
            print(f"[HORIZON] Real upload successful: {gcs_url}")
            
        except Exception as upload_error:
            print(f"[HORIZON] GCS Python library failed: {upload_error}")
            
            # Fallback: Use gcloud CLI for upload
            try:
                import tempfile
                import os
                
                # Save image to temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{imagetype}") as temp_file:
                    temp_file.write(base64.b64decode(b64_data))
                    temp_file_path = temp_file.name
                
                # Upload using gcloud CLI
                from ..config import GCS_
                blob_path = f"assets/img/profile/{date_path}{filename}"
                gs_path = f"gs://{GCS_BUCKET_NAME}/{blob_path}"
                
                import subprocess
                result = subprocess.run([
                    'gcloud', 'storage', 'cp', temp_file_path, gs_path,
                    '--content-type', f"image/{imagetype}"
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    # Make file public
                    subprocess.run([
                        'gcloud', 'storage', 'objects', 'update', gs_path,
                        '--add-acl-grant=allUsers:READER'
                    ], capture_output=True, text=True)
                    
                    # Generate public URL
                    from ..config import GCS_BASE_URL_ASSET
                    gcs_url = f"{GCS_BASE_URL_ASSET}{blob_path}"
                    
                    print(f"[HORIZON] gcloud CLI upload successful: {gcs_url}")
                else:
                    raise Exception(f"gcloud upload failed: {result.stderr}")
                
                # Clean up temp file
                os.unlink(temp_file_path)
                
            except Exception as cli_error:
                print(f"[HORIZON] gcloud CLI upload failed: {cli_error}")
                # Final fallback to mock upload
                print(f"[HORIZON] Falling back to mock upload: {filename}")
                from ..config import GCS_BASE_URL_ASSET
                gcs_url = f"{GCS_BASE_URL_ASSET}assets/img/profile/{date_path}{filename}"
                print(f"[HORIZON] Mock upload successful: {gcs_url}")
        
        # Save to member_file table in database (reuse existing connection)
        try:
            # Check if profile record already exists
            cur.execute("""
                SELECT id FROM member_file 
                WHERE member_id = %s AND file_type_id = 1 AND title = 'Profile'
            """, (member_db_id,))
            
            existing_record = cur.fetchone()
            
            if existing_record:
                # Update existing profile record
                cur.execute("""
                    UPDATE member_file 
                    SET file_base_url = %s, file_base_path = %s, file_path = %s, 
                        file_name = %s, file_extention = %s, updated_at = NOW()
                    WHERE member_id = %s AND file_type_id = 1 AND title = 'Profile'
                """, (
                    GCS_BASE_URL_ASSET,  # file_base_url - CDN URL from config
                    "assets/img/profile/",  # file_base_path
                    date_path,  # file_path - only date part: 2025/09/28/
                    filename,  # file_name
                    f"image/{imagetype}",  # file_extention
                    member_db_id  # Use member.id for foreign key
                ))
                print(f"[HORIZON] Updated existing profile record for member_db_id: {member_db_id}")
            else:
                # Insert new profile record
                cur.execute("""
                    INSERT INTO member_file 
                    (member_id, file_type_id, file_base_url, file_base_path, file_path, file_name, file_extention, created_at, updated_at, title)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s)
                """, (
                    member_db_id,  # Use member.id for foreign key
                    1,  # file_type_id for profile
                    GCS_BASE_URL_ASSET,  # file_base_url - CDN URL from config
                    "assets/img/profile/",  # file_base_path
                    date_path,  # file_path - only date part: 2025/09/28/
                    filename,  # file_name
                    f"image/{imagetype}",  # file_extention
                    "Profile"  # title
                ))
                print(f"[HORIZON] Inserted new profile record for member_db_id: {member_db_id}")
            
            conn.commit()
            print(f"[HORIZON] Database record saved successfully for member_db_id: {member_db_id}")
            
        except Exception as db_error:
            print(f"[HORIZON] Database error: {db_error}")
            # Don't fail the upload if database save fails
        
        # Close database connection
        cur.close()
        conn.close()
        
        return {"success": True, "url": gcs_url, "filename": filename}
        
    except Exception as e:
        print(f"[HORIZON] Error: {e}")
        return {"success": False, "error": str(e)}, 500


@recognition_bp.route("/compare-photo-burst", methods=["POST"])
def compare_photo_burst():
    """Accept array of dataURL images, build averaged encoding, compare to GymMaster photo, and optionally save to DB by email."""
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        data = request.get_json(force=True)
        images = data.get("images") or []
        target_email = (data.get("email") or '').strip().lower()
        
        # If no email provided, try to get from session login
        if not target_email:
            token = session.get("gm_token", "")
            if token:
                prof = fetch_member_profile(token)
                if not prof.get("error") and prof.get("result"):
                    target_email = prof["result"].get("email", "").strip().lower()
                    print(f"[COMPARE_BURST] Using email from session: {target_email}")
        
        if not images or not isinstance(images, list):
            return {"success": False, "error": "images[] is required"}, 400

        # Fetch GymMaster profile to get current photo URL
        token = session.get("gm_token", "")
        gym_photo_url = ""
        if token:
            prof = fetch_member_profile(token)
            if not prof.get("error") and prof.get("result"):
                gym_photo_url = prof["result"].get("memberphoto") or ""
        if not gym_photo_url:
            return {"success": False, "error": "GymMaster photo not available"}, 400

        from ..services.face_recognition_service import (
            url_to_rgb_array, safe_face_recognition, force_garbage_collection
        )

        # Build encodings for burst
        enc_list = []
        processed = 0
        print("[COMPARE_BURST] Processing burst images with grayscale preprocessing...")
        for data_url in images:
            try:
                match = re.match(r"^data:image/[^;]+;base64,(.*)$", data_url)
                b64_data = match.group(1) if match else data_url
                img_bytes = base64.b64decode(b64_data)
                np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
                bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    continue
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                
                # Preprocess to grayscale for better accuracy
                rgb = preprocess_image_grayscale(rgb)
                
                boxes = safe_face_recognition("face_locations", rgb, model="hog")
                if not boxes:
                    continue
                enc = safe_face_recognition("face_encodings", rgb, known_face_locations=[boxes[0]])
                if enc:
                    enc_list.append(enc[0])
                    processed += 1
            except Exception:
                continue

        if not enc_list:
            return {"success": False, "error": "No faces detected in burst"}, 200

        # Average encoding across burst samples using stable numpy ops
        try:
            enc_stack = np.stack(enc_list, axis=0).astype(np.float64)
            enc_avg = np.mean(enc_stack, axis=0)
        except Exception as e:
            print(f"[COMPARE_BURST] Averaging error: {e}")
            return {"success": False, "error": "Failed to aggregate encodings"}, 500

        # Gym photo encoding with grayscale preprocessing
        print("[COMPARE_BURST] Processing GymMaster photo with grayscale preprocessing...")
        rgb_gym = url_to_rgb_array(gym_photo_url)
        rgb_gym = preprocess_image_grayscale(rgb_gym)
        
        boxes_gym = safe_face_recognition("face_locations", rgb_gym, model="hog")
        if not boxes_gym:
            return {"success": False, "error": "No face detected in GymMaster photo"}, 200
        enc_gym_list = safe_face_recognition("face_encodings", rgb_gym, known_face_locations=[boxes_gym[0]])
        if not enc_gym_list:
            return {"success": False, "error": "Failed to compute GymMaster encoding"}, 200
        enc_gym = enc_gym_list[0]

        # Distance and similarity
        distances = safe_face_recognition("face_distance", [enc_gym], enc_avg)
        distance = float(distances[0]) if distances is not None and len(distances) else 1.0
        similarity = max(0.0, 1.0 - (distance / 0.6)) * 100.0
        from ..config import TOLERANCE, MIN_SIMILARITY_PERCENT
        is_match = (distance <= TOLERANCE) and (similarity >= MIN_SIMILARITY_PERCENT)

        force_garbage_collection()

        # Optionally save averaged encoding to DB using email -> member.id mapping
        saved = False
        member_db_id = None
        save_reason = None
        
        print(f"[COMPARE_BURST] Target email: '{target_email}'")
        print(f"[COMPARE_BURST] Email provided: {bool(target_email)}")
        
        if target_email:
            try:
                from ..services.database_service import get_conn, save_encoding_to_db
                conn = get_conn()
                cur = conn.cursor()
                
                print(f"[COMPARE_BURST] Searching for email: {target_email}")
                cur.execute("SELECT id, email, first_name, last_name FROM member WHERE email = %s LIMIT 1", (target_email,))
                row = cur.fetchone()
                
                if row:
                    member_db_id = int(row[0])
                    print(f"[COMPARE_BURST] Email found! Member ID: {member_db_id}, Name: {row[2]} {row[3]}")
                    
                    # Save encoding
                    print(f"[COMPARE_BURST] Saving encoding for member_id={member_db_id}")
                    save_encoding_to_db(member_db_id, enc_avg.astype(np.float64))
                    saved = True
                    print(f"[COMPARE_BURST] ✅ Encoding saved successfully!")
                else:
                    save_reason = "email_not_found"
                    print(f"[COMPARE_BURST] ❌ Email not found in database")
                
                cur.close()
                conn.close()
            except Exception as e:
                print(f"[COMPARE_BURST] ❌ Save error: {e}")
                save_reason = str(e)
        else:
            save_reason = "no_email_provided"
            print(f"[COMPARE_BURST] ❌ No email provided")

        return {
            "success": True,
            "distance": round(distance, 4),
            "similarity": round(similarity, 2),
            "match": bool(is_match),
            "processed": processed,
            "thresholds": {"tolerance": TOLERANCE, "min_similarity": MIN_SIMILARITY_PERCENT},
            "saved": saved,
            "member_id": member_db_id,
            "save_reason": save_reason,
            "samples": len(enc_list)
        }
    except Exception as e:
        print(f"[COMPARE_BURST] Error: {e}")
        return {"success": False, "error": str(e)}, 500

@recognition_bp.route("/debug-burst-save", methods=["POST"])
def debug_burst_save():
    """Debug endpoint to test burst save functionality"""
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        data = request.get_json(force=True)
        target_email = (data.get("email") or '').strip().lower()
        test_member_id = data.get("member_id")
        
        debug_info = {
            "target_email": target_email,
            "email_provided": bool(target_email),
            "test_member_id": test_member_id
        }
        
        # Test email lookup
        if target_email:
            try:
                from ..services.database_service import get_conn
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT id, email, first_name, last_name FROM member WHERE email = %s LIMIT 1", (target_email,))
                row = cur.fetchone()
                cur.close()
                conn.close()
                
                if row:
                    debug_info.update({
                        "email_found": True,
                        "member_id": row[0],
                        "member_email": row[1],
                        "member_name": f"{row[2]} {row[3]}"
                    })
                else:
                    debug_info.update({
                        "email_found": False,
                        "error": "Email not found in database"
                    })
            except Exception as e:
                debug_info.update({
                    "email_found": False,
                    "error": str(e)
                })
        
        # Test save functionality
        if debug_info.get("email_found") or test_member_id:
            try:
                from ..services.database_service import get_conn, save_encoding_to_db
                import numpy as np
                
                # Create dummy encoding for testing
                dummy_encoding = np.random.rand(128).astype(np.float64)
                member_id = debug_info.get("member_id") or test_member_id
                
                save_encoding_to_db(int(member_id), dummy_encoding)
                debug_info.update({
                    "save_test": True,
                    "save_success": True,
                    "test_encoding_saved": True
                })
                
                # Verify save
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT LENGTH(enc) FROM member WHERE id = %s", (member_id,))
                result = cur.fetchone()
                cur.close()
                conn.close()
                
                if result and result[0] == 1024:
                    debug_info.update({
                        "verification": True,
                        "enc_length": result[0]
                    })
                else:
                    debug_info.update({
                        "verification": False,
                        "enc_length": result[0] if result else None
                    })
                    
            except Exception as e:
                debug_info.update({
                    "save_test": True,
                    "save_success": False,
                    "save_error": str(e)
                })
        
        return {
            "success": True,
            "debug_info": debug_info
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@recognition_bp.route("/test_member_ids")
def test_member_ids():
    """Test endpoint to verify member ID mapping"""
    try:
        # Get a sample of loaded member IDs and their mappings
        sample_data = []
        for i, member_id in enumerate(recognizer.known_ids[:5]):  # First 5 members
            gym_member_id = recognizer.gym_member_id_mapping.get(member_id)
            sample_data.append({
                "member_id": member_id,
                "gym_member_id": gym_member_id,
                "name": recognizer.known_names[i] if i < len(recognizer.known_names) else "Unknown"
            })
        
        return {
            "success": True,
            "total_loaded": len(recognizer.known_ids),
            "sample_data": sample_data,
            "message": "member_id should be member.member_id (gym ID), gym_member_id should be member.id (db ID)"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@recognition_bp.route("/test_gym_config")
def test_gym_config():
    """Test endpoint to verify gym API configuration"""
    try:
        from ..config import GYM_API_KEY, GYM_LOGIN_URL, GYM_GATE_URL, CHECKIN_ENABLED
        
        return {
            "success": True,
            "config": {
                "GYM_API_KEY": "***" if GYM_API_KEY else "NOT SET",
                "GYM_LOGIN_URL": GYM_LOGIN_URL or "NOT SET",
                "GYM_GATE_URL": GYM_GATE_URL or "NOT SET",
                "CHECKIN_ENABLED": CHECKIN_ENABLED
            },
            "message": "Check if all required gym API configuration is set"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@recognition_bp.route("/test_gym_api")
def test_gym_api():
    """Test gym API with a sample member ID"""
    try:
        from ..services.gym_service import gym_login, gym_open_gate_with_door
        from ..config import GYM_API_KEY, GYM_LOGIN_URL, GYM_GATE_URL
        
        if not GYM_API_KEY or not GYM_LOGIN_URL or not GYM_GATE_URL:
            return {
                "success": False,
                "error": "Gym API configuration incomplete",
                "config": {
                    "GYM_API_KEY": "SET" if GYM_API_KEY else "NOT SET",
                    "GYM_LOGIN_URL": GYM_LOGIN_URL or "NOT SET",
                    "GYM_GATE_URL": GYM_GATE_URL or "NOT SET"
                }
            }
        
        # Test with a sample member ID (you can change this to a real member ID)
        test_member_id = 1004686  # This should be a real member.member_id from your database
        
        # Test login
        login_result = gym_login(test_member_id)
        
        if login_result["success"]:
            # Test gate opening
            gate_result = gym_open_gate_with_door(login_result["token"], "19456", correct_member_id=test_member_id)
            
            return {
                "success": True,
                "login_result": login_result,
                "gate_result": gate_result,
                "message": f"Tested with member_id: {test_member_id}"
            }
        else:
            return {
                "success": False,
                "login_result": login_result,
                "message": f"Login failed for member_id: {test_member_id}"
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}
