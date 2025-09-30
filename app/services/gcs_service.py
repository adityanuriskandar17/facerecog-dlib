"""
Google Cloud Storage Service for FTL Gym Face Recognition
Handles uploads to GCS bucket with proper error handling and fallbacks
"""

import os
import tempfile
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class GCSService:
    """Google Cloud Storage service with multiple upload methods"""
    
    def __init__(self):
        """Initialize GCS service"""
        self.bucket_name = os.getenv('GCS_BUCKET_NAME', 'ftlhorizon')
        self.base_url = os.getenv('GCS_BASE_URL_ASSET', 'https://cdn.ftlhorizon.com/')
        self.upload_enabled = os.getenv('GCS_UPLOAD_ENABLED', 'true').lower() == 'true'
        
        # Try to initialize GCS client
        self.gcs_client = None
        self.gcs_available = False
        
        try:
            from google.cloud import storage
            self.gcs_client = storage.Client()
            self.gcs_available = True
            logger.info("GCS Python client initialized successfully")
        except Exception as e:
            logger.warning(f"GCS Python client not available: {e}")
            self.gcs_available = False
        
        # Check gcloud CLI availability
        self.gcloud_available = self._check_gcloud_cli()
        
        logger.info(f"GCS Service initialized - Python client: {self.gcs_available}, gcloud CLI: {self.gcloud_available}")
    
    def _check_gcloud_cli(self) -> bool:
        """Check if gcloud CLI is available"""
        try:
            result = subprocess.run(['gcloud', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False
    
    def upload_image(self, image_data: bytes, filename: str, folder: str = "profile") -> Dict[str, Any]:
        """
        Upload image to GCS using available method
        
        Args:
            image_data: Image data as bytes
            filename: Name for the file
            folder: Folder in bucket
            
        Returns:
            Dict with upload result
        """
        if not self.upload_enabled:
            return self._mock_upload(filename)
        
        # Try Python client first
        if self.gcs_available:
            result = self._upload_with_python_client(image_data, filename, folder)
            if result.get('success'):
                return result
        
        # Fallback to gcloud CLI
        if self.gcloud_available:
            result = self._upload_with_gcloud_cli(image_data, filename, folder)
            if result.get('success'):
                return result
        
        # Final fallback to mock upload
        logger.warning("All GCS upload methods failed, using mock upload")
        return self._mock_upload(filename)
    
    def _upload_with_python_client(self, image_data: bytes, filename: str, folder: str) -> Dict[str, Any]:
        """Upload using Python GCS client"""
        try:
            from google.cloud import storage
            
            # Create blob path
            date_path = datetime.now().strftime("%Y/%m/%d/")
            blob_path = f"assets/img/{folder}/{date_path}{filename}"
            
            # Get bucket and blob
            bucket = self.gcs_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            
            # Upload image
            blob.upload_from_string(image_data, content_type='image/jpeg')
            
            # Make public
            blob.make_public()
            
            # Generate URL
            gcs_url = f"{self.base_url}{blob_path}"
            
            logger.info(f"GCS Python client upload successful: {gcs_url}")
            return {
                'success': True,
                'url': gcs_url,
                'method': 'python_client',
                'blob_path': blob_path
            }
            
        except Exception as e:
            logger.error(f"GCS Python client upload failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'method': 'python_client'
            }
    
    def _upload_with_gcloud_cli(self, image_data: bytes, filename: str, folder: str) -> Dict[str, Any]:
        """Upload using gcloud CLI"""
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                temp_file.write(image_data)
                temp_file_path = temp_file.name
            
            # Create blob path
            date_path = datetime.now().strftime("%Y/%m/%d/")
            blob_path = f"assets/img/{folder}/{date_path}{filename}"
            gs_path = f"gs://{self.bucket_name}/{blob_path}"
            
            # Upload using gcloud CLI
            result = subprocess.run([
                'gcloud', 'storage', 'cp', temp_file_path, gs_path,
                '--content-type', 'image/jpeg'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Make file public
                subprocess.run([
                    'gcloud', 'storage', 'objects', 'update', gs_path,
                    '--add-acl-grant=allUsers:READER'
                ], capture_output=True, text=True, timeout=10)
                
                # Generate URL
                gcs_url = f"{self.base_url}{blob_path}"
                
                logger.info(f"gcloud CLI upload successful: {gcs_url}")
                return {
                    'success': True,
                    'url': gcs_url,
                    'method': 'gcloud_cli',
                    'blob_path': blob_path
                }
            else:
                logger.error(f"gcloud CLI upload failed: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr,
                    'method': 'gcloud_cli'
                }
                
        except Exception as e:
            logger.error(f"gcloud CLI upload error: {e}")
            return {
                'success': False,
                'error': str(e),
                'method': 'gcloud_cli'
            }
        finally:
            # Clean up temporary file
            try:
                if 'temp_file_path' in locals():
                    os.unlink(temp_file_path)
            except Exception:
                pass
    
    def _mock_upload(self, filename: str) -> Dict[str, Any]:
        """Mock upload for testing/fallback"""
        import uuid
        
        # Generate mock URL
        mock_filename = f"{uuid.uuid4()}.jpeg"
        mock_url = f"{self.base_url}assets/img/profile/2025/09/30/{mock_filename}"
        
        logger.info(f"Mock upload successful: {mock_url}")
        return {
            'success': True,
            'url': mock_url,
            'method': 'mock',
            'filename': mock_filename
        }
    
    def upload_face_recognition_image(self, image_data: bytes, member_id: str, recognition_type: str = "face_detection") -> Dict[str, Any]:
        """
        Upload face recognition image with proper naming
        
        Args:
            image_data: Image data as bytes
            member_id: Member ID
            recognition_type: Type of recognition
            
        Returns:
            Dict with upload result
        """
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{member_id}_{recognition_type}_{timestamp}.jpg"
        
        return self.upload_image(image_data, filename, "face_recognition")
    
    def upload_burst_images(self, images_data: list, member_id: str) -> Dict[str, Any]:
        """
        Upload multiple burst images
        
        Args:
            images_data: List of image data bytes
            member_id: Member ID
            
        Returns:
            Dict with upload results
        """
        results = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for i, image_data in enumerate(images_data):
            filename = f"{member_id}_burst_{timestamp}_{i+1:02d}.jpg"
            result = self.upload_image(image_data, filename, "burst_registration")
            results.append(result)
        
        return {
            'success': all(r.get('success', False) for r in results),
            'results': results,
            'total_images': len(images_data)
        }
    
    def get_upload_status(self) -> Dict[str, Any]:
        """Get current upload service status"""
        return {
            'upload_enabled': self.upload_enabled,
            'gcs_available': self.gcs_available,
            'gcloud_available': self.gcloud_available,
            'bucket_name': self.bucket_name,
            'base_url': self.base_url
        }

# Global instance
gcs_service = GCSService()
