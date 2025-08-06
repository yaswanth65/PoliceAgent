from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import speech_recognition as sr
import google.generativeai as genai
import os
import uuid
import logging
from datetime import datetime, timedelta
import json
import base64
import threading
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
import asyncio

# Import our modules
from config import Config
from database import DatabaseManager
from rate_limiter import rate_limiter
from audio_processor import AudioProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Validate configuration
try:
    Config.validate_config()
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    exit(1)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# Configure CORS
CORS(app,
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     origins=["http://localhost:3000", "http://127.0.0.1:5000"])

# Initialize services
try:
    # Gemini AI (keep this for quality responses)
    genai.configure(api_key=Config.GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    
    # Speech Recognition (faster local processing)
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8
    
    # Database
    db_manager = DatabaseManager()
    
    # Thread pool for parallel processing
    executor = ThreadPoolExecutor(max_workers=4)
    
    logger.info("All services initialized successfully")
    
except Exception as e:
    logger.error(f"Service initialization failed: {e}")
    exit(1)

# Global storage for active sessions
active_sessions = {}

def cleanup_expired_sessions():
    """Remove expired sessions from memory"""
    current_time = datetime.now()
    expired_sessions = [
        session_id for session_id, data in active_sessions.items()
        if current_time - data['created_at'] > timedelta(seconds=Config.SESSION_TIMEOUT)
    ]
    
    for session_id in expired_sessions:
        del active_sessions[session_id]
        logger.info(f"Cleaned up expired session: {session_id}")

def is_police_related_query(text):
    """Fast police-related query check using keywords"""
    police_keywords = [
        'police', 'emergency', 'crime', 'report', 'accident', 'theft', 'robbery',
        'assault', 'help', 'officer', 'complaint', 'incident', 'security',
        'stolen', 'missing', 'violence', 'harassment', 'disturbance', 'break',
        'fraud', 'vandalism', 'drugs', 'traffic', 'violation', 'law', 'legal'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in police_keywords)

def fast_transcribe_audio(audio_file_path):
    """Fast local speech recognition using Google Speech Recognition"""
    try:
        with sr.AudioFile(audio_file_path) as source:
            # Adjust for ambient noise quickly
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source)
        
        # Use Google Speech Recognition (faster than AssemblyAI)
        text = recognizer.recognize_google(audio)
        logger.info(f"Fast transcription completed: {text[:100]}...")
        return text
        
    except sr.UnknownValueError:
        logger.warning("Could not understand audio")
        return None
    except sr.RequestError as e:
        logger.error(f"Speech recognition error: {e}")
        return None
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None

def generate_ai_response(text, conversation_context, message_count):
    """Generate AI response with caching for common queries"""
    
    # Cache common responses
    common_responses = {
        "hello": "Hello, this is the Metro Police Department. How may I assist you today?",
        "hi": "Hello, this is the Metro Police Department. How may I assist you today?",
        "help": "I'm here to help you with police-related matters. What do you need assistance with?",
        "emergency": "If this is an emergency, please hang up and dial 911 immediately. For non-emergency matters, I can help you here.",
    }
    
    # Check for common queries first
    text_lower = text.lower().strip()
    for key, response in common_responses.items():
        if key in text_lower:
            return response
    
    # Generate AI response for complex queries
    try:
        greeting = "Hello, this is the Metro Police Department. How may I assist you today?" if message_count == 0 else ""
        
        prompt = f"""You are a professional police receptionist. Be concise and helpful.

{greeting}

Previous conversation:
{conversation_context}

Caller just said: "{text}"

Respond in under 50 words with helpful, professional guidance. If emergency, direct to 911.

Response:"""

        response = gemini_model.generate_content(prompt)
        reply = response.text.strip()
        
        # Clean up formatting
        reply = reply.replace("**", "").replace("*", "")
        
        # Ensure reasonable length
        if len(reply) > 300:
            reply = reply[:300] + "..."
            
        return reply
        
    except Exception as e:
        logger.error(f"AI response generation failed: {e}")
        return "I apologize for the technical difficulty. How can I assist you with your police-related inquiry?"

@app.after_request
def after_request(response):
    """Add security headers"""
    response.headers['Permissions-Policy'] = 'microphone=(self)'
    response.headers['Feature-Policy'] = 'microphone *'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

@app.route('/')
def index():
    """Serve main application page"""
    return render_template('index.html')

@app.route('/start_session', methods=['POST'])
@rate_limiter.rate_limit(per_minute=10, per_hour=100)
def start_session():
    """Start a new conversation session"""
    try:
        cleanup_expired_sessions()
        session_id = str(uuid.uuid4())
        active_sessions[session_id] = {
            'messages': [],
            'created_at': datetime.now(),
            'last_activity': datetime.now(),
            'caller_info': {}
        }
        
        logger.info(f"Started new session: {session_id}")
        return jsonify({
            "session_id": session_id,
            "status": "session_started",
            "expires_in": Config.SESSION_TIMEOUT
        })
        
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        return jsonify({"error": "Failed to start session"}), 500

@app.route('/process_audio', methods=['POST'])
@rate_limiter.rate_limit(per_minute=Config.RATE_LIMIT_PER_MINUTE, per_hour=Config.RATE_LIMIT_PER_HOUR)
def process_audio():
    """Process uploaded audio with optimized speed"""
    audio_file = None
    wav_file = None
    
    try:
        # Get session ID
        session_id = request.form.get('session_id')
        if not session_id or session_id not in active_sessions:
            return jsonify({"error": "Invalid or expired session"}), 400
            
        # Update session activity
        active_sessions[session_id]['last_activity'] = datetime.now()
        
        # Get and validate audio file
        audio_file = request.files.get('audio')
        if not audio_file:
            return jsonify({"error": "No audio file provided"}), 400
            
        # Validate audio file
        is_valid, error_message = AudioProcessor.validate_audio_file(audio_file)
        if not is_valid:
            return jsonify({"error": error_message}), 400
            
        # Save uploaded file
        upload_dir = AudioProcessor.ensure_upload_directory()
        original_filename = f"{session_id}_{uuid.uuid4()}.{audio_file.filename.rsplit('.', 1)[-1]}"
        original_path = os.path.join(upload_dir, original_filename)
        audio_file.save(original_path)
        
        # Convert to WAV quickly
        wav_filename = f"{session_id}_{uuid.uuid4()}.wav"
        wav_path = os.path.join(upload_dir, wav_filename)
        if not AudioProcessor.convert_to_wav(original_path, wav_path):
            return jsonify({"error": "Audio conversion failed"}), 500
            
        # Fast transcription using local speech recognition
        text = fast_transcribe_audio(wav_path)
        
        if not text:
            return jsonify({"error": "No speech detected in audio"}), 400
            
        logger.info(f"Fast transcribed text: {text[:100]}...")
        
        # Quick police-related check
        if not is_police_related_query(text):
            reply = "I can only assist with police-related matters and emergencies. How can I help you with a police-related inquiry?"
        else:
            # Generate AI response
            conversation_context = "\n".join([
                f"Caller: {msg['transcript']}\nOfficer: {msg['response']}"
                for msg in active_sessions[session_id]['messages'][-2:]  # Only last 2 for speed
            ])
            
            message_count = len(active_sessions[session_id]['messages'])
            reply = generate_ai_response(text, conversation_context, message_count)
        
        # Store conversation
        message_data = {
            'timestamp': datetime.now().isoformat(),
            'transcript': text,
            'response': reply,
            'audio_file': original_filename
        }
        
        active_sessions[session_id]['messages'].append(message_data)
        
        # Prepare response (no audio generation for speed)
        response_data = {
            "transcript": text,
            "response": reply,
            "session_id": session_id,
            "message_count": len(active_sessions[session_id]['messages']),
            "has_audio": False,  # Disable audio for speed
            "processing_time": "fast"
        }
        
        logger.info(f"Fast processed audio for session {session_id}: {len(text)} chars transcribed")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Audio processing error: {str(e)}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500
        
    finally:
        # Cleanup temporary files
        for file_path in [original_path if 'original_path' in locals() else None,
                         wav_path if 'wav_path' in locals() else None]:
            if file_path and os.path.exists(file_path):
                AudioProcessor.cleanup_file(file_path)

@app.route('/end_session', methods=['POST'])
def end_session():
    """End session and save summary to database"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        caller_name = data.get('caller_name', 'Anonymous')
        caller_email = data.get('caller_email', '')
        
        if not session_id or session_id not in active_sessions:
            return jsonify({"error": "Session not found"}), 404
            
        session_data = active_sessions[session_id]
        messages = session_data['messages']
        
        if not messages:
            return jsonify({"error": "No conversation to summarize"}), 400
            
        # Quick summary generation
        full_conversation = "\n".join([
            f"Caller: {msg['transcript']}\nOfficer: {msg['response']}"
            for msg in messages[-5:]  # Only last 5 messages for speed
        ])
        
        try:
            summary_prompt = f"Summarize this police call briefly:\n{full_conversation}\n\nSummary (under 100 words):"
            summary_response = gemini_model.generate_content(summary_prompt)
            summary = summary_response.text.strip()
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            summary = f"Police conversation with {len(messages)} exchanges. Main topics discussed with caller {caller_name}."
            
        # Save to database
        record_id = db_manager.save_call_summary(
            caller_name=caller_name,
            caller_email=caller_email,
            summary=summary,
            session_id=session_id,
            conversation_data=messages
        )
        
        # Clean up session
        del active_sessions[session_id]
        
        logger.info(f"Session {session_id} ended and saved with record ID: {record_id}")
        
        return jsonify({
            "summary": summary,
            "record_id": record_id,
            "status": "session_ended_and_saved",
            "message_count": len(messages)
        })
        
    except Exception as e:
        logger.error(f"End session error: {str(e)}")
        return jsonify({"error": f"Failed to end session: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db_manager.client.server_info()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "active_sessions": len(active_sessions),
            "services": {
                "database": "connected",
                "speech_recognition": "ready",
                "gemini": "configured"
            }
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    # Run the application
    app.run(debug=False, host='0.0.0.0', port=5000)
