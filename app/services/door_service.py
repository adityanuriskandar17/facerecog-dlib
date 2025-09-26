import time
from typing import Dict

# In-memory storage for door IDs (you might want to use Redis or database for production)
device_door_mapping = {}

def update_door_id_service(door_id: str, device_id: str) -> Dict:
    """Update door ID for a device"""
    try:
        if not door_id or not device_id:
            return {"success": False, "error": "Door ID and device ID required"}
        
        # Store the mapping
        device_door_mapping[device_id] = {
            'door_id': door_id,
            'updated_at': time.time()
        }
        
        print(f"[DOOR] Device {device_id} assigned to door {door_id}")
        
        return {
            "success": True,
            "message": f"Door ID {door_id} set for device {device_id}",
            "door_id": door_id,
            "device_id": device_id
        }
        
    except Exception as e:
        print(f"[DOOR] Error updating door ID: {e}")
        return {"success": False, "error": str(e)}

def get_door_id_for_device(device_id: str) -> str:
    """Get door ID for a device"""
    if device_id in device_door_mapping:
        return device_door_mapping[device_id]['door_id']
    return None

def get_all_device_door_mappings() -> Dict:
    """Get all device-door mappings"""
    return device_door_mapping.copy()
