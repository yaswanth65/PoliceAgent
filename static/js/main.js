class PoliceAIReceptionist {
    constructor() {
        this.sessionId = null;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.recordingStartTime = null;
        this.recordingTimer = null;
        
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
                    sampleRate: 44100
                } 
            });
            
            this.updateStatus('Microphone ready - Click to start recording', 'success');
            this.recordBtn.disabled = false;
            
            // Stop the stream for now
            stream.getTracks().forEach(track => track.stop());
            
        } catch (error) {
            console.error('Microphone permission denied:', error);
            this.updateStatus('Microphone access denied. Please enable microphone permissions.', 'error');
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
            this.updateStatus('Failed to initialize session. Please refresh the page.', 'error');
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
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
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
            
            this.updateStatus('Recording... Speak clearly about your police-related inquiry', 'recording');
            
        } catch (error) {
            console.error('Failed to start recording:', error);
            this.updateStatus('Failed to start recording. Please check microphone permissions.', 'error');
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
            this.updateStatus('Processing your request...', 'processing');
        }
    }

    updateRecordingUI(recording) {
        if (recording) {
            this.recordBtn.classList.add('recording');
            this.recordIcon.textContent = '⏹️';
            this.recordText.textContent = 'Stop Recording';
        } else {
            this.recordBtn.classList.remove('recording');
            this.recordIcon.textContent = '🎤';
            this.recordText.textContent = 'Start Recording';
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
            this.updateStatus('No audio recorded. Please try again.', 'error');
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

            if (response.ok) {
                this.displayConversation(data.transcript, data.response);
                
                // Play audio response if available
                if (data.audio_response) {
                    this.playAudioResponse(data.audio_response);
                }
                
                this.updateStatus('Ready for your next question', 'success');
                
                // Show caller info after first interaction
                if (data.message_count === 1) {
                    this.callerInfo.style.display = 'block';
                }
                
            } else {
                throw new Error(data.error || 'Processing failed');
            }

        } catch (error) {
            console.error('Processing error:', error);
            this.updateStatus(`Error: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    displayConversation(transcript, response) {
        // Add user message
        const userMessage = document.createElement('div');
        userMessage.className = 'message user-message';
        userMessage.innerHTML = `<strong>You:</strong> ${transcript}`;
        this.conversation.appendChild(userMessage);

        // Add bot response
        const botMessage = document.createElement('div');
        botMessage.className = 'message bot-message';
        botMessage.innerHTML = `<strong>Police Bot:</strong> ${response}`;
        this.conversation.appendChild(botMessage);

        // Scroll to bottom
        this.conversation.scrollTop = this.conversation.scrollHeight;
    }

    playAudioResponse(audioHex) {
        try {
            // Convert hex string back to binary
            const bytes = new Uint8Array(audioHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
            const audioBlob = new Blob([bytes], { type: 'audio/mpeg' });
            const audioUrl = URL.createObjectURL(audioBlob);
            
            const audio = new Audio(audioUrl);
            audio.play().catch(error => {
                console.warn('Could not play audio response:', error);
            });
            
            // Clean up URL after playing
            audio.onended = () => URL.revokeObjectURL(audioUrl);
            
        } catch (error) {
            console.warn('Could not play audio response:', error);
        }
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
                this.updateStatus('Session ended successfully. Thank you for using Police AI Receptionist.', 'success');
                this.recordBtn.disabled = true;
                this.callerInfo.style.display = 'none';
            } else {
                throw new Error(data.error || 'Failed to end session');
            }

        } catch (error) {
            console.error('End session error:', error);
            this.updateStatus(`Error ending session: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    displaySessionSummary(summary) {
        const summaryMessage = document.createElement('div');
        summaryMessage.className = 'message bot-message';
        summaryMessage.innerHTML = `
            <strong>📋 Session Summary:</strong><br>
            <div style="margin-top: 10px; padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #007bff;">
                ${summary}
            </div>
            <p style="margin-top: 15px; font-size: 0.9em; color: #6c757d;">
                This summary has been saved to our records. Thank you for using our service.
            </p>
        `;
        this.conversation.appendChild(summaryMessage);
        this.conversation.scrollTop = this.conversation.scrollHeight;
    }

    updateStatus(message, type = '') {
        this.status.textContent = message;
        this.status.className = `status ${type}`;
    }

    showLoading(show) {
        this.loading.style.display = show ? 'flex' : 'none';
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new PoliceAIReceptionist();
});
