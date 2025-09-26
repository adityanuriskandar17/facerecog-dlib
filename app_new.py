#!/usr/bin/env python3
"""
Face Recognition System - Refactored Version
Main application entry point using modular structure
"""

from app import create_app
from app.services.recognition_service import recognizer
import threading
import time

# Create Flask application
app = create_app()

def background_auto_check():
    """Background thread untuk auto-check data baru dengan memory management"""
    while True:
        try:
            recognizer.check_for_new_members()
            # Force garbage collection after each check
            from app.services.face_recognition_service import force_garbage_collection
            force_garbage_collection()
            time.sleep(10)  # Increased interval to reduce load
        except Exception as e:
            print(f"[BACKGROUND] Error in auto-check: {e}")
            time.sleep(60)  # Wait longer on error

if __name__ == "__main__":
    # Initial load of encodings
    print("[STARTUP] Loading initial encodings...")
    try:
        from app.services.recognition_service import prepare_encodings
        prepare_encodings()
        print("[STARTUP] Initial encodings loaded successfully")
    except Exception as e:
        print(f"[STARTUP] Error loading initial encodings: {e}")
    
    # Start background thread for auto-checking new members
    print("[STARTUP] Starting background auto-check thread...")
    background_thread = threading.Thread(target=background_auto_check, daemon=True)
    background_thread.start()
    
    # Start Flask application
    print("[STARTUP] Starting Flask application...")
    app.run(host="0.0.0.0", port=8001, debug=False, threaded=True)
