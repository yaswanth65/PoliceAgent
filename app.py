from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import assemblyai as aai
from elevenlabs import play

import google.generativeai as genai
from elevenlabs.client import ElevenLabs

import os
import uuid
import logging
from datetime import datetime, timedelta
import json

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

# Configure CORS properly for production
CORS(app, 
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     origins=["http://localhost:3000", "http://127.0.0.1:5000"])

# Initialize services
try:
    # AssemblyAI
    aai.settings.api_key = Config.ASSEMBLYAI_API_KEY
    
    # Gemini AI
    genai.configure(api_key=Config.GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    
    # ElevenLabs
    elevenlabs_client = ElevenLabs(api_key=Config.ELEVENLABS_API_KEY)
    
    # Database
    db_manager = DatabaseManager()
    
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
    """Check if query is police-related using Gemini"""
    try:
        check_prompt = f"""
        Is this question related to police work, law enforcement, emergencies, public safety, or filing reports?
        
        Question: "{text}"
        
        Consider these as police-related:
        - Crime reporting
        - Emergency situations  
        - Legal inquiries
        - Traffic violations
        - Community safety
        - Police procedures
        - Filing complaints
        - Security concerns
        
        Answer only "YES" or "NO".
        """
        
        response = gemini_model.generate_content(check_prompt)
        result = response.text.strip().upper() == "YES"
        logger.debug(f"Police query check for '{text[:50]}...': {result}")
        return result
        
    except Exception as e:
        logger.error(f"Police query check failed: {e}")
        # Default to allowing the query if check fails
        return True

@app.after_request
def after_request(response):
    """Add security headers"""
    # Enable microphone access
    response.headers['Permissions-Policy'] = 'microphone=(self)'
    response.headers['Feature-Policy'] = 'microphone *'
    
    # Security headers
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
    """Process uploaded audio and return AI response"""
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
        
        # Convert to WAV if needed
        wav_filename = f"{session_id}_{uuid.uuid4()}.wav"
        wav_path = os.path.join(upload_dir, wav_filename)
        
        if not AudioProcessor.convert_to_wav(original_path, wav_path):
            return jsonify({"error": "Audio conversion failed"}), 500
        
        # Transcribe audio
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(wav_path)
        
        if transcript.status == aai.TranscriptStatus.error:
            return jsonify({"error": f"Transcription failed: {transcript.error}"}), 500
        
        text = transcript.text.strip()
        if not text:
            return jsonify({"error": "No speech detected in audio"}), 400
        
        logger.info(f"Transcribed text: {text[:100]}...")
        
        # Check if query is police-related
        if not is_police_related_query(text):
            reply = "Sorry, that's outside my scope. I'm a Police Bot and can only help with police-related inquiries, emergencies, and public safety matters."
        else:
            # Generate AI response for police queries
            conversation_context = "\n".join([
                f"User: {msg['transcript']}\nBot: {msg['response']}"
                for msg in active_sessions[session_id]['messages'][-5:]  # Last 5 messages for context
            ])
            
            prompt = f"""You are a professional police receptionist AI assistant. 
            
            Previous conversation:
            {conversation_context}
            
            Current user query: "{text}"
            
            Provide a helpful, professional response for police-related inquiries. Keep responses concise, clear, and under 150 words. 
            If this is about filing a report, ask for necessary details. If it's an emergency, direct them to call 911 immediately.
            """
            
            try:
                response = gemini_model.generate_content(prompt)
                reply = response.text.strip()
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                reply = "I apologize, but I'm experiencing technical difficulties. Please try again or contact us directly for urgent matters."
        
        # Generate speech
        try:
            speech = elevenlabs_client.generate(
                text=reply,
                voice=Config.VOICE_ID,
                model="eleven_monolingual_v1"
            )
            
            # Save audio response
            audio_response_path = os.path.join(upload_dir, f"response_{session_id}_{uuid.uuid4()}.mp3")
            with open(audio_response_path, 'wb') as f:
                for chunk in speech:
                    f.write(chunk)
            
        except Exception as e:
            logger.error(f"Speech generation failed: {e}")
            audio_response_path = None
        
        # Store conversation
        message_data = {
            'timestamp': datetime.now().isoformat(),
            'transcript': text,
            'response': reply,
            'audio_file': original_filename,
            'response_audio': audio_response_path
        }
        
        active_sessions[session_id]['messages'].append(message_data)
        
        # Prepare response
        response_data = {
            "transcript": text,
            "response": reply,
            "session_id": session_id,
            "message_count": len(active_sessions[session_id]['messages'])
        }
        
        if audio_response_path and os.path.exists(audio_response_path):
            with open(audio_response_path, 'rb') as f:
                audio_data = f.read()
            response_data["audio_response"] = audio_data.hex()  # Convert to hex for JSON
        
        logger.info(f"Processed audio for session {session_id}: {len(text)} chars transcribed")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Audio processing error: {str(e)}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500
    
    finally:
        # Cleanup temporary files
        for file_path in [audio_file, wav_file]:
            if file_path and hasattr(file_path, 'name'):
                AudioProcessor.cleanup_file(file_path.name)

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
        
        # Create conversation summary
        full_conversation = "\n".join([
            f"User: {msg['transcript']}\nBot: {msg['response']}" 
            for msg in messages
        ])
        
        summary_prompt = f"""
        Summarize this police receptionist conversation professionally:
        
        {full_conversation}
        
        Provide a concise summary including:
        - Main inquiry/issue discussed
        - Key details and information provided  
        - Any follow-up actions needed
        - Overall outcome/resolution
        
        Keep it under 200 words and format it professionally.
        """
        
        try:
            summary_response = gemini_model.generate_content(summary_prompt)
            summary = summary_response.text.strip()
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            summary = f"Conversation with {len(messages)} exchanges. Unable to generate detailed summary due to technical issues."
        
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
                "assemblyai": "configured",
                "gemini": "configured", 
                "elevenlabs": "configured"
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
