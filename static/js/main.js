class PoliceAIReceptionist {
    constructor() {
        this.sessionId = null;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.recordingStartTime = null;
        this.recordingTimer = null;
        this.audioContext = null;
        this.isPlaying = false;  // Added audio state tracking
        this.currentAudio = null;  // Track current audio
        this.initializeElements();
        this.initializeAudioContext();
        this.initializeSession();
        this.requestMicrophonePermission();
    }

    initializeElements() {
        this.recordBtn = document.getElementById('recordBtn');
        this.recordIcon = document.getElementById('recordIcon');
        this.recordText = document.getElementById('recordText');
        this.recordingTime = document.getElementById('recordingTime');
        this.status = document.getElementById('status');
        this.conversation = document.getElementById('conversation');
        this.callerInfo = document.getElementById('callerInfo');
        this.callerName = document.getElementById('callerName');
        this.callerEmail = document.getElementById('callerEmail');
        this.endCallBtn = document.getElementById('endCallBtn');
        this.loading = document.getElementById('loading');

        // Event listeners
        this.recordBtn.addEventListener('click', () => this.toggleRecording());
        this.endCallBtn.addEventListener('click', () => this.endSession());
    }

    async initializeAudioContext() {
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            console.log('Audio context initialized');
        } catch (error) {
            console.warn('Could not initialize audio context:', error);
        }
    }

    async requestMicrophonePermission() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 44100
                }
            });
            this.updateStatus('🎤 Ready to take your call - Click to speak', 'success');
            this.recordBtn.disabled = false;

            // Stop the stream for now
            stream.getTracks().forEach(track => track.stop());
        } catch (error) {
            console.error('Microphone permission denied:', error);
            this.updateStatus('❌ Microphone access denied. Please enable microphone permissions.', 'error');
        }
    }

    async initializeSession() {
        try {
            const response = await fetch('/start_session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.sessionId = data.session_id;
                console.log('Session started:', this.sessionId);
            } else {
                throw new Error('Failed to start session');
            }
        } catch (error) {
            console.error('Session initialization failed:', error);
            this.updateStatus('❌ Failed to connect. Please refresh the page.', 'error');
        }
    }

    async toggleRecording() {
        if (this.isRecording) {
            this.stopRecording();
        } else {
            await this.startRecording();
        }
    }

    async startRecording() {
        // Don't allow recording while audio is playing
        if (this.isPlaying) {
            this.updateStatus('⏳ Please wait for the officer to finish speaking...', 'warning');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 44100
                }
            });

            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            this.audioChunks = [];
            this.isRecording = true;
            this.recordingStartTime = Date.now();

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = () => {
                this.processRecording();
            };

            this.mediaRecorder.start();
            this.updateRecordingUI(true);
            this.startRecordingTimer();
            this.updateStatus('🔴 Recording... Please speak clearly', 'recording');

        } catch (error) {
            console.error('Failed to start recording:', error);
            this.updateStatus('❌ Failed to start recording. Please check microphone permissions.', 'error');
        }
    }

    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            this.mediaRecorder.stop();
            this.isRecording = false;

            // Stop all tracks
            if (this.mediaRecorder.stream) {
                this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
            }

            this.updateRecordingUI(false);
            this.stopRecordingTimer();
            this.updateStatus('🔄 Processing your request...', 'processing');
        }
    }

    updateRecordingUI(recording) {
        if (recording) {
            this.recordBtn.classList.add('recording');
            this.recordIcon.textContent = '⏹️';
            this.recordText.textContent = 'Stop Recording';
            this.recordBtn.style.backgroundColor = '#dc3545';
        } else {
            this.recordBtn.classList.remove('recording');
            this.recordIcon.textContent = '🎤';
            this.recordText.textContent = 'Start Recording';
            this.recordBtn.style.backgroundColor = '#007bff';
        }
    }

    startRecordingTimer() {
        this.recordingTimer = setInterval(() => {
            const elapsed = Date.now() - this.recordingStartTime;
            const minutes = Math.floor(elapsed / 60000);
            const seconds = Math.floor((elapsed % 60000) / 1000);
            this.recordingTime.textContent =
                `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }, 1000);
    }

    stopRecordingTimer() {
        if (this.recordingTimer) {
            clearInterval(this.recordingTimer);
            this.recordingTimer = null;
        }
        this.recordingTime.textContent = '00:00';
    }

    async processRecording() {
        if (this.audioChunks.length === 0) {
            this.updateStatus('❌ No audio recorded. Please try again.', 'error');
            return;
        }

        this.showLoading(true);
        try {
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
            const formData = new FormData();
            formData.append('audio', audioBlob, 'recording.webm');
            formData.append('session_id', this.sessionId);

            const response = await fetch('/process_audio', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            console.log('API Response:', data); // Debug log

            if (response.ok) {
                this.displayConversation(data.transcript, data.response);

                // Play audio response if available - FIXED AUDIO PLAYBACK
                if (data.has_audio && data.audio_response) {
                    console.log('Audio response received, attempting to play...');
                    await this.playAudioResponse(data.audio_response);
                } else {
                    console.log('No audio response available');
                    this.updateStatus('✅ Ready for your next question', 'success');
                }

                // Show caller info after first interaction
                if (data.message_count === 1) {
                    this.callerInfo.style.display = 'block';
                }
            } else {
                throw new Error(data.error || 'Processing failed');
            }

        } catch (error) {
            console.error('Processing error:', error);
            this.updateStatus(`❌ Error: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    displayConversation(transcript, response) {
        // Add user message
        const userMessage = document.createElement('div');
        userMessage.className = 'message user-message';
        userMessage.innerHTML = `<strong>🗣️ You:</strong> ${transcript}`;
        this.conversation.appendChild(userMessage);

        // Add bot response
        const botMessage = document.createElement('div');
        botMessage.className = 'message bot-message';
        botMessage.innerHTML = `<strong>👮 Officer:</strong> ${response}`;
        this.conversation.appendChild(botMessage);

        // Scroll to bottom
        this.conversation.scrollTop = this.conversation.scrollHeight;

        // Speak the bot's response using SpeechSynthesis API
        if (response && typeof response === 'string') {
            const utterance = new SpeechSynthesisUtterance(response);
            speechSynthesis.speak(utterance);
        }

        // Add download link for bot audio if available
        if (this.lastApiData && this.lastApiData.bot_audio_file) {
            const audioLink = document.createElement('a');
            audioLink.href = this.lastApiData.bot_audio_file;
            audioLink.download = '';
            audioLink.textContent = '⬇️ Download Officer Audio';
            audioLink.className = 'bot-audio-download-link';
            botMessage.appendChild(document.createElement('br'));
            botMessage.appendChild(audioLink);
        }
    }

    // COMPLETELY REWRITTEN AUDIO PLAYBACK FUNCTION
    async playAudioResponse(audioBase64) {
        try {
            this.isPlaying = true;
            this.updateStatus('🔊 Officer is speaking...', 'playing');
            console.log('Starting audio playback...');

            // Disable recording while playing
            this.recordBtn.disabled = true;

            // Stop any currently playing audio
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio = null;
            }

            // Convert base64 to array buffer
            const binaryString = atob(audioBase64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }

            console.log(`Audio data converted: ${bytes.length} bytes`);

            // Create audio blob with proper MIME type
            const audioBlob = new Blob([bytes], { type: 'audio/mpeg' });
            const audioUrl = URL.createObjectURL(audioBlob);

            // Create and configure audio element
            this.currentAudio = new Audio(audioUrl);
            this.currentAudio.volume = 0.9;
            this.currentAudio.preload = 'auto';

            // Set up event handlers
            this.currentAudio.onloadstart = () => {
                console.log('Audio loading started');
            };

            this.currentAudio.oncanplay = () => {
                console.log('Audio can start playing');
            };

            this.currentAudio.onplay = () => {
                console.log('Audio playback started successfully');
            };

            this.currentAudio.onended = () => {
                console.log('Audio playback finished');
                this.isPlaying = false;
                this.recordBtn.disabled = false;
                this.updateStatus('✅ Ready for your next question', 'success');
                URL.revokeObjectURL(audioUrl);
                this.currentAudio = null;
            };

            this.currentAudio.onerror = (error) => {
                console.error('Audio playback error:', error);
                console.error('Audio element error details:', this.currentAudio.error);
                this.isPlaying = false;
                this.recordBtn.disabled = false;
                this.updateStatus('⚠️ Audio playback failed, but message received', 'warning');
                URL.revokeObjectURL(audioUrl);
                this.currentAudio = null;
            };

            this.currentAudio.onpause = () => {
                console.log('Audio playback paused');
            };

            // Ensure audio context is resumed (required for some browsers)
            if (this.audioContext && this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }

            // Start playback
            console.log('Attempting to play audio...');
            await this.currentAudio.play();

        } catch (error) {
            console.error('Audio playback failed:', error);
            console.error('Error details:', error.message);
            this.isPlaying = false;
            this.recordBtn.disabled = false;
            this.updateStatus('⚠️ Could not play audio response', 'warning');

            // Clean up on error
            if (this.currentAudio) {
                const url = this.currentAudio.src;
                this.currentAudio = null;
                if (url.startsWith('blob:')) {
                    URL.revokeObjectURL(url);
                }
            }
        }
    }

    async endSession() {
        const callerName = this.callerName.value.trim();
        if (!callerName) {
            alert('Please enter your name before ending the session.');
            return;
        }

        // Stop any playing audio
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }

        this.showLoading(true);
        try {
            const response = await fetch('/end_session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    caller_name: callerName,
                    caller_email: this.callerEmail.value.trim()
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.displaySessionSummary(data.summary);
                this.updateStatus('✅ Session ended. Thank you for calling Metro Police Department.', 'success');
                this.recordBtn.disabled = true;
                this.callerInfo.style.display = 'none';
            } else {
                throw new Error(data.error || 'Failed to end session');
            }

        } catch (error) {
            console.error('End session error:', error);
            this.updateStatus(`❌ Error ending session: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    displaySessionSummary(summary) {
        const summaryMessage = document.createElement('div');
        summaryMessage.className = 'message bot-message summary';
        summaryMessage.innerHTML = `
            <strong>📋 Call Summary:</strong><br>
            <div class="summary-content">${summary}</div>
            <em>This summary has been saved to our records. Thank you for calling!</em>
        `;
        this.conversation.appendChild(summaryMessage);
        this.conversation.scrollTop = this.conversation.scrollHeight;
    }

    updateStatus(message, type = '') {
        this.status.textContent = message;
        this.status.className = `status ${type}`;
        console.log(`Status: ${message} (${type})`); // Debug log
    }

    showLoading(show) {
        this.loading.style.display = show ? 'flex' : 'none';
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing Police AI Receptionist...');
    new PoliceAIReceptionist();
});
