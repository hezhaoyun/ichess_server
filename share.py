import logging
import platform
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


def get_native_engine_path():
    STOCKFISH_PATH_LINUX_POPCNT = './stockfish/linux-popcnt'
    STOCKFISH_PATH_LINUX_AVX2 = './stockfish/linux-avx2'  # faster than popcnt
    STOCKFISH_PATH_MAC_APPLE_SILICON = './stockfish/apple-silicon'

    # Determine CPU type and set Stockfish path
    if platform.system() == 'Linux':
        if 'avx2' in platform.uname().machine:
            STOCKFISH_PATH = STOCKFISH_PATH_LINUX_AVX2
        else:
            STOCKFISH_PATH = STOCKFISH_PATH_LINUX_POPCNT

    elif platform.system() == 'Darwin':
        STOCKFISH_PATH = STOCKFISH_PATH_MAC_APPLE_SILICON

    else:
        raise Exception('Unsupported operating system')

    return STOCKFISH_PATH

class Reasons:
    class Win:
        CHECKMATE = 'CHECKMATE'
        OPPONENT_OUT_OF_TIME = 'OPPONENT_OUT_OF_TIME'
        OPPONENT_RESIGNED = 'OPPONENT_RESIGNED'
        OPPONENT_LEFT = 'OPPONENT_LEFT'
    
    class Lose:
        CHECKMATED = 'CHECKMATED'
        OUT_OF_TIME = 'OUT_OF_TIME'
        RESIGNED = 'RESIGNED'
    
    class Draw:
        STALEMATE = 'STALEMATE'
        INSUFFICIENT_MATERIAL = 'INSUFFICIENT_MATERIAL'
        CONSENSUS = 'CONSENSUS'
