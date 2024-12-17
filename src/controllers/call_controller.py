from flask import Flask, request, jsonify, Response, Blueprint, json, redirect, current_app
import requests
import os
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Start
from celery import Celery
import time
import threading
import re
from websocket_server import WebsocketServer
import base64
import asyncio
import websockets
from flask_sockets import Sockets
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
from pydub import AudioSegment


SYSTEM_MESSAGE = (
    "You are a helpful and bubbly AI assistant who loves to chat about "
    "anything the user is interested in and is prepared to offer them facts. "
    "You have a penchant for dad jokes, owl jokes, and rickrolling – subtly. "
    "Always stay positive, but work in a joke when appropriate."
)
VOICE = 'alloy'
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False

# # Setup Celery for async tasks
# app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
# app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
# celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
# celery.conf.update(app.config)

websocket_server = None

# Twilio credentials
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak?model=aura-asteria-en"


client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

OPEN_AI_URL = 'https://api.openai.com'

call_queue = [] 
is_calling = False
current_call_sid = None
call_logs = {}
power_dialer_prompt = ""

project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(project_root, "..", ".."))

cert_path = os.path.join(backend_dir, "cert.pem")
key_path = os.path.join(backend_dir, 'key.pem')

agent = Blueprint("agent", __name__)
sockets = Sockets(current_app)


def generate_audio_with_deepgram(prompt):
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "text": prompt,
    }
    response = requests.post(DEEPGRAM_TTS_URL, headers=headers, json=data)

    if response.status_code == 200:
        # Save audio to file
        if not os.path.exists('static/build/audio'):
            os.makedirs('static/build/audio')

        audio_filename = f"{prompt[:10].replace(' ', '_')}.mp3"
        audio_path = os.path.join('static/build/audio', audio_filename)

        with open(audio_path, "wb") as audio_file:
            audio_file.write(response.content)

        return audio_filename  
    else:
        print("Error generating audio:", response.json())
        return None

# Route to make outbound call
@agent.route("/aiagent-call", methods=["POST"])
def aiagent_call():
    data = request.json
    if "phone" in data and "prompt" in data:
        to_number = "+" + str(data["phone"]["countryCode"]) + str(data["phone"]["areaCode"]) + str(data["phone"]["phoneNumber"])
        prompt = data["prompt"]
        answer = generate_prompt(prompt)

        # Generate audio with Deepgram
        audio_filename = generate_audio_with_deepgram(answer)
  
        if not audio_filename  :
            return jsonify({"status": "Call Failed", "reason": "Audio generation failed"}), 500

        # Upload audio file to public storage (example: AWS S3 or similar)
        # For demo, we'll assume the audio is accessible via a public URL
        public_audio_url = f"http://159.223.165.147:5555/build/audio/{audio_filename}"
        # public_audio_url = f"https://demo.twilio.com/docs/classic.mp3"

        print('here', public_audio_url)
        try:
            call = client.calls.create(
                # twiml=f"<Response><Say>{prompt}</Say><Say>{answer}</Say></Response>",
                twiml=f'<Response><Play>{public_audio_url}</Play></Response>',
                to=to_number,
                from_=TWILIO_PHONE_NUMBER,
                # url="http://159.223.165.147:5555/api/v1/agent/outbound-prompt"
            )            
        
            print(call.sid)
            
            return jsonify({"status": "Call initiated", "call_sid": call.sid})

        except:
            return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

    return jsonify({"status": "Call Failed", "reason": "No phone number provided"}), 400


@agent.route("/aiwelcome-call", methods=["POST"])
def aiwelcome_call():
    data = request.json

    if "phone" in data and "fullname" in data:
        country_code = re.match(r"\+\d+", data["phone"]).group()
        to_number = country_code  + re.sub(r"\D", "", data["phone"][len(country_code):])
        fullname = data["fullname"]

        try:
            call = client.calls.create(
                to=to_number,
                from_=TWILIO_PHONE_NUMBER,
                url=f"http://159.223.165.147:5555/api/v1/agent/handle-call"
            )

            return jsonify({"message": "Call initiated", "call_sid": call.sid})
        
        except:
            return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

    return jsonify({"message": "Call initiated", "call_sid": call.sid})


@agent.post("/handle-call")
async def incoming_call():

    # Set the audio URL to the pre-recorded welcome message
    print("handle call")
    # Create TwiML response: play audio and record input without transcription
    response = VoiceResponse()
    response.say("Welcome to the AI Agent. Please state your question.", voice='alice')

    # Record user input without Twilio transcription
    response.record(
        action=
        "http://159.223.165.147:5555/api/v1/agent/process_recording",  # Send to process_recording to handle the input
        method="POST",
        max_length=30,
        play_beep=True,
        timeout=3,
        finish_on_key="q"  # Optional: Allows caller to end input with "#"
    )

    return str(response)

@agent.route("/process_recording", methods=["GET", "POST"])
def process_recording():
    try:
        form_data = request.form
        # print(form_data)

        recording_url = request.form['RecordingUrl']
        print('recording', recording_url)
        response = VoiceResponse()
        response.say("Please wait while I process your message.")
        user_input = transcribe_audio(recording_url)
        print('user_input', user_input)

        if not recording_url:
            print("Missing required fields: RecordingUrl or CallSid")
            response = VoiceResponse()
            response.say("We encountered an error processing your input.")
            response.hangup()
            return str(response)

        # Log the recording URL
        print(f"Recording URL received: {recording_url}")

        if user_input:
            ai_response = generate_prompt(user_input)
            print('ai_response', ai_response)
            response.say(ai_response)
            response.pause(length=2)
            response.say("Thanks for your asking, Good bye!")
        else:
            response.say("I'm sorry, I couldn't understand your message. Please try again.")

        response.hangup()

        return str(response)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions like timeout, connection error
        print(f"Recording failed due to an exception: {e}")


def transcribe_audio(audio_url):
    """
    Transcribe the user's audio message using OpenAI Whisper API for Speech-to-Text.
    """
    try:
        # Ensure directories exist
        os.makedirs('static/build/audio', exist_ok=True)
        os.makedirs('static/build/audio_converted', exist_ok=True)

        # Log the start of the download process
        print(f"Downloading audio from: {audio_url}")
        audio_path = download_recording_with_retry(audio_url, 5, 2)
        
        # if audio_response.status_code != 200:
        #     raise Exception(f"Failed to download audio. HTTP Status: {audio_response.status_code}")
        

        # # Save the downloaded audio
        # audio_path = os.path.join('static/build/audio', "audio.wav")
        # with open(audio_path, 'wb') as audio_file:
        #     for chunk in audio_response.iter_content(chunk_size=8192):
        #         audio_file.write(chunk)
        

        # Convert to WAV format
        print("Converting audio to WAV format...")
        audio = AudioSegment.from_file(audio_path)
        wav_path = os.path.join('static/build/audio_converted', "audio_converted.wav")
        audio.export(wav_path, format="wav")
        print("Audio converted to WAV format. Path:", wav_path)

        # Send the WAV file to Whisper API for transcription
        print("Sending audio to OpenAI Whisper API...")
        response = transcribe_audio_whisper(wav_path)  # Assumes this is defined elsewhere and works correctly
        print('transcribe_audio_whisper', response)
        # Extract the transcription result
        transcription = response.get('text', '')
        print(f"Transcription result: {transcription}")

        return transcription

    except requests.RequestException as req_err:
        print(f"Request error: {req_err}")
        return None
    except FileNotFoundError as fnf_err:
        print(f"File error: {fnf_err}")
        return None
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None


def download_recording_with_retry(recording_url, max_retries=5, delay=2):
    for attempt in range(max_retries):
        response = requests.get(recording_url, auth=(TWILIO_SID, TWILIO_AUTH_TOKEN), stream=True)

        if response.status_code == 200:
            # Save the recording to a file
            audio_file_path = os.path.join('static/build/audio', "audio.wav")
            with open(audio_file_path, "wb") as audio_file:
                audio_file.write(response.content)
            print(f"Recording downloaded successfully after {attempt + 1} attempt(s).")
            return audio_file_path

        print(f"Attempt {attempt + 1} failed. Recording not yet available. Status code: {response.status_code}")

        # Wait before retrying
        time.sleep(delay)

    # If the recording is still not available after all retries, return None
    print("Recording not available after maximum retries.")
    return None


# Route for outbound call prompt
@agent.route("/outbound-prompt", methods=["GET"])
def outbound_prompt():
    response = VoiceResponse()
    response.say("Hello, this is a call from our system. Please listen to the prompt.", voice='alice')
    # Add other prompts as needed
    response.say("Press 1 for assistance. Press 2 to end the call.", voice='alice')
    return str(response)


# Celery task to simulate transferring large scale calls
@Celery.task
def process_high_volume_calls():
    # Logic to simulate high-volume call processing, e.g., calling APIs to initiate calls
    pass


@agent.route('/add_to_queue', methods=['POST'])
def add_to_queue():
    """Adds a phone number to the dialer queue."""
    global call_queue

    data = request.json
    if "phone" in data:
        phone_number = "+" + str(data["phone"]["countryCode"]) + str(data["phone"]["areaCode"]) + str(data["phone"]["phoneNumber"])
        call_queue.append(phone_number)
        print(call_queue)

        return jsonify({"status": "success", "message": "Added the phone number", "phone_number": phone_number})
        
    return jsonify({"status": "Failed", "message": "No phone number provided"}), 400


def initiate_call(to_number):
    """Initiates a call and plays a TwiML prompt."""
    global current_call_sid, is_calling, power_dialer_prompt

    answer = generate_prompt(power_dialer_prompt)

    is_calling = True

    status_callback_url = "http://159.223.165.147:5555/api/v1/agent/call_status_update" 

    call = client.calls.create(
        to=to_number,
        from_=TWILIO_PHONE_NUMBER,
        twiml=f"<Response><Say>{power_dialer_prompt}</Say><Say>{answer}</Say></Response>",
        status_callback=status_callback_url,  # Set the callback URL
        status_callback_event=['completed', 'failed', 'no-answer', 'busy'],
    )
    current_call_sid = call.sid
    print(f"Call initiated with SID: {call.sid}")


def dialer_loop():
    """Continuously processes the queue and makes calls sequentially."""
    global is_calling
    while call_queue:
        if not is_calling:
            # Get the next number from the queue
            next_number = call_queue.pop(0)
            print(f"Dialing: {next_number}")
            initiate_call(next_number)
        
        # Wait a short time before checking call status again
        time.sleep(2)

@agent.route('/start_dialer', methods=['POST'])
def start_dialer():
    global power_dialer_prompt

    data = request.json
    power_dialer_prompt = data["prompt"]

    try:
        if len(call_queue) <=0:
            return jsonify({"status": "failed", "message": "Dialer failed"})
        else:
            dialer_thread = threading.Thread(target=dialer_loop)
            dialer_thread.start()
            return jsonify({"status": "success", "message": "Dialer started"})

    except requests.exceptions.RequestException as e:
        return jsonify({"status": "failed", "message": "Dialer failed"})


@agent.route('/api/v1/dialer/prompt', methods=['GET', 'POST'])
def dialer_prompt():
    """TwiML response that plays a prompt for outbound calls."""
    response = VoiceResponse()
    response.say("Hello, this is an automated call. Please stay on the line for further assistance.", voice='alice')
    return str(response)


@agent.route('/call_status_update', methods=['POST'])
def call_status_update():
    """Handles call status updates from Twilio."""
    global is_calling, current_call_sid
    
    call_sid = request.form.get('CallSid')
    call_status = request.form.get('CallStatus')
    to_number = request.form.get('To')
    from_number = request.form.get('From')
    timestamp = request.form.get('Timestamp', None)
    
    print(f"Received status update: {call_status} for call SID: {call_sid}")

    # Update the current call state
    if call_sid == current_call_sid:
        if call_status in ['completed', 'failed', 'no-answer', 'busy']:
            is_calling = False
            current_call_sid = None
    
    # Log the call status for record-keeping
    call_logs[call_sid] = {
        "status": call_status,
        "to": to_number,
        "from": from_number,
        "timestamp": timestamp,
    }

    return '', 200


def generate_prompt(prompt):

    url = f"{OPEN_AI_URL}/v1/chat/completions"

    if os.environ.get("APP_ENV") == "development":
        proxy = {
            'http': os.environ.get("PROXY_FOR_OPENAI"),
            'https': os.environ.get("PROXY_FOR_OPENAI")
        }
    else:
        proxy = None
    
    payload = {
        "model": "gpt-3.5-turbo",
        "temperature": 0.7,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY"),
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), proxies=proxy)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]

    except requests.exceptions.RequestException as e:
        return f"Request failed with status code {response.status_code}: {response.text}"


def transcribe_audio_whisper(wav_path):
    url = "https://api.openai.com/v1/audio/transcriptions"
    
    # Only include Authorization in the headers; Content-Type is set automatically for multipart form-data.
    headers = {
        "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY"),
    }

    try:
        with open(wav_path, 'rb') as audio_file:
            # Prepare the multipart form-data
            files = {
                "file": audio_file,  # The binary audio file
                "model": (None, "whisper-1"),  # Model name,
                "language": (None, "en")
            }
            
            # Make the POST request
            response = requests.post(url, headers=headers, files=files)
            
            # Check for errors
            if response.status_code != 200:
                return f"Request failed with status code {response.status_code}: {response.text}"

            # Return the response as JSON
            return response.json()

    except requests.exceptions.RequestException as e:
        return f"An exception occurred: {str(e)}"


if __name__ == "__main__":
        
    app.run(debug=True, host="0.0.0.0", port=5000)
