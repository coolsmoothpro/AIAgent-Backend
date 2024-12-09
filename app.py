from src import config, app
from flask import Flask

if __name__ == "__main__":
    app.run(
        host= config.HOST,
        port= config.PORT,
        debug= config.DEBUG,
        ssl_context=('/etc/letsencrypt/live/www.leadgoblin.com/fullchain.pem',
                     '/etc/letsencrypt/live/www.leadgoblin.com/privkey.pem')
    )