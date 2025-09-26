import face_recognition
import numpy as np
import requests
import cv2
import gc
from typing import List, Optional

def safe_face_recognition(func_name: str, *args, **kwargs):
    """Safely call face_recognition functions with error handling"""
    try:
        func = getattr(face_recognition, func_name)
        result = func(*args, **kwargs)
        return result
    except Exception as e:
        print(f"[FACE_REC] Error in {func_name}: {e}")
        return None

def url_to_rgb_array(url: str) -> Optional[np.ndarray]:
    """Download image from URL and convert to RGB array"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Convert to numpy array
        img_array = np.frombuffer(response.content, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if img is None:
            return None
        
        # Convert BGR to RGB
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return rgb
        
    except Exception as e:
        print(f"[FACE_REC] Error loading image from URL {url}: {e}")
        return None

def force_garbage_collection():
    """Force garbage collection to free memory"""
    try:
        gc.collect()
    except Exception as e:
        print(f"[FACE_REC] Error in garbage collection: {e}")
