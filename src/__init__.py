from flask import Flask
from flask_sockets import Sockets
import os
from src.config.config import Config
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask import send_from_directory

load_dotenv()

app = Flask(__name__)
# socketio = SocketIO(app, cors_allowed_origins="*")
sockets = Sockets(app)

app = Flask(__name__, static_folder='../static/build', template_folder='templates')

CORS(app)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory('../static/build', 'index.html')


if os.environ.get("APP_ENV") == 'development':
    config = Config().dev_config
else:
    config = Config().production_config

app.env = config.ENV

app.secret_key = os.environ.get("SECRET_KEY")
bcrypt = Bcrypt(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("MYSQL_DB_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = os.environ.get("SQLALCHEMY_TRACK_MODIFICATIONS")

app.config['PUBLIC_FOLDER'] = os.path.join(os.getcwd(), 'public')

db = SQLAlchemy(app)

from src.routes import api
app.register_blueprint(api, url_prefix="/api/v1")