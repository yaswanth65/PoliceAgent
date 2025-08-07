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
    genai.configure(api_key=Config.GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8
    db_manager = DatabaseManager()
    executor = ThreadPoolExecutor(max_workers=4)
    logger.info("All services initialized successfully")
except Exception as e:
    logger.error(f"Service initialization failed: {e}")
    exit(1)

# Global storage for active sessions
active_sessions = {}

def cleanup_expired_sessions():
    current_time = datetime.now()
    expired_sessions = [
        session_id for session_id, data in active_sessions.items()
        if current_time - data['created_at'] > timedelta(seconds=Config.SESSION_TIMEOUT)
    ]
    for session_id in expired_sessions:
        del active_sessions[session_id]
        logger.info(f"Cleaned up expired session: {session_id}")

def is_police_related_query(text):
    police_keywords = [
        'police', 'emergency', 'crime', 'report', 'accident', 'theft', 'robbery',
        'assault', 'help', 'officer', 'complaint', 'incident', 'security',
        'stolen', 'missing', 'violence', 'harassment', 'disturbance', 'break',
        'fraud', 'vandalism', 'drugs', 'traffic', 'violation', 'law', 'legal'
    ]
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in police_keywords)

def fast_transcribe_audio(audio_file_path):
    try:
        with sr.AudioFile(audio_file_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source)
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
    """
    Generate context-aware multi-turn 911/Police conversation with detail collection.
    """
    # Remove any hardcoded shallow responses; everything is context-driven
    prompt = f"""
You are a highly professional 911 police dispatcher (emergency operator).
Conduct this as a real emergency or police call.
- For every report, you COLLECT ALL NEEDED DETAILS step-by-step: 
   - What happened?
   - When did it happen?
   - Where (location/address)?
   - Who was involved? Is anything missing/stolen? Description of people involved? Any threat?
   - Are there any injuries, witnesses, or video?
   - Any additional info?
- Keep the conversation natural, polite, and helpful. Always reference previous replies if relevant.
- For each new user message, if more details are needed, ASK natural FOLLOW-UP QUESTIONS until you have all needed info.
- When you believe you’ve collected all necessary incident details, say: 
  "Thank you for all the information. Would you like to end this call and save a summary of your report to the police department?"
- You NEVER tell the caller to 'call 911' (you ARE 911). Treat the user as a real caller on the line.
- DO NOT close the conversation or ask user to save until you have at least what, when, where, and any unique details.
- Maintain context, and recall what the CALLER ALREADY SAID.
- Use role-play format, step-by-step, as an actual dispatcher would.

Conversation so far:
{conversation_context}

Caller: "{text}"

911 Dispatcher:
"""
    try:
        response = gemini_model.generate_content(prompt)
        reply = response.text.strip()
        # Ensure reasonable length
        if len(reply) > 600:
            reply = reply[:600] + "..."
        return reply
    except Exception as e:
        logger.error(f"AI response generation failed: {e}")
        return "Sorry, there was a technical issue handling your request. Could you try again or provide more details?"

@app.after_request
def after_request(response):
    response.headers['Permissions-Policy'] = 'microphone=(self)'
    response.headers['Feature-Policy'] = 'microphone *'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_session', methods=['POST'])
@rate_limiter.rate_limit(per_minute=10, per_hour=100)
def start_session():
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
    audio_file = None
    wav_file = None
    try:
        session_id = request.form.get('session_id')
        if not session_id or session_id not in active_sessions:
            return jsonify({"error": "Invalid or expired session"}), 400
        active_sessions[session_id]['last_activity'] = datetime.now()
        audio_file = request.files.get('audio')
        if not audio_file:
            return jsonify({"error": "No audio file provided"}), 400
        is_valid, error_message = AudioProcessor.validate_audio_file(audio_file)
        if not is_valid:
            return jsonify({"error": error_message}), 400
        upload_dir = AudioProcessor.ensure_upload_directory()
        original_filename = f"{session_id}_{uuid.uuid4()}.{audio_file.filename.rsplit('.', 1)[-1]}"
        original_path = os.path.join(upload_dir, original_filename)
        audio_file.save(original_path)
        wav_filename = f"{session_id}_{uuid.uuid4()}.wav"
        wav_path = os.path.join(upload_dir, wav_filename)
        if not AudioProcessor.convert_to_wav(original_path, wav_path):
            return jsonify({"error": "Audio conversion failed"}), 500
        text = fast_transcribe_audio(wav_path)
        if not text:
            return jsonify({"error": "No speech detected in audio"}), 400
        logger.info(f"Fast transcribed text: {text[:100]}...")

        # Accept all as police-related for simulation (optional: keep the fast check)
        #if not is_police_related_query(text):
        #    reply = "I can only assist with police-related matters and emergencies. How can I help you with a police-related inquiry?"
        #else:

        # Use last 8 turns for a much better memory
        conversation_context = "\n".join([
            f"Caller: {msg['transcript']}\nOfficer: {msg['response']}"
            for msg in active_sessions[session_id]['messages'][-8:]
        ])
        message_count = len(active_sessions[session_id]['messages'])
        reply = generate_ai_response(text, conversation_context, message_count)

        message_data = {
            'timestamp': datetime.now().isoformat(),
            'transcript': text,
            'response': reply,
            'audio_file': original_filename
        }
        active_sessions[session_id]['messages'].append(message_data)
        response_data = {
            "transcript": text,
            "response": reply,
            "session_id": session_id,
            "message_count": len(active_sessions[session_id]['messages']),
            "has_audio": False,
            "processing_time": "fast"
        }
        logger.info(f"Fast processed audio for session {session_id}: {len(text)} chars transcribed")
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"Audio processing error: {str(e)}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500
    finally:
        for file_path in [original_path if 'original_path' in locals() else None,
                          wav_path if 'wav_path' in locals() else None]:
            if file_path and os.path.exists(file_path):
                AudioProcessor.cleanup_file(file_path)

@app.route('/end_session', methods=['POST'])
def end_session():
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
        # Use more of the conversation for a richer summary
        full_conversation = "\n".join([
            f"Caller: {msg['transcript']}\nOfficer: {msg['response']}"
            for msg in messages[-8:]
        ])
        try:
            summary_prompt = f"Summarize this full police call for the official record. Include what, when, where, who, and key details, under 100 words:\n{full_conversation}\n\nSummary:"
            summary_response = gemini_model.generate_content(summary_prompt)
            summary = summary_response.text.strip()
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            summary = f"Police conversation with {len(messages)} exchanges. Main topics discussed with caller {caller_name}."
        record_id = db_manager.save_call_summary(
            caller_name=caller_name,
            caller_email=caller_email,
            summary=summary,
            session_id=session_id,
            conversation_data=messages
        )
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
    try:
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
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    app.run(debug=False, host='0.0.0.0', port=5000)
