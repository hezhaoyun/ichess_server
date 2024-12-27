import platform
import threading
import time
from typing import Dict, List

import chess
import chess.engine

from player import level_of, player_of, update_elo_after_game
from share import get_logger, running, send_command, send_message
from stockfish_pool import StockfishPool

STOCKFISH_PATH_LINUX_POPCNT = './stockfish/linux-popcnt'
STOCKFISH_PATH_LINUX_AVX2 = './stockfish/linux-avx2'  # faster than popcnt
STOCKFISH_PATH_MAC_APPLE_SILICON = './stockfish/apple-silicon'


logger = get_logger(__name__)

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


class Game:
    stockfish_pool = StockfishPool(STOCKFISH_PATH, max_size=5)  # Shared pool

    def __init__(self, pair: List[str], total_time: int, step_increment_time: int, bot_sid=None):

        self.players = pair
        self.player1, self.player2 = self.players[0], self.players[1]
        self.game_id = hash(self.player1) + hash(self.player2)

        self.player_times = [total_time, total_time]
        self.step_increment_time = step_increment_time

        self.start_time = None
        self.current_player_index: int = 0

        self.board = chess.Board()
        self.is_game_over = False
        self.game_state = {'draw_proposer': None, 'takeback_proposer': None}

        self.bot_sid = bot_sid
        self.start_game()

    def start_game(self) -> None:

        self.start_time = time.time()
        self.send_board_state()

        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})

        logger.info(f'Waiting for player to make a move, game ID = {self.game_id}')

    def update_timer(self):
        # Calculate elapsed time based on current time and subtract it from current player's remaining time
        current_time = time.time()
        elapsed = current_time - self.start_time
        self.player_times[self.current_player_index] -= elapsed
        self.start_time = current_time

    def send_board_state(self):
        # This sends the board state to both players
        send_message(self.players, f'\n{str(self.board)}')
        logger.info(f'GAME STATUS. ID = {self.game_id}')
        logger.info(self.board)

    def make_bot_move(self) -> None:
        # Get engine
        level = level_of(player_of(self.bot_sid)['elo'])
        engine = Game.stockfish_pool.get_engine(level)

        result = engine.play(self.board, chess.engine.Limit(time=1.0))
        self.on_move({'move': str(result.move)}, self.bot_sid)

        # Return engine after thinking
        Game.stockfish_pool.return_engine(engine)

    def on_move(self, move: Dict[str, str], player: str) -> bool:

        if 'move' in move and self.verify_move(move['move']):

            self.make_move(move['move'], self.opponent_of(player))
            self.player_times[self.current_player_index] += self.step_increment_time

            self.after_move()
            return True

        else:
            send_message([player], f'Command error: {move}, please re-enter.')
            return False

    def verify_move(self, move: str) -> bool:
        try:
            return chess.Move.from_uci(move) in self.board.legal_moves
        except (ValueError, IndexError):
            return False

    def make_move(self, move: str, opponent: str):
        self.board.push_uci(move)
        send_command([opponent], 'move', {'move': self.board.peek().uci()})

    def after_move(self):

        if not self.check_players_connected():
            return self.handle_disconnection()

        if self.check_game_end():
            return

        self.prepare_next_turn()

    def check_players_connected(self) -> bool:
        for player in self.players:
            if not self.is_player_connected(player):
                return False

        return True

    def handle_disconnection(self) -> None:
        disconnected_player = next(
            (player for player in [self.player1, self.player2]
             if not self.is_player_connected(player)),
            None
        )

        if disconnected_player:
            self.player_disconnected(disconnected_player)

    def is_player_connected(self, player: str) -> bool:
        if player in running.online_players or player.startswith('bot_'):
            return True
        else:
            self.players.remove(player)
            return False

    def player_disconnected(self, player: str):
        winner = self.player2 if self.player1 == player else self.player1
        self.declare_winner([winner], 'Opponent has left the game!')
        update_elo_after_game(winner, player, 1)

    def check_game_end(self) -> bool:

        if self.board.is_checkmate():
            self.handle_checkmate()
            return True

        if self.board.is_stalemate():
            self.draw('Stalemate!')
            update_elo_after_game(self.player1, self.player2, 0.5)
            return True

        if self.board.is_insufficient_material():
            self.draw('Insufficient material!')
            update_elo_after_game(self.player1, self.player2, 0.5)
            return True

        return False

    def prepare_next_turn(self) -> None:

        self.send_board_state()
        self.current_player_index = (self.current_player_index + 1) % 2

        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})

        self.update_timer()

    def game_over(self):
        logger.info(f'The game has ended. ID = {self.game_id}')
        send_command(self.players, 'game_over', {})

        self.is_game_over = True
        running.games.remove(self)

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        for player in self.players:
            send_message([player], 'Tap MATCH to match immediately.')
            send_command([player], 'waiting_match', {})

    def declare_winner(self, players: List[str], reason: str):
        send_command(players, 'win', {'reason': reason})
        self.game_over()

    def declare_loser(self, players: List[str], reason: str):
        send_command(players, 'lost', {'reason': reason})

    def draw(self, reason: str):
        send_command(self.players, 'draw', {'reason': reason})
        self.game_over()

    def handle_checkmate(self) -> None:
        winner = self.players[self.current_player_index]
        loser = self.opponent_of(winner)

        self.declare_winner([winner], 'Checkmate!')
        self.declare_loser([loser], 'You have been checkmated!')

        update_elo_after_game(winner, loser, 1)

    def on_resign(self, player: str):
        if player == self.player1:
            self.declare_winner([self.player2], 'Opponent resigned!')
            update_elo_after_game(self.player2, self.player1, 1)

        else:
            self.declare_winner([self.player1], 'Opponent resigned!')
            update_elo_after_game(self.player1, self.player2, 1)

    def on_draw_proposal(self, proposer: str) -> bool:

        if self.game_state['draw_proposer'] is None:

            self.game_state['draw_proposer'] = proposer
            opponent = self.opponent_of(proposer)

            if self.bot_sid and opponent == self.bot_sid:
                running.socketio.sleep(1)
                self.on_draw_response(self.bot_sid, True)
                return True

            send_command([opponent], 'draw_request', {
                'message': 'Opponent proposes a draw, do you accept?'
            })

            return True

        return False

    def on_draw_response(self, responder: str, accepted: bool) -> bool:

        if self.game_state['draw_proposer'] and responder == self.opponent_of(self.game_state['draw_proposer']):

            if accepted:
                self.draw('Draw agreed!')
                update_elo_after_game(self.player1, self.player2, 0.5)

            else:
                send_command([self.game_state['draw_proposer']], 'draw_declined', {})

            self.game_state['draw_proposer'] = None

            return True

        return False

    def on_takeback_proposal(self, proposer: str) -> bool:

        if self.game_state['takeback_proposer'] is None and len(self.board.move_stack) > 0:

            self.game_state['takeback_proposer'] = proposer
            opponent = self.opponent_of(proposer)

            if self.bot_sid and opponent == self.bot_sid:
                running.socketio.sleep(1)
                self.on_takeback_response(self.bot_sid, True)
                return True

            send_command([opponent], 'takeback_request', {
                'message': 'Opponent requests a takeback, do you accept?'
            })

            return True

        return False

    def on_takeback_response(self, responder: str, accepted: bool) -> bool:

        if self.game_state['takeback_proposer'] and responder == self.opponent_of(self.game_state['takeback_proposer']):

            if accepted:

                # Check if there are at least two moves to take back
                if len(self.board.move_stack) >= 2:
                    # Take back the last two moves of both players
                    _ = self.board.pop()  # Take back opponent's move
                    _ = self.board.pop()  # Take back own move

                    # Restore time (subtract increment time for both)
                    self.player_times[0] -= self.step_increment_time
                    self.player_times[1] -= self.step_increment_time
                    self.start_time = time.time()

                    # It's the turn of the player who initiated the takeback
                    self.current_player_index = self.players.index(self.game_state['takeback_proposer'])

                    # Notify both players
                    send_command(self.players, 'takeback_success', {})

                    self.send_board_state()
                    send_command([self.players[self.current_player_index]], 'go', {})

                else:
                    # Not enough moves, decline takeback
                    send_command([self.game_state['takeback_proposer']], 'takeback_declined', {
                        'reason': 'Not enough moves to take back!'
                    })

            else:
                send_command([self.game_state['takeback_proposer']], 'takeback_declined', {})

            self.game_state['takeback_proposer'] = None

            return True

        return False

    def opponent_of(self, player: str) -> str:
        return self.player2 if player == self.player1 else self.player1
