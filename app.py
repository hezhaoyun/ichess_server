from datetime import datetime
from random import shuffle
from typing import List, Optional

from flask import Flask, request

from game import Game
from player import join, name_of
from share import create_socketio, logger, running, send_command, send_message

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chessroad-upup'
socketio = create_socketio(app)


@app.route('/')
def index():
    return '欢迎来到 Chessroad!\n' \
           + f"服务器时间: {datetime.now().strftime('%H:%M')}\n" \
           + f'当前在线玩家: {len(running.online_players)}\n' \
           + f'当前匹配对局等待列表: {len(running.waiting_players)}\n'


@socketio.on('connect')
def on_connect():
    # what happens when somebody connects
    logger.info(f'New connection made: {request.sid}')

    running.online_players.append(request.sid)

    welcome()

    send_message(running.waiting_players, '新玩家已连接，等待匹配对局！')


@socketio.on('disconnect')
def on_disconnect():
    # Maintaining numbers and lists of ALL connected players
    running.online_players.remove(request.sid)

    # Disconnected player was in a waiting list
    if request.sid in running.waiting_players:
        running.waiting_players.remove(request.sid)

    # Disconnected player was in a game, checking
    for game in running.games:
        if request.sid in game.players:
            logger.info('Player in a chess game has disconnected')
            game.player_disconnected(request.sid)

    logger.info('Connection Lost and handled by the server')


@socketio.on('join')
def on_join(data):
    logger.info(f'{request.sid} logged in with {data}.')

    if 'pid' not in data or 'name' not in data:
        send_message(request.sid, '登录失败，请检查客户端版本！')
        return

    join(request.sid, data['pid'], data['name'])

    on_match(data)


@socketio.on('match')
def on_match(_):
    logger.info(f'{request.sid} wants to play.')

    game = find_game(request.sid)
    if game:
        logger.info(f'{request.sid} is already in a game.')
        return

    # the client is not playing in a game
    if request.sid not in running.waiting_players:
        running.waiting_players.append(request.sid)
        match_making()


@socketio.on('move')
def on_move(data):
    logger.info(f'{request.sid} wants to move {data}.')

    game = find_game(request.sid)
    if game:
        if game.on_move(data, request.sid):
            # Engage the next turn function
            game.after_move()
        else:
            logger.info(f'{request.sid} sent an invalid move.')
    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('propose_draw')
def on_propose_draw(_):
    logger.info(f'{request.sid} proposed a draw.')

    game = find_game(request.sid)
    if game:
        if game.on_draw_proposal(request.sid):
            logger.info(f'{request.sid} proposed a draw')
        else:
            logger.info(f'{request.sid} draw proposal failed')


@socketio.on('draw_response')
def on_draw_response(data):
    logger.info(f'{request.sid} responded to draw: {data}')

    game = find_game(request.sid)
    if game:
        accepted = data.get('accepted', False)
        if game.on_draw_response(request.sid, accepted):
            logger.info(f'{request.sid} responded to draw: {accepted}')
        else:
            logger.info(f'{request.sid} draw response failed')


@socketio.on('propose_takeback')
def on_propose_takeback(_):
    game = find_game(request.sid)
    if game:
        if game.on_takeback_proposal(request.sid):
            logger.info(f'{request.sid} requested takeback')
        else:
            logger.info(f'{request.sid} takeback request failed')


@socketio.on('takeback_response')
def on_takeback_response(data):
    game = find_game(request.sid)
    if game:
        accepted = data.get('accepted', False)
        if game.on_takeback_response(request.sid, accepted):
            logger.info(f'{request.sid} responded to takeback: {accepted}')
        else:
            logger.info(f'{request.sid} takeback response failed')


@socketio.on('forfeit')
def on_forfeit(_):
    logger.info(f'{request.sid} wants to forfeit.')

    game = find_game(request.sid)
    if game:
        game.on_forfeit(request.sid)
    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('message')
def on_message(data):
    # we got something from a client
    logger.info(f'{request.sid} sent a message: {data}')


def welcome():
    # a bunch of on-login messages
    send_message([request.sid], '欢迎来到 Chessroad!')
    send_message([request.sid], f"服务器时间: {datetime.now().strftime('%H:%M')}")
    send_message([request.sid], f'当前在线玩家: {len(running.online_players)}')
    send_message([request.sid], f'当前匹配对局等待列表: {len(running.waiting_players) + 1}')


def match_making():
    # Find two players on a waiting list and make them play
    # Is there enough players in waiting queue
    if (len(running.waiting_players) >= 2):

        logger.info('Matchmaking two players..')

        # Creating a shortlist of matched players at the moment
        pair = []
        pair.append(running.waiting_players.pop(0))
        pair.append(running.waiting_players.pop(0))

        # Messaging players that a game has been found
        send_message(pair, '找到匹配对局.. 连接中')

        make_game(pair)

    else:
        # 等待人数不足，请耐心等待！
        send_message([request.sid], '请耐心等待匹配另一名玩家..')


def make_game(pair: List[str]):

    shuffle(pair)

    white, black = pair[0], pair[1]

    # Sending over the command codes to initialize game modes on clients
    send_command([white], 'game_mode', {'side': 'white', 'opponent': name_of(black)})
    send_command([black], 'game_mode', {'side': 'black', 'opponent': name_of(white)})

    # running the game
    the_game = Game(pair, 20, 5)
    running.games.append(the_game)

    logger.info(f'Hosted a game. ID = {the_game.game_id}')


def find_game(sid: str) -> Optional[Game]:
    for game in running.games:
        if sid in game.players:
            return game

    return None


if __name__ == '__main__':
    logger.info('Starting server...')
    socketio.run(app)
