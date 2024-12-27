import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, List

from flask import Flask
from flask_socketio import SocketIO, emit, send


class running:
    online_players: List[str] = []
    waiting_players: Dict[str, str] = {}
    games = []
    socketio: SocketIO = None


def create_socketio(app: Flask):

    if running.socketio is None:
        running.socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

    return running.socketio


def send_message(sids: List[str], message: str):

    thread_name = threading.current_thread().name

    # message privately everyone on the list
    if thread_name.startswith('timer_task') or thread_name == 'match_players':

        for sid in sids:
            if sid.startswith('bot_'):
                continue
            running.socketio.send(message, to=sid)

    else:

        for sid in sids:
            if sid.startswith('bot_'):
                continue
            send(message, to=sid)


def send_command(sids: List[str], event: str, data: dict):

    thread_name = threading.current_thread().name

    if thread_name.startswith('timer_task') or thread_name == 'match_players':

        for sid in sids:
            if sid.startswith('bot_'):
                continue
            running.socketio.emit(event, data, to=sid)

    else:

        for sid in sids:
            if sid.startswith('bot_'):
                continue
            emit(event, data, to=sid)


def get_logger(mod_name) -> logging.Logger:
    if mod_name == '__main__':
        mod_name = 'app'
    
    logger = logging.getLogger(mod_name)
    logger.setLevel(logging.INFO)

    handler = TimedRotatingFileHandler(f'./logs/{mod_name}.log', when='midnight', interval=1, backupCount=7)
    handler.suffix = '%Y-%m-%d'
    handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger
