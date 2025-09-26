from flask import Blueprint, request, jsonify, session
from .auth import require_login
import threading

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
    """Face recognition endpoint"""
    try:
        if not require_login():
            return {"success": False, "error": "Unauthorized"}, 401
        
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
