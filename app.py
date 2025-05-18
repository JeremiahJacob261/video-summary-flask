# app.py
import os
import moviepy.editor as mp
import requests
import json
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

# --- Configuration ---
# It's highly recommended to set the API key as an environment variable
# For example, run: export FIREWORKS_API_KEY='your_actual_api_key'
# And then access it in Python with: os.environ.get('FIREWORKS_API_KEY')
FIREWORKS_API_KEY = os.environ.get('FIREWORKS_API_KEY', "fw_3Ziq4BByToyH77BKr7pcBH9i") # Replace with your key or use env var

# Folder to store uploaded videos and temporary audio files
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv'} # Allowed video extensions

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.urandom(24) # For flash messages
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit

# Create upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- Helper Function ---
def allowed_file(filename):
    """Checks if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- VideoSummarizer Class (adapted for Flask) ---
class VideoSummarizer:
    def __init__(self, fireworks_api_key):
        self.api_key = fireworks_api_key
        if not self.api_key or self.api_key == "YOUR_FIREWORKS_API_KEY_HERE": # Default placeholder check
            app.logger.error("Fireworks API Key is not set or is using the default placeholder.")
            # You might want to raise an exception or handle this more gracefully
            # For now, it will proceed but API calls will likely fail.
        self.transcription_url = "https://audio-prod.us-virginia-1.direct.fireworks.ai/v1/audio/transcriptions"
        # Using the user-provided summarization API endpoint
        self.summarization_api_url = "https://backend.jeremiahjacob261.workers.dev/chat"

    def extract_audio(self, video_path, audio_path="temp_audio.wav"):
        """Extract audio from video file."""
        try:
            app.logger.info(f"Extracting audio from: {video_path} to {audio_path}")
            video = mp.VideoFileClip(video_path)
            video.audio.write_audiofile(audio_path, codec='pcm_s16le') # Specify codec for .wav
            video.close()
            app.logger.info("Audio extraction successful.")
            return audio_path
        except Exception as e:
            app.logger.error(f"Error extracting audio: {str(e)}")
            raise Exception(f"Error extracting audio: {str(e)}")

    def transcribe_audio(self, audio_path):
        """Transcribe audio using Fireworks AI Whisper."""
        try:
            app.logger.info(f"Transcribing audio from: {audio_path}")
            if not self.api_key:
                raise ValueError("Fireworks API Key is not configured.")

            with open(audio_path, 'rb') as audio_file:
                files = {'file': (os.path.basename(audio_path), audio_file, 'audio/wav')}
                headers = {'Authorization': f'Bearer {self.api_key}'}
                
                response = requests.post(
                    self.transcription_url,
                    headers=headers,
                    files=files,
                    data={'model': 'whisper-v3'} # As per original script
                )
                
                app.logger.info(f"Transcription API response status: {response.status_code}")
                if response.status_code != 200:
                    app.logger.error(f"Transcription API error: {response.text}")
                response.raise_for_status() # Will raise an HTTPError for bad responses (4XX or 5XX)
                
                transcription_text = response.json().get('text', '')
                app.logger.info(f"Transcription successful. Length: {len(transcription_text)} chars.")
                return transcription_text
        except requests.exceptions.RequestException as e:
            app.logger.error(f"RequestException during transcription: {str(e)}")
            raise Exception(f"Network or API error during transcription: {str(e)}")
        except Exception as e:
            app.logger.error(f"Error in transcription: {str(e)}")
            raise Exception(f"Error in transcription: {str(e)}")

    def summarize_text(self, transcript, max_tokens=200): # max_tokens not used by this specific API
        """Generate summary using the provided API endpoint."""
        try:
            app.logger.info("Generating summary...")
            if not transcript:
                app.logger.warning("Transcript is empty, returning empty summary.")
                return ""

            payload = {"queries": [transcript]} # API expects a list of queries
            headers = {"Content-Type": "application/json"}

            response = requests.post(
                self.summarization_api_url,
                headers=headers,
                data=json.dumps(payload)
            )
            
            app.logger.info(f"Summarization API response status: {response.status_code}")
            if response.status_code != 200:
                app.logger.error(f"Summarization API error: Status {response.status_code}, Body: {response.text}")
                raise Exception(f"Summarization API request failed with status {response.status_code}: {response.text}")

            # Assuming the API returns JSON like: {"answer": "summary text"} or similar
            # Based on the original script's print(response.text) and data = response.json()
            # And the example payload, it seems the API might return a more complex structure.
            # Let's assume it returns a structure where the summary is accessible.
            # If the API returns a list of summaries for a list of queries:
            data = response.json()
            app.logger.info(f"Summarization API raw response: {data}")

            # Adjust based on actual API response structure
            # If data is a list and contains dicts with 'answer' or similar:
            if isinstance(data, list) and data:
                summary_text = data[0].get("answer", "Summary not found in response.") # Example access
            elif isinstance(data, dict):
                 summary_text = data.get("answer", data.get("summary", "Summary not found in response.")) # More general access
            else:
                summary_text = "Could not parse summary from API response."
            
            app.logger.info("Summary generation successful.")
            return summary_text

        except requests.exceptions.RequestException as e:
            app.logger.error(f"RequestException during summarization: {str(e)}")
            raise Exception(f"Network or API error during summarization: {str(e)}")
        except json.JSONDecodeError as e:
            app.logger.error(f"JSONDecodeError during summarization: {str(e)}. Response text: {response.text}")
            raise Exception(f"Error decoding summarization API response: {str(e)}")
        except Exception as err:
            app.logger.error(f"Error fetching summarization API response: {str(err)}")
            raise Exception(f"Error during text summarization: {str(err)}")

    def summarize_video(self, video_path):
        """Main function to process video and generate summary."""
        # Generate unique audio file name with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") # Added microseconds for more uniqueness
        # Ensure audio path is within the UPLOAD_FOLDER for cleanup and access
        base_video_filename = os.path.splitext(os.path.basename(video_path))[0]
        audio_filename = f"{base_video_filename}_{timestamp}.wav"
        audio_path = os.path.join(app.config['UPLOAD_FOLDER'], audio_filename)
        
        transcript = ""
        summary = ""
        
        try:
            # Extract audio
            app.logger.info("Extracting audio...")
            actual_audio_path = self.extract_audio(video_path, audio_path)
            
            # Transcribe
            app.logger.info("Transcribing audio...")
            transcript = self.transcribe_audio(actual_audio_path)
            
            # Summarize
            if transcript:
                app.logger.info("Generating summary...")
                summary = self.summarize_text(transcript)
            else:
                app.logger.warning("Skipping summarization due to empty transcript.")
                summary = "Could not generate summary because the transcript was empty."
            
            return {
                "transcript": transcript,
                "summary": summary
            }
        except Exception as e:
            app.logger.error(f"Error processing video in summarize_video: {str(e)}")
            # Re-raise to be caught by the route's error handler
            raise
        finally:
            # Clean up temporary audio file
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    app.logger.info(f"Cleaned up temporary audio file: {audio_path}")
                except OSError as e:
                    app.logger.error(f"Error deleting temporary audio file {audio_path}: {e.strerror}")
            # The uploaded video file will be cleaned up by the route if needed, or kept.
            # For this version, we'll delete it after processing.
            if os.path.exists(video_path):
                 try:
                    os.remove(video_path)
                    app.logger.info(f"Cleaned up uploaded video file: {video_path}")
                 except OSError as e:
                    app.logger.error(f"Error deleting uploaded video file {video_path}: {e.strerror}")


# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'video_file' not in request.files:
            flash('No file part in the request.', 'danger')
            return redirect(request.url)
        
        file = request.files['video_file']
        
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == '':
            flash('No selected file.', 'warning')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename) # Sanitize filename
            # Add a timestamp to filename to avoid overwrites and make it unique
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            unique_filename = f"{timestamp}_{filename}"
            video_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            
            try:
                file.save(video_path)
                app.logger.info(f"File saved to {video_path}")
                
                # Initialize summarizer (ensure API key is available)
                if not FIREWORKS_API_KEY or FIREWORKS_API_KEY == "YOUR_FIREWORKS_API_KEY_HERE":
                    flash("API Key for Fireworks AI is not configured on the server. Please contact the administrator.", "danger")
                    # Clean up the saved file if API key is missing
                    if os.path.exists(video_path):
                        os.remove(video_path)
                    return redirect(request.url)

                summarizer = VideoSummarizer(FIREWORKS_API_KEY)
                
                # Process video
                flash('Processing your video... This may take a while.', 'info')
                # Redirect to a loading/processing page or use AJAX for better UX
                # For simplicity, we process here and then show results.

                results = summarizer.summarize_video(video_path) # video_path is cleaned up inside this method
                
                return render_template('results.html', results=results, video_filename=filename)

            except Exception as e:
                app.logger.error(f"Error during video processing route: {str(e)}")
                flash(f'An error occurred: {str(e)}', 'danger')
                # Clean up the uploaded file if an error occurs during processing
                if os.path.exists(video_path) and 'results' not in locals(): # only if summarize_video didn't run or failed early
                    try:
                        os.remove(video_path)
                        app.logger.info(f"Cleaned up {video_path} due to error.")
                    except OSError as rm_err:
                        app.logger.error(f"Error cleaning up {video_path} after error: {rm_err.strerror}")
                return redirect(request.url)
            
        else:
            flash('Invalid file type. Allowed types are: mp4, mov, avi, mkv.', 'danger')
            return redirect(request.url)
            
    return render_template('index.html')

if __name__ == '__main__':
    # Set up basic logging
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # For more detailed debugging, you can set level=logging.DEBUG
    # app.run(debug=True) # debug=True is useful for development, but disable for production
    app.run(host='0.0.0.0', port=5000) # Makes it accessible on the network
