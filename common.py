import logging

from flask_socketio import emit, send


class running:
    players = []  # list of all players connected
    waiting_players = []  # list of players waiting to be matched
    games = []  # list of all games


def send_message(sids, message):
    # message privately everyone on the list
    for sid in sids:
        send(message, to=sid)


def send_command(sids: list[str], event: str, message: dict):
    # 使用 socketio.emit() 替代 emit()
    for sid in sids:
        emit(event, message, room=sid)


def get_logger():
    logger = logging.getLogger('CHESS-SERVER')
    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger


logger = get_logger()
