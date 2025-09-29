#!/usr/bin/env python3
"""
Test script untuk debug burst face recognition save functionality
"""

import requests
import json

def test_debug_endpoint():
    """Test debug endpoint untuk burst save"""
    url = "http://localhost:8001/debug-burst-save"
    
    # Test data
    test_data = {
        "email": "test@example.com",  # Ganti dengan email yang ada di database
        "member_id": 1  # Optional: test dengan member_id langsung
    }
    
    try:
        response = requests.post(url, json=test_data)
        result = response.json()
        
        print("=== DEBUG BURST SAVE TEST ===")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(result, indent=2)}")
        
        if result.get("success"):
            debug_info = result.get("debug_info", {})
            print("\n=== ANALYSIS ===")
            print(f"Email provided: {debug_info.get('email_provided')}")
            print(f"Email found: {debug_info.get('email_found')}")
            print(f"Save test: {debug_info.get('save_test')}")
            print(f"Save success: {debug_info.get('save_success')}")
            print(f"Verification: {debug_info.get('verification')}")
            
            if debug_info.get("error"):
                print(f"Error: {debug_info.get('error')}")
        else:
            print(f"Error: {result.get('error')}")
            
    except Exception as e:
        print(f"Request error: {e}")

def test_compare_burst_endpoint():
    """Test compare-photo-burst endpoint dengan dummy data"""
    url = "http://localhost:8001/compare-photo-burst"
    
    # Dummy test data (tidak akan benar-benar process image)
    test_data = {
        "images": ["data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD..."],  # Dummy base64
        "email": "test@example.com"  # Ganti dengan email yang ada di database
    }
    
    try:
        response = requests.post(url, json=test_data)
        result = response.json()
        
        print("\n=== COMPARE BURST TEST ===")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(result, indent=2)}")
        
        if result.get("success"):
            print(f"Saved: {result.get('saved')}")
            print(f"Member ID: {result.get('member_id')}")
            print(f"Save reason: {result.get('save_reason')}")
        else:
            print(f"Error: {result.get('error')}")
            
    except Exception as e:
        print(f"Request error: {e}")

def check_database_emails():
    """Check available emails in database"""
    try:
        from app.services.database_service import get_conn
        
        conn = get_conn()
        cur = conn.cursor()
        
        # Get sample emails
        cur.execute("SELECT id, email, first_name, last_name FROM member WHERE email IS NOT NULL AND email != '' LIMIT 5")
        rows = cur.fetchall()
        
        print("\n=== SAMPLE EMAILS IN DATABASE ===")
        for row in rows:
            print(f"ID: {row[0]}, Email: {row[1]}, Name: {row[2]} {row[3]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    print("🔍 BURST FACE RECOGNITION DEBUG TOOL")
    print("=" * 50)
    
    # Check database emails
    check_database_emails()
    
    # Test debug endpoint
    test_debug_endpoint()
    
    # Test compare burst endpoint
    test_compare_burst_endpoint()
    
    print("\n=== INSTRUCTIONS ===")
    print("1. Ganti 'test@example.com' dengan email yang ada di database")
    print("2. Jalankan aplikasi: python app.py")
    print("3. Cek server logs untuk detailed logging")
    print("4. Test burst face recognition di browser")
    print("5. Cek response untuk 'saved' dan 'save_reason'")
