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


@recognition_bp.route("/compare-photo-burst", methods=["POST"])
def compare_photo_burst():
    """Accept array of dataURL images, build averaged encoding, compare to GymMaster photo, and optionally save to DB by email."""
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401

        data = request.get_json(force=True)
        images = data.get("images") or []
        target_email = (data.get("email") or '').strip().lower()
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

        # Gym photo encoding
        rgb_gym = url_to_rgb_array(gym_photo_url)
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
        if target_email:
            try:
                from ..services.database_service import get_conn, save_encoding_to_db
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT id FROM member WHERE email = %s LIMIT 1", (target_email,))
                row = cur.fetchone()
                if row:
                    member_db_id = int(row[0])
                    save_encoding_to_db(member_db_id, enc_avg.astype(np.float64))
                    saved = True
                else:
                    save_reason = "email_not_found"
                cur.close()
                conn.close()
            except Exception as e:
                print(f"[COMPARE_BURST] Save error: {e}")
                save_reason = str(e)

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
