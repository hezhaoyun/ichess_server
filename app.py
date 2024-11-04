import logging
import time
from datetime import datetime
from random import shuffle

import chess
from flask import Flask, request
from flask_socketio import SocketIO, emit, send

from logger import get_logger

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chessroad-upup'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

logger = get_logger()


class running:
    players = []  # list of all players connected
    waiting_players = []  # list of players waiting to be matched
    games = []  # list of all games


class Game:

    def __init__(self, pair, total_time, step_increment_time):

        self.players = pair
        self.player1 = self.players[0]
        self.player2 = self.players[1]
        self.game_id = hash(self.player1) + hash(self.player2)

        self.game_times = [total_time, total_time]
        self.step_increment_time = step_increment_time

        self.start_time = None

        self.player_turn = 0
        self.this_turn_move_made = False

        self.board = chess.Board()
        self.is_game_over = False

        self.first_turn()

    def opponent_of(self, player):
        return self.players[(self.players.index(player) + 1) % 2]

    def update_timer(self):
        # Calculate elapsed time based on current time and subtract it from current player's remaining time
        current_time = time.time()
        elapsed = current_time - self.start_time
        self.game_times[self.player_turn] -= elapsed
        self.start_time = current_time

    def get_timer(self, request_player):

        self.update_timer()

        # if the request player is the one that should make a move, return the current player's timer

        request_user_is_current = (request_player == self.players[self.player_turn])
        current = 'mine' if request_user_is_current else 'opponent'
        opponent = 'opponent' if request_user_is_current else 'mine'

        return {
            current: int(self.game_times[self.player_turn]),
            opponent: int(self.game_times[(self.player_turn + 1) % 2]),
        }

    def first_turn(self):

        self.player_turn = 0  # index of player that is ought to make a move
        self.last_player = 1  # index of a player that made move last time

        self.new_board_state()

        send_command([self.players[self.player_turn]], 'go', {})

        self.start_time = time.time()

        logger.info(f'Waiting for a move from player, game ID = {self.game_id}')

    def new_board_state(self):
        # This send_to out the board state to both players
        send_message(self.players, f'\n{str(self.board)}')
        logger.info(f'GAME STATUS. ID = {self.game_id}')
        logger.info(self.board)

    def after_move(self):
        # Verify if both players are still connected
        if (self.is_player_connected(self.player1) and self.is_player_connected(self.player2)):
            # draw conditions
            if not (self.board.is_stalemate()):
                if not (self.board.is_insufficient_material()):
                    # has the game been won
                    if not (self.board.is_checkmate()):
                        if not (self.is_game_over):
                            # WE GET TO PLAY, HURRAY
                            # sending board state to players
                            self.new_board_state()

                            # changing turns
                            self.this_turn_move_made = False
                            self.player_turn = (self.player_turn + 1) % 2
                            self.last_player = (self.last_player + 1) % 2

                            # message next player of his turn
                            send_command(
                                [self.players[self.player_turn]],
                                'go',
                                {'last_move': self.board.peek().uci()}
                            )

                            # update timer, and reset the start time for next turn
                            self.update_timer()

                    else:
                        # player who made the last move won
                        self.declare_loser([self.players[self.last_player]], 'Checkmate')
                        self.declare_winner([self.players[self.player_turn]], 'Checkmate')
                else:
                    # is a stalemate due to insufficient material
                    self.draw('Insufficient material')

            else:
                # is a stalemate
                self.draw('Stalemate')

        else:
            # one of the players has disconnected
            # declaring winners
            if not (self.is_player_connected(self.player1)):
                self.declare_winner([self.player2], 'Your opponent has disconnected')
            else:
                self.declare_winner([self.player1], 'Your opponent has disconnected')

    def is_player_connected(self, player):
        if (player in running.players):
            return True
        else:
            self.players.remove(player)
            return False

    def declare_winner(self, players, reason):
        send_command(players, 'win', {'reason': reason})
        self.game_over()

    def declare_loser(self, players, reason):
        send_command(players, 'lost', {'reason': reason})

    def draw(self, reason):
        send_command(self.players, 'draw', {'reason': reason})
        self.game_over()

    def player_disconnected(self, player):
        if (self.player1 == player):
            self.declare_winner([self.player2], 'Your opponent has disconnected')
        elif (self.player2 == player):
            self.declare_winner([self.player1], 'Your opponent has disconnected')

    def game_over(self):

        logger.info(f'The game has ended. ID = {self.game_id}')
        send_command(self.players, 'game_over', {})
        self.is_game_over = True

        # remove the game from games list
        running.games.remove(self)
        logger.info(f'Removed a finished game from games')

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        # add the players to waiting list, maintain numbers and run matchmaking (since we're adding new players)
        for player in self.players:
            send_message(
                [player],
                "You have been put in the matchmaking lobby again."
            )

        # SPECIAL COMMAND CODE to clients
        for player in self.players:
            send_message([player], 'Type in MATCH to be matched again immediately.')
            send_command([player], 'waiting_match', {})

    def on_forfeit(self, player):

        if (player == self.player1):
            self.declare_winner([self.player2], 'The opposite player has forfeited the game')

        else:
            self.declare_winner([self.player1], 'The opposite player has forfeited the game')

    def on_move(self, move, player):
        # processes messages and return True/False depending if it was valid

        if ('move' in move and self.verify_move(move['move'])):
            self.make_move(move['move'])
            self.game_times[self.player_turn] += self.step_increment_time
            return True

        else:
            send_message([player], 'Incorrect command, try again')
            return False

    def verify_move(self, move):
        # verifies moves
        try:
            if (chess.Move.from_uci(move) in self.board.legal_moves):
                return True
            else:
                return False
        except (ValueError, IndexError) as wrong_format_or_illegal_move:
            return False

    def make_move(self, move):
        # Makes the move on the board
        self.board.push_uci(move)
        self.this_turn_move_made = True


@app.route('/')
def index():
    return 'Chess Server is running!'


@socketio.on('connect')
def on_connect():
    # what happens when somebody connects
    logger.info(f'New connection made: {request.sid}')

    running.players.append(request.sid)

    welcome()

    send_message(running.waiting_players, 'New player has connected and wants to play!')

    running.waiting_players.insert(0, request.sid)

    match_making()


@socketio.on('disconnect')
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


@socketio.on('forfeit')
def on_forfeit(_):
    logger.info(f'{request.sid} wants to forfeit.')

    game = find_game(request.sid)
    if game:
        game.on_forfeit(request.sid)

    else:
        logger.info(f'{request.sid} is not in a game.')


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


@socketio.on('timer_check')
def on_timer_check(_):
    game = find_game(request.sid)

    if game:
        timer = game.get_timer(request.sid)

        if timer['mine'] <= 0 and game.players[game.player_turn] == request.sid:
            
            loser, winner = request.sid, game.opponent_of(request.sid)
            
            game.declare_winner([winner], 'Opponent have timed out')
            game.declare_loser([loser], 'You have timed out')
        
        else:
            send_command([request.sid], 'timer', timer)

    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('message')
def on_message(data):
    # we got something from a client
    logger.info(f'{request.sid} sent a message: {data}')


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
    send_command([white], 'game_mode', {'side': 'white'})
    send_command([black], 'game_mode', {'side': 'black'})

    # running the game
    the_game = Game(pair, 180, 5)
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
    # 使用 socketio.emit() 替代 emit()
    for sid in sids:
        emit(event, message, room=sid)


if __name__ == '__main__':
    socketio.run(app)
