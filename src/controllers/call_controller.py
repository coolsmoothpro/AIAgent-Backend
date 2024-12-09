from flask import Flask, request, jsonify, Response, Blueprint, json, redirect
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

app = Flask(__name__)

agent = Blueprint("agent", __name__)
sockets = Sockets()

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


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

@agent.route('/aiwelcome-call', methods=['POST'])
def aiwelcome_call():
    data = request.json
    
    print('cert', cert_path)
    print('key_path', key_path)
    logger.info("This is an aiwelcome_call")

    if "phone" in data and "fullname" in data:
        country_code = re.match(r"\+\d+", data["phone"]).group()
        to_number = country_code  + re.sub(r"\D", "", data["phone"][len(country_code):])
        fullname = data["fullname"]

        try:
            call = client.calls.create(
                to=to_number,
                from_=TWILIO_PHONE_NUMBER,
                url=f"http://159.223.165.147:5555/api/v1/agent/voice"
            )

            return jsonify({"message": "Call initiated", "call_sid": call.sid})
        
        except:
            return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

    return jsonify({"message": "Call initiated", "call_sid": call.sid})

# @agent.route("/voice", methods=["GET", "POST"])
# def voice():
#     """Respond to incoming phone calls with a prompt for AI interaction."""
    
#     response = VoiceResponse()
#     # Ask for input from the user (this will be spoken to the user)
#     response.say("Hello, this is your AI assistant. Please say something and I will respond.")
    
#     # Record the user's speech
#     response.record(timeout=5, transcribe=True, transcribe_callback="http://159.223.165.147:5555/api/v1/agent/transcription")
    
#     return str(response)

# @agent.route("/transcription", methods=["POST"])
# def transcription():
#     """Receive the transcription of the user's speech, send it to OpenAI, and return a response."""
    
#     # Get the transcription text from the Twilio request
#     transcription = request.form.get("TranscriptionText")
    
#     if transcription:

#         # Get the response from OpenAI
#         ai_response = generate_prompt(transcription)
        
#         # Now respond back to the user with the AI's response
#         return redirect(f"http://159.223.165.147:5555/api/v1/agent/speak?text={ai_response}")
    
#     return "Sorry, I couldn't understand your input."


# @agent.route("/speak", methods=["GET"])
# def speak():
#     """Convert the AI response into speech and play it back to the user."""
    
#     # Get the AI response from the URL parameter
#     text = request.args.get("text")
    
#     if text:
#         response = VoiceResponse()
#         response.say(text)
#         response.hangup()
#         return str(response)
    
#     return "Sorry, I didn't get any response from the AI."

@agent.route("/voice", methods=["GET", "POST"])
def voice():
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    response.say("Please wait while we connect your call to the AI. voice assistant, powered by Twilio and the Open-A.I. Realtime API")
    response.pause(length=1)
    
    connect = Connect()
    connect.stream(url=f'ws://159.223.165.147:5555/api/v1/agent/media-stream')
    response.append(connect)
    response.say("O.K. you can start talking!")
    print("you can start talking")
    response.pause(length=5)
    return Response(str(response), content_type="application/xml")

@sockets.route("/media-stream")
def handle_media_stream(websocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("streaming connection") 
    asyncio.run(handle_websocket_connection(websocket))
    # return app.sockets.handle_websocket_connection()


# @sockets.route("/api/v1/agent/media-stream")
async def handle_websocket_connection(websocket):
    """Handles the WebSocket connection for media stream."""
    print("Client connected")
    
    await websocket.accept()

    async with websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Connection specific state
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        
        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except websockets.exceptions.WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    if response.get('type') == 'response.audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                            if SHOW_TIMING_MATH:
                                print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                        # Update last_assistant_item safely
                        if response.get('item_id'):
                            last_assistant_item = response['item_id']

                        await send_mark(websocket, stream_sid)

                    # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Greet the user with 'Hello there! I am an AI voice assistant powered by Twilio and the OpenAI Realtime API. You can ask me for facts, jokes, or anything you can imagine. How can I help you?'"
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def initialize_session(openai_ws):
    """Control initial session with OpenAI."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

# Route to make outbound call
# @agent.route("/aiwelcome-call", methods=["POST"])
# def aiwelcome_call():
#     data = request.json
#     if "phone" in data and "fullname" in data:
#         country_code = re.match(r"\+\d+", data["phone"]).group()
#         to_number = country_code  + re.sub(r"\D", "", data["phone"][len(country_code):])
#         fullname = data["fullname"]
#         answer = f"Hello, {fullname}, Welcome to LeadGoblin! I am Alyse, your personalized AI assistant, designed to make your life easier by handling everything from answering questions and managing schedules to offering smart recommendations. Whether you need quick insights, task automation, or just a helping hand, I am here to support you every step of the way."

#         # Generate audio with Deepgram
#         audio_filename = generate_audio_with_deepgram(answer)

#         if not audio_filename  :
#             return jsonify({"status": "Call Failed", "reason": "Audio generation failed"}), 500

#         public_audio_url = f"http://159.223.165.147:5555/build/audio/{audio_filename}"

#         try:
#             call = client.calls.create(
#                 twiml=f'<Response><Play>{public_audio_url}</Play></Response>',
#                 to=to_number,
#                 from_=TWILIO_PHONE_NUMBER,
#             )            
        
#             print(call.sid)
            
#             return jsonify({"status": "Call initiated", "call_sid": call.sid})

#         except:
#             return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

#     return jsonify({"status": "Call Failed", "reason": "No phone number provided"}), 400


# @agent.route('/aiwelcome-call', methods=['POST'])
# def aiwelcome_call():
#     data = request.json
#     if "phone" in data and "fullname" in data:
#         country_code = re.match(r"\+\d+", data["phone"]).group()
#         to_number = country_code  + re.sub(r"\D", "", data["phone"][len(country_code):])
#         fullname = data["fullname"]

#         try:
#             call = client.calls.create(
#                 to=to_number,
#                 from_=TWILIO_PHONE_NUMBER,
#                 url=f"http://159.223.165.147:5555/api/v1/agent/voice"
#             )

#             return jsonify({"message": "Call initiated", "call_sid": call.sid})
        
#         except:
#             return jsonify({"status": "This is a Trial account. You cannot call unverifed phone number!"})

#     return jsonify({"message": "Call initiated", "call_sid": call.sid})

# # Twilio Voice Webhook
# @agent.route('/voice', methods=['POST'])
# def voice_response():
#     # Twilio's request passes the user's input (DTMF or speech) to this route.
#     response = VoiceResponse()

#     response.say("Welcome to the AI Agent. Please state your question.", voice='alice')

#     # Capture the user's input via speech
#     response.connect().stream(
#         url=f'wss://159.223.165.147:8765'
#     )

#     return str(response)








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
    # websocket_thread = threading.Thread(target=start_websocket_server)
    # websocket_thread.daemon = True
    # websocket_thread.start()

    app.run(ssl_context=('/etc/letsencrypt/live/www.leadgoblin.com/fullchain.pem',
                     '/etc/letsencrypt/live/www.leadgoblin.com/privkey.pem'),
        host='0.0.0.0', port=5555)
    # app.run(debug=True, host="0.0.0.0", port=5000)
    # server = pywsgi.WSGIServer(('0.0.0.0', 5555), app, handler_class=WebSocketHandler, ssl_context=('/etc/letsencrypt/live/www.leadgoblin.com/fullchain.pem',
    #                  '/etc/letsencrypt/live/www.leadgoblin.com/privkey.pem'))
    # server.serve_forever()
