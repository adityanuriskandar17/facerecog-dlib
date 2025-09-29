import requests
from ..config import GYM_API_KEY, GYM_LOGIN_URL, GYM_GATE_URL, CHECKIN_ENABLED

def gym_login(member_id: int) -> dict:
    """
    Login to gym system and get token
    """
    try:
        if not CHECKIN_ENABLED or not GYM_LOGIN_URL:
            print("[GYM] GYM_LOGIN_URL is empty, skip calling login API")
            return {"success": False, "error": "Login API disabled"}
            
        payload = {
            "api_key": GYM_API_KEY,
            "memberid": member_id
        }
        
        print(f"[GYM] Logging in member_id: {member_id}")
        response = requests.post(GYM_LOGIN_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("error") is None:
            token = data.get("result", {}).get("token")
            if token:
                print(f"[GYM] Login successful for member_id: {member_id}")
                return {"success": True, "token": token}
            else:
                print(f"[GYM] No token in response for member_id: {member_id}")
                return {"success": False, "error": "No token received"}
        else:
            print(f"[GYM] Login failed for member_id: {member_id}: {data.get('error')}")
            return {"success": False, "error": data.get("error", "Login failed")}
            
    except requests.exceptions.RequestException as e:
        print(f"[GYM] Login request failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"[GYM] Login error: {e}")
        return {"success": False, "error": str(e)}

def gym_open_gate_with_door(token: str, door_id: str, correct_member_id: int = None) -> dict:
    """
    Open gym gate using token with specific door ID
    """
    try:
        if not CHECKIN_ENABLED or not GYM_GATE_URL:
            print(f"[GYM] GYM_GATE_URL is empty, skip calling gate API for door {door_id}")
            return {
                "success": True,
                "message": "Gate call skipped (URL empty)",
                "popup": {
                    "show": True,
                    "style": "GRANTED",
                    "member_name": "Unknown Member",
                    "member_id": "N/A",
                    "message": "Gate API disabled",
                    "cooldown_duration": 10
                }
            }
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
            # Use correct_member_id from database table if provided, otherwise fallback to API response
            member_id = correct_member_id if correct_member_id is not None else result.get("member_id", "N/A")
            print(f"[DEBUG] correct_member_id: {correct_member_id}, API member_id: {result.get('member_id')}, final member_id: {member_id}")
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
            # Use correct_member_id from database table if provided, otherwise fallback to API response
            member_id = correct_member_id if correct_member_id is not None else result.get("member_id", "N/A")
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

def process_member_detection_with_door(gym_member_id: int, member_name: str, door_id: str, db_member_id: int = None) -> dict:
    """
    Process member detection with specific door ID: login and open gate
    """
    print(f"[GYM] Processing detection for {member_name} (Gym ID: {gym_member_id}, DB ID: {db_member_id}) with door {door_id}")
    
    # Step 1: Login to get token using gym_member_id (member.member_id) for API
    # The login API expects member.member_id (gym member ID like 1004686)
    login_result = gym_login(gym_member_id)
    if not login_result["success"]:
        return {"success": False, "error": f"Login failed: {login_result['error']}"}
    
    # Step 2: Open gate using token with specific door ID
    # Pass the gym_member_id for popup display (this is what should be shown to user)
    print(f"[DEBUG] process_member_detection_with_door: gym_member_id={gym_member_id}, db_member_id={db_member_id}, using gym_member_id for display")
    gate_result = gym_open_gate_with_door(login_result["token"], door_id, correct_member_id=gym_member_id)
    
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
