from flask import Blueprint, render_template, redirect, url_for, request, session
from .auth import require_login, fetch_member_profile

# Create main blueprint
main_bp = Blueprint('main', __name__)

@main_bp.route("/")
def index():
    """Redirect to retake page"""
    if not require_login():
        return redirect(url_for("auth.login"))
    return redirect(url_for("main.retake"))

@main_bp.route("/retake")
def retake():
    """Retake photo page"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
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

@main_bp.route("/recognition")
def recognition_page():
    """Face recognition page"""
    if not require_login():
        return redirect(url_for("auth.login"))
    
    # Import here to avoid circular imports
    from ..services.recognition_service import prepare_encodings
    
    try:
        print("[RECOG] Preparing encodings on-demand...")
        prepare_encodings()
    except Exception as e:
        print(f"[RECOG] Prepare error: {e}")
    
    return render_template("recognition.html")
