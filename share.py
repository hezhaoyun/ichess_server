import logging
import threading
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


def send_command(sids: List[str], event: str, message: dict):

    thread_name = threading.current_thread().name

    if thread_name.startswith('timer_task') or thread_name == 'match_players':
    
        for sid in sids:
            if sid.startswith('bot_'):
                continue
            running.socketio.emit(event, message, to=sid)
    
    else:
    
        for sid in sids:
            if sid.startswith('bot_'):
                continue
            emit(event, message, to=sid)


def get_logger() -> logging.Logger:
    logger = logging.getLogger('CRS')
    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger


logger = get_logger()
