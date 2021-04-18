from app import app
from config import config

if __name__ == "__main__":

    if config['application'].getboolean('use_https'):
        app.run(ssl_context=('ssl/cert.pem', 'ssl/key.pem'))
    else:
        app.run()
