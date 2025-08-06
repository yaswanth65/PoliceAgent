import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration optimized for speed"""
    
    # API Keys (reduced dependencies)
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    
    # Database
    MONGODB_URL = os.getenv('MONGODB_URL')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'aiAgentcaller')
    
    # Rate Limiting (more generous for faster testing)
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', 10))
    RATE_LIMIT_PER_HOUR = int(os.getenv('RATE_LIMIT_PER_HOUR', 100))
    
    # Audio Settings (optimized for speed)
    MAX_AUDIO_FILE_SIZE = int(os.getenv('MAX_AUDIO_FILE_SIZE', 5242880))  # 5MB (smaller for speed)
    SUPPORTED_AUDIO_FORMATS = ['wav', 'mp3', 'ogg', 'webm', 'm4a']
    
    # Session Settings
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 1800))  # 30 minutes
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
    
    @classmethod
    def validate_config(cls):
        """Validate required configuration"""
        required_vars = [
            'GEMINI_API_KEY',
            'MONGODB_URL'
        ]
        
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True
