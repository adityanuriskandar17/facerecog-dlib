import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database Configuration
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'deepface')

# Gym API Configuration
GYM_API_KEY = os.getenv('GYM_API_KEY', '')
GYM_BASE_URL = os.getenv('GYM_BASE_URL', '')
GYM_LOGIN_URL = os.getenv('GYM_LOGIN_URL', '')
GYM_PROFILE_URL = os.getenv('GYM_PROFILE_URL', '')

# Horizon GCloud Configuration
HORIZON_FASTAPI_URL = os.getenv('HORIZON_FASTAPI_URL', 'https://ftlhorizon.com')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'ftlhorizon')
GCS_BASE_URL_ASSET = os.getenv('GCS_BASE_URL_ASSET', 'https://cdn.ftlhorizon.com/')

# Flask Configuration
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# Face Recognition Configuration
TOLERANCE = float(os.getenv('TOLERANCE', '0.6'))  # Standard tolerance for face recognition
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '10'))
MIN_SIMILARITY_PERCENT = float(os.getenv('MIN_SIMILARITY_PERCENT', '50'))  

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_DB = int(os.getenv('REDIS_DB', '0'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
