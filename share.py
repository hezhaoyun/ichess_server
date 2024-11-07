import logging
from typing import List

from flask_socketio import emit, send


class running:
    online_players: List[str] = []  # list of all players connected
    waiting_players: List[str] = []  # list of players waiting to be matched
    games = []  # list of all games


def send_message(sids: List[str], message: str):
    # message privately everyone on the list
    for sid in sids:
        send(message, to=sid)


def send_command(sids: List[str], event: str, message: dict):
    # 使用 socketio.emit() 替代 emit()
    for sid in sids:
        emit(event, message, room=sid)


def get_logger() -> logging.Logger:
    logger = logging.getLogger('CRS')
    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger


logger = get_logger()
