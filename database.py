from pymongo import MongoClient
from datetime import datetime
import logging
from config import Config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all MongoDB operations"""
    
    def __init__(self):
        try:
            self.client = MongoClient(Config.MONGODB_URL, serverSelectionTimeoutMS=5000)
            self.db = self.client[Config.DATABASE_NAME]
            self.calls_collection = self.db.calls
            self.sessions_collection = self.db.sessions
            
            # Test connection
            self.client.server_info()
            logger.info("Successfully connected to MongoDB")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise
    
    def save_call_summary(self, caller_name, caller_email, summary, session_id, conversation_data=None):
        """Save completed call summary to database"""
        try:
            call_record = {
                "caller_name": caller_name,
                "caller_email": caller_email,
                "summary": summary,
                "session_id": session_id,
                "conversation_data": conversation_data or [],
                "timestamp": datetime.now(),
                "created_at": datetime.now(),
                "status": "completed"
            }
            
            result = self.calls_collection.insert_one(call_record)
            logger.info(f"Saved call summary with ID: {result.inserted_id}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Failed to save call summary: {str(e)}")
            raise
    
    def save_session(self, session_id, session_data):
        """Save or update session data"""
        try:
            session_record = {
                "session_id": session_id,
                "data": session_data,
                "last_updated": datetime.now()
            }
            
            self.sessions_collection.update_one(
                {"session_id": session_id},
                {"$set": session_record},
                upsert=True
            )
            
        except Exception as e:
            logger.error(f"Failed to save session: {str(e)}")
            raise
    
    def get_session(self, session_id):
        """Retrieve session data"""
        try:
            session = self.sessions_collection.find_one({"session_id": session_id})
            return session['data'] if session else None
            
        except Exception as e:
            logger.error(f"Failed to retrieve session: {str(e)}")
            return None
    
    def cleanup_expired_sessions(self, timeout_minutes=30):
        """Clean up expired sessions"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)
            result = self.sessions_collection.delete_many(
                {"last_updated": {"$lt": cutoff_time}}
            )
            logger.info(f"Cleaned up {result.deleted_count} expired sessions")
            
        except Exception as e:
            logger.error(f"Failed to cleanup sessions: {str(e)}")
    
    def close_connection(self):
        """Close database connection"""
        if hasattr(self, 'client'):
            self.client.close()
