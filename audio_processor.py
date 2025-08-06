import os
import logging
import subprocess
import shutil
from pydub import AudioSegment
from werkzeug.utils import secure_filename
from config import Config

logger = logging.getLogger(__name__)

class AudioProcessor:
    """Handles audio file processing and validation"""
    
    @staticmethod
    def validate_audio_file(file):
        """Validate uploaded audio file"""
        if not file or not file.filename:
            return False, "No audio file provided"
        
        # Check file size
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size > Config.MAX_AUDIO_FILE_SIZE:
            return False, f"File too large. Maximum size: {Config.MAX_AUDIO_FILE_SIZE / 1024 / 1024:.1f}MB"
        
        # Check file extension
        filename = secure_filename(file.filename.lower())
        extension = filename.rsplit('.', 1)[-1] if '.' in filename else ''
        
        if extension not in Config.SUPPORTED_AUDIO_FORMATS:
            return False, f"Unsupported format. Supported: {', '.join(Config.SUPPORTED_AUDIO_FORMATS)}"
        
        return True, None
    
    @staticmethod
    def check_ffmpeg():
        """Check if ffmpeg is available"""
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL, 
                         check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("ffmpeg not found - some audio conversions may fail")
            return False
    
    @staticmethod
    def convert_to_wav(input_path, output_path):
        """Convert audio file to WAV format"""
        try:
            # First try with pydub
            try:
                audio = AudioSegment.from_file(input_path)
                audio.export(output_path, format="wav")
                logger.info(f"Converted {input_path} to WAV using pydub")
                return True
            except Exception as pydub_error:
                logger.warning(f"pydub conversion failed: {pydub_error}")
                
                # Fallback to ffmpeg if available
                if AudioProcessor.check_ffmpeg():
                    subprocess.run([
                        'ffmpeg', '-i', input_path, 
                        '-acodec', 'pcm_s16le', 
                        '-ar', '16000', 
                        output_path, '-y'
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logger.info(f"Converted {input_path} to WAV using ffmpeg")
                    return True
                else:
                    raise Exception("Neither pydub nor ffmpeg could convert the file")
                    
        except Exception as e:
            logger.error(f"Audio conversion failed: {str(e)}")
            return False
    
    @staticmethod
    def cleanup_file(file_path):
        """Safely delete audio file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup file {file_path}: {str(e)}")
    
    @staticmethod
    def ensure_upload_directory():
        """Ensure upload directory exists"""
        upload_dir = 'uploads'
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
        return upload_dir
