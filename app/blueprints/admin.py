from flask import Blueprint, redirect, url_for, request, jsonify
from .auth import require_login

# Create admin blueprint
admin_bp = Blueprint('admin', __name__)

@admin_bp.route("/check_new_members")
def check_new_members_route():
    """Manual check for new members"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import check_new_members
    
    try:
        result = check_new_members()
        return f"New members check completed. Result: {result}"
    except Exception as e:
        return f"Error checking new members: {e}", 500

@admin_bp.route("/regenerate_enc")
def regenerate_enc_route():
    """Manually trigger regeneration of missing encodings"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import regenerate_encodings_manual
    
    try:
        result = regenerate_encodings_manual()
        return f"ENC regeneration triggered. Result: {result}"
    except Exception as e:
        return f"Error regenerating encodings: {e}", 500

@admin_bp.route("/enc_status")
def enc_status_route():
    """Check ENC status for all members"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import get_enc_status
    
    try:
        result = get_enc_status()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/debug_members")
def debug_members_route():
    """Debug endpoint to see current member status"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import get_debug_members
    
    try:
        result = get_debug_members()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/set_auto_check_interval", methods=['POST'])
def set_auto_check_interval_route():
    """Set auto-check interval for new members (in seconds)"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    try:
        data = request.get_json()
        interval = data.get('interval', 300)  # Default 5 minutes
        
        # Import here to avoid circular imports
        from ..services.recognition_service import set_auto_check_interval
        
        result = set_auto_check_interval(interval)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# GCP specific routes
@admin_bp.route("/gcp_debug")
def gcp_debug_route():
    """GCP specific debug endpoint"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import get_gcp_debug
    
    try:
        result = get_gcp_debug()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/gcp_load_on_demand")
def gcp_load_on_demand_route():
    """Load encodings on-demand for GCP"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import gcp_load_on_demand
    
    try:
        result = gcp_load_on_demand()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Redis specific routes
@admin_bp.route("/redis_status")
def redis_status_route():
    """Check Redis connection and cache status"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.redis_service import get_redis_status
    
    try:
        result = get_redis_status()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/redis_clear_cache")
def redis_clear_cache_route():
    """Clear Redis cache"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.redis_service import clear_redis_cache
    
    try:
        result = clear_redis_cache()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/redis_reload")
def redis_reload_route():
    """Force reload encodings and update Redis cache"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.redis_service import redis_reload
    
    try:
        result = redis_reload()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/redis_cleanup")
def redis_cleanup_route():
    """Clean up removed members from Redis cache"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.redis_service import cleanup_removed_members
    
    try:
        result = cleanup_removed_members()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
