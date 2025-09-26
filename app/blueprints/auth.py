from flask import Blueprint, render_template, request, session, redirect, url_for
import requests

from ..config import GYM_API_KEY, GYM_BASE_URL, GYM_LOGIN_URL, GYM_PROFILE_URL

# Create auth blueprint
auth_bp = Blueprint('auth', __name__)

def require_login():
    """Check if user is logged in"""
    return bool(session.get("logged_in"))

def gym_login_with_email(email: str, password: str) -> dict:
    """Authenticate user with gym API"""
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
    """Fetch member profile from gym API"""
    try:
        params = {"token": token, "api_key": GYM_API_KEY}
        r = requests.get(GYM_PROFILE_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page and authentication"""
    if request.method == "POST":
        email = (request.form.get("email") or '').strip().lower()
        password = request.form.get("password") or ''
        result = gym_login_with_email(email, password)
        if result.get("success") and result.get("token"):
            session["logged_in"] = True
            session["gm_token"] = result.get("token")
            return redirect(url_for("main.retake"))
        return render_template("login.html", error="Invalid email or password")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    """Logout user and clear session"""
    session.clear()
    return redirect(url_for("auth.login"))
