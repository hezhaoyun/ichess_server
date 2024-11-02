from datetime import datetime
from random import shuffle

from flask import request
from flask_socketio import emit, send

from src.logger import logger


class running:
    players = []  # list of all players connected
    waiting_players = []  # list of players waiting to be matched
    games = []  # list of all games


def on_connect():

    # what happens when somebody connects
    logger.info(f'New connection made: {request.sid}')

    running.players.append(request.sid)

    welcome()

    send_message(running.waiting_players, 'New player has connected and wants to play!')

    running.waiting_players.insert(0, request.sid)

    match_making()


def on_disconnect():

    # Maintaining numbers and lists of ALL connected players
    running.players.remove(request.sid)

    # Disconnected player was in a waiting list
    if request.sid in running.waiting_players:
        running.waiting_players.remove(request.sid)

    # Disconnected player was in a game, checking
    for game in running.games:
        if request.sid in game.players:
            logger.info('Player in a chess game has disconnected')
            game.player_disconnected(request.sid)

    logger.info('Connection Lost and handled by the server')


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


def on_forfeit(_):
    logger.info(f'{request.sid} wants to forfeit.')

    game = find_game(request.sid)
    if game:
        game.on_forfeit(request.sid)

    else:
        logger.info(f'{request.sid} is not in a game.')


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


def on_message(line):
    # we got something from a client
    logger.info(f'{request.sid} sent a message: {line}')


def welcome():
    # a bunch of on-login messages
    send('Welcome to Chessroad.')
    send(f"Server time: {datetime.now().strftime('%H:%M')}")
    send(f'Connected players: {len(running.players)}')
    send(f'Available players for matchmaking: {len(running.waiting_players) + 1}')


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
        send_message(pair, 'Found a pair.. Connecting')

        make_game(pair)

    else:
        # Not enough players, you have to wait!
        send('Please wait to be matched with another player')


def make_game(pair):

    shuffle(pair)
    
    white, black = pair[0], pair[1]

    # Sending over the command codes to initialize game modes on clients
    send_command([white], 'GAME_MODE', {'side': 'white'})
    send_command([black], 'GAME_MODE', {'side': 'black'})

    # running the game
    import src.game as game
    the_game = game.Game(pair)
    running.games.append(the_game)

    logger.info(f'Hosted a game. ID = {the_game.game_id}')


def find_game(sid):
    for game in running.games:
        if sid in game.players:
            return game

    return None


def send_message(sids, message):
    # message privately everyone on the list
    for sid in sids:
        send(message, to=sid)


def send_command(sids: list[str], event: str, message: dict):
    # message privately everyone on the list
    for sid in sids:
        emit(event, message, to=sid)


