from flask import Flask, request, jsonify
import requests
import os
from flask import request, Response, json, Blueprint
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from celery import Celery
import time
import threading


# # Setup Celery for async tasks
# app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
# app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
# celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
# celery.conf.update(app.config)

# Twilio credentials
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

OPEN_AI_URL = 'https://api.openai.com'

call_queue = [] 
is_calling = False
current_call_sid = None

agent = Blueprint("agent", __name__)

# Route to receive incoming calls
@agent.route("/incoming-call", methods=["POST"])
def incoming_call():
    data = request.json
    if "phone" in data and "prompt" in data:
        phone = "+" + str(data["phone"]["countryCode"]) + str(data["phone"]["areaCode"]) + str(data["phone"]["phoneNumber"])
        # prompt = data["prompt"]
        # answer = generate_prompt(prompt)
        # print(answer)
        response = VoiceResponse()

        response.say("Thank you for calling. Please wait while we connect you to an agent.", voice='alice')

        # Transfer to live agent (e.g., an agent's number or conference room)
        # response.dial("+12765658476")  # Replace with live agent's phone number or conference room

        return str(response)


# Route to make outbound call
@agent.route("/aiagent-call", methods=["POST"])
def aiagent_call():
    data = request.json
    if "phone" in data and "prompt" in data:
        to_number = "+" + str(data["phone"]["countryCode"]) + str(data["phone"]["areaCode"]) + str(data["phone"]["phoneNumber"])
        prompt = data["prompt"]
        answer = generate_prompt(prompt)
        print(to_number)
        try:
            call = client.calls.create(
                twiml=f"<Response><Say>{answer}</Say></Response>",
                to=to_number,
                from_=TWILIO_PHONE_NUMBER,
                # url="http://127.0.0.1:5555/api/v1/agent/outbound-prompt"
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
    data = request.json
    if "phone" in data:
        phone_number = "+" + str(data["phone"]["countryCode"]) + str(data["phone"]["areaCode"]) + str(data["phone"]["phoneNumber"])
        call_queue.append(phone_number)
        print(call_queue)

        return jsonify({"status": "Added to queue", "phone_number": phone_number})
        
    return jsonify({"status": "Failed", "reason": "No phone number provided"}), 400


def initiate_call(to_number):
    """Initiates a call and plays a TwiML prompt."""
    global current_call_sid, is_calling
    is_calling = True
    call = client.calls.create(
        to=to_number,
        from_=TWILIO_PHONE_NUMBER,
        twiml=f"<Response><Say>Hello, this is an automated call. Please stay on the line for further assistance.</Say></Response>",
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

    # Start the dialer in a background thread
    dialer_thread = threading.Thread(target=dialer_loop)
    dialer_thread.start()
    return jsonify({"status": "Dialer started"})


@agent.route('/api/v1/dialer/prompt', methods=['GET', 'POST'])
def dialer_prompt():
    """TwiML response that plays a prompt for outbound calls."""
    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say("Hello, this is an automated call. Please stay on the line for further assistance.", voice='alice')
    return str(response)


@agent.route('/call_status_update', methods=['POST'])
def call_status_update():
    """Handles call status updates from Twilio."""
    global is_calling, current_call_sid
    call_sid = request.form.get('CallSid')
    call_status = request.form.get('CallStatus')
    print(f"Received status update: {call_status} for call SID: {call_sid}")

    if call_sid == current_call_sid:
        if call_status in ['completed', 'failed', 'no-answer', 'busy']:
            # Reset calling state to allow the next call in the queue
            is_calling = False
            current_call_sid = None

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
