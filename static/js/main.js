class PoliceAIReceptionist {
    constructor() {
        this.sessionId = null;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.recordingStartTime = null;
        this.recordingTimer = null;
        this.isProcessing = false; // Prevent multiple simultaneous requests
        
        this.initializeElements();
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

    async requestMicrophonePermission() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 16000, // Lower sample rate for faster processing
                    channelCount: 1 // Mono for faster processing
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
        if (this.isProcessing) {
            this.updateStatus('⏳ Processing previous request...', 'warning');
            return;
        }

        if (this.isRecording) {
            this.stopRecording();
        } else {
            await this.startRecording();
        }
    }

    async startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 16000, // Optimized for speed
                    channelCount: 1
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

        this.isProcessing = true;
        this.showLoading(true);

        try {
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
            const formData = new FormData();
            formData.append('audio', audioBlob, 'recording.webm');
            formData.append('session_id', this.sessionId);

            const startTime = Date.now();
            const response = await fetch('/process_audio', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            const processingTime = Date.now() - startTime;
            
            console.log(`Processing completed in ${processingTime}ms`);

            if (response.ok) {
                this.displayConversation(data.transcript, data.response);
                
                // Use browser's built-in speech synthesis for immediate audio feedback
                this.speakResponse(data.response);
                
                this.updateStatus('✅ Ready for your next question', 'success');

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
            this.isProcessing = false;
        }
    }

    speakResponse(text) {
        // Use browser's built-in Speech Synthesis API for instant audio
        if ('speechSynthesis' in window && text) {
            // Cancel any ongoing speech
            speechSynthesis.cancel();
            
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 1.1; // Slightly faster for efficiency
            utterance.pitch = 1;
            utterance.volume = 0.8;
            
            // Try to use a professional sounding voice
            const voices = speechSynthesis.getVoices();
            const preferredVoice = voices.find(voice => 
                voice.name.includes('Google') || 
                voice.name.includes('Microsoft') ||
                voice.lang.startsWith('en')
            );
            
            if (preferredVoice) {
                utterance.voice = preferredVoice;
            }
            
            speechSynthesis.speak(utterance);
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
    }

    async endSession() {
        const callerName = this.callerName.value.trim();
        if (!callerName) {
            alert('Please enter your name before ending the session.');
            return;
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
        summaryMessage.innerHTML = `<strong>📋 Call Summary:</strong><br>${summary}`;
        this.conversation.appendChild(summaryMessage);
        this.conversation.scrollTop = this.conversation.scrollHeight;
    }

    updateStatus(message, type) {
        this.status.textContent = message;
        this.status.className = `status ${type}`;
    }

    showLoading(show) {
        this.loading.style.display = show ? 'block' : 'none';
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new PoliceAIReceptionist();
});
