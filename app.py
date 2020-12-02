from flask import Flask
import configparser

config = configparser.ConfigParser()
config.read('properties.ini')

app = Flask(__name__)

@app.route('/version')
def version():
    return "Version: {0}".format(config['application']['version'])


if __name__ == '__main__':
    app.run(port=config['application']['port'])
