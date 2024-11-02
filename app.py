from flask import Flask
from flask_socketio import SocketIO

import src.server as server

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chessroad-upup'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')


@app.route('/')
def index():
    return 'Chess Server is running!'


@socketio.on('connect')
def on_connect():
    server.on_connect()


@socketio.on('disconnect')
def on_disconnect():
    server.on_disconnect()


@socketio.on('match')
def on_match(data):
    server.on_match(data)


@socketio.on('forfeit')
def on_forfeit(data):
    server.on_forfeit(data)


@socketio.on('move')
def on_move(data):
    server.on_move(data)


@socketio.on('message')
def on_message(data):
    server.on_message(data)


if __name__ == '__main__':
    socketio.run(app)
