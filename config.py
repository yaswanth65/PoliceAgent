import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""
    
    # API Keys
    ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
    
    # Database
    MONGODB_URL = os.getenv('MONGODB_URL')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'aiAgentcaller')
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', 5))
    RATE_LIMIT_PER_HOUR = int(os.getenv('RATE_LIMIT_PER_HOUR', 50))
    
    # Audio Settings
    MAX_AUDIO_FILE_SIZE = int(os.getenv('MAX_AUDIO_FILE_SIZE', 10485760))  # 10MB
    SUPPORTED_AUDIO_FORMATS = ['wav', 'mp3', 'ogg', 'webm', 'm4a']
    
    # Session Settings
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 1800))  # 30 minutes
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-this')
    
    # ElevenLabs Settings
    VOICE_ID = os.getenv('ELEVENLABS_VOICE_ID', 'pNInz6obpgDQGcFmaJgB')  # Adam voice
    
    @classmethod
    def validate_config(cls):
        """Validate required configuration"""
        required_vars = [
            'ASSEMBLYAI_API_KEY', 
            'GEMINI_API_KEY', 
            'ELEVENLABS_API_KEY', 
            'MONGODB_URL'
        ]
        
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True
