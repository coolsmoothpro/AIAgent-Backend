from flask import Flask, request, jsonify
import requests
import os
from flask import request, Response, json, Blueprint
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from celery import Celery
import time
import threading
import re


# # Setup Celery for async tasks
# app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
# app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
# celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
# celery.conf.update(app.config)

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


agent = Blueprint("agent", __name__)

# Route to receive incoming calls
@agent.route("/incoming-call", methods=["POST"])
def incoming_call():
    print("incoming call")
    response = VoiceResponse()

    response.say("Thank you for calling. Please wait while we connect you to an agent.", voice='alice')

    # Transfer to live agent (e.g., an agent's number or conference room)
    response.dial("+19032184512")  # Replace with live agent's phone number or conference room

    return str(response)

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


# Route to make outbound call
@agent.route("/aiwelcome-call", methods=["POST"])
def aiwelcome_call():
    data = request.json
    if "phone" in data and "fullname" in data:
        country_code = re.match(r"\+\d+", data["phone"]).group()
        to_number = country_code  + re.sub(r"\D", "", data["phone"][len(country_code):])
        fullname = data["fullname"]
        answer = f"Hello, {fullname}, Welcome to LeadGoblin! I am Alyse, your personalized AI assistant, designed to make your life easier by handling everything from answering questions and managing schedules to offering smart recommendations. Whether you need quick insights, task automation, or just a helping hand, I am here to support you every step of the way."

        # Generate audio with Deepgram
        audio_filename = generate_audio_with_deepgram(answer)

        if not audio_filename  :
            return jsonify({"status": "Call Failed", "reason": "Audio generation failed"}), 500

        public_audio_url = f"http://159.223.165.147:5555/build/audio/{audio_filename}"

        try:
            call = client.calls.create(
                twiml=f'<Response><Play>{public_audio_url}</Play></Response>',
                to=to_number,
                from_=TWILIO_PHONE_NUMBER,
            )            
        
            print(call.sid)
            
            return jsonify({"status": "Call initiated", "call_sid": call.sid})

        except:
            return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

    return jsonify({"status": "Call Failed", "reason": "No phone number provided"}), 400


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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
