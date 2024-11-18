from src import config, app
from flask import Flask

app = Flask(__name__, static_folder='static/build', template_folder='static/build')

if __name__ == "__main__":
    app.run(
        host= config.HOST,
        port= config.PORT,
        debug= config.DEBUG
    )