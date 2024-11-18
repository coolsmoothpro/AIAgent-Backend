import jwt
import os
import uuid
from flask import request, Response, json, Blueprint
from datetime import datetime, timedelta, timezone
from src.models.model import User
from src import bcrypt, db
from src.middlewares import authentication_required

# user controller blueprint to be registered with api blueprint
auth = Blueprint("auth", __name__)

# login api/auth/signin
@auth.route('/signin', methods = ["POST"])
def handle_login():
    try: 
        # first check user parameters
        data = request.json
        if "email" and "password" in data:
            # check db for user records
            user = User.query.filter_by(email = data["email"]).first()

            # if user records exists we will check user password
            if user:
                # check user password
                if bcrypt.check_password_hash(user.password, data["password"]):
                    # user password matched, we will generate token
                    payload = {
                        'iat': datetime.now(timezone.utc),
                        'exp': datetime.now(timezone.utc) + timedelta(days=7),
                        'fullname': user.fullname,
                        'email': user.email,
                        'phone': user.phone
                    }
                    token = jwt.encode(payload,os.getenv('SECRET_KEY'),algorithm='HS256')
                    return Response(
                            response=json.dumps({
                                    'status': True,
                                    "message": "User Sign In Successful",
                                    "payload": {
                                        "token": token,
                                        "data": payload
                                    }
                                }),
                            status=200,
                            mimetype='application/json'
                        )
                else:
                    return Response(
                        response=json.dumps({'status': False, "message": "User Password Mistmatched"}),
                        status=401,
                        mimetype='application/json'
                    ) 
            # if there is no user record
            else:
                return Response(
                    response=json.dumps({'status': False, 
                        "message": "User Record doesn't exist, kindly register"}),
                    status=404,
                    mimetype='application/json'
                ) 
        else:
            # if request parameters are not correct 
            return Response(
                response=json.dumps({'status': False, "message": "User Parameters Email and Password are required"}),
                status=400,
                mimetype='application/json'
            )
        
    except Exception as e:
        return Response(
                response=json.dumps({'status': False, 
                                     "message": "Error Occured",
                                     "error": str(e)}),
                status=500,
                mimetype='application/json'
            )

        
@auth.route('/signup', methods = ["POST"])
def handle_signup():
    try:
        data = request.json
        if "email" in data and "password" in data and "fullname" in data and "phone" in data:
            user = User.query.filter_by(email = data["email"]).first()

            if not user:
                user_obj = User(
                    # id = uuid.uuid4(),
                    email = data["email"],
                    password = bcrypt.generate_password_hash(data['password']).decode('utf-8'),
                    fullname = data["fullname"],
                    phone = "+"+str(data["phone"]["countryCode"])+str(data["phone"]["areaCode"])+str(data["phone"]["phoneNumber"]),                                
                )

                db.session.add(user_obj)
                db.session.commit()
 
                payload = {
                    'iat': datetime.now(timezone.utc),
                    'exp': datetime.now(timezone.utc) + timedelta(days=7),
                    'email': user_obj.email,
                    'password': user_obj.password,
                    'phone': user_obj.phone,
                    'fullname': user_obj.fullname
                }
                token = jwt.encode(payload,os.getenv('SECRET_KEY'), algorithm='HS256')
                return Response(
                    response=json.dumps({
                        'status': True,
                        "message": "User Sign up Successful",
                        "payload": {
                            "token": token
                        }}),
                    status=201,
                    mimetype='application/json'
                )
            else:
                # if user already exists
                return Response(
                response=json.dumps({
                    'status': False, 
                    "message": "User already exists kindly use sign in"
                }),
                status=409,
                mimetype='application/json'
            )
        else:
            # if request parameters are not correct 
            return Response(
                response=json.dumps({
                    'status': False, 
                    "message": "User Parameters Username, Email, Phone number and Password are required"
                }),
                status=400,
                mimetype='application/json'
            )
        
    except Exception as e:
        return Response(
            response=json.dumps({
                'status': False, 
                "message": "Error Occured",
                "error": str(e)
            }),
            status=500,
            mimetype='application/json'
        )
        
@auth.route('/onboarding', methods = ["POST"])
@authentication_required
def handle_onboarding(auth_data):
    try:         
        data = request.json
        client_obj = Client.query.filter_by(email = auth_data["email"]).first()
        if client_obj:
            client_obj.advisor = data["advisorName"],
            client_obj.primary_goal = data["primary_goal"],
            client_obj.challenge = data["challenge"],
            client_obj.comfortable = data["comfortable"],
            client_obj.situation = data["situation"],
            client_obj.short_goal = data["short_goal"],
            client_obj.medium_goal = data["medium_goal"],
            client_obj.long_goal = data["long_goal"]  
            db.session.commit()
            
            return Response(
                response=json.dumps({
                    'status': True,
                    "message": "User Sign up Successful",
                }),
                status=201,
                mimetype='application/json'
            )
        else:
            # if user already exists
            return Response(
            response=json.dumps({
                'status': False, 
                "message": "User doesn't exist."
            }),
            status=409,
            mimetype='application/json'
        )
        
        
    except Exception as e:
        return Response(
            response=json.dumps({
                'status': False, 
                "message": "Error Occured",
                "error": str(e)
            }),
            status=500,
            mimetype='application/json'
        )