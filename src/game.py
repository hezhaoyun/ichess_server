import chess

import src.server as server
from src.logger import logger
from src.server import running


class Game:

    def __init__(self, pair):

        self.players = pair
        self.player1 = self.players[0]
        self.player2 = self.players[1]

        self.game_id = hash(self.player1) + hash(self.player2)

        self.player_turn = 0
        self.this_turn_move_made = False

        self.board = chess.Board()
        self.is_game_over = False

        self.first_turn()

    def first_turn(self):

        self.player_turn = 0  # index of player that is ought to make a move
        self.last_player = 1  # index of a player that made move last time

        self.new_board_state()

        server.send_command([self.players[self.player_turn]], 'go', {})

        logger.info(f'Waiting for a move from player, game ID = {self.game_id}')

    def new_board_state(self):
        # This send_to out the board state to both players
        server.send_message(self.players, f'\n{str(self.board)}')
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
                            server.send_command(
                                [self.players[self.player_turn]],
                                'go',
                                {'last_move': self.board.peek().uci()}
                            )

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
        server.send_command(players, 'win', {'reason': reason})
        self.game_over()

    def declare_loser(self, players, reason):
        server.send_command(players, 'lost', {'reason': reason})

    def draw(self, reason):
        server.send_command(self.players, 'draw', {'reason': reason})
        self.game_over()

    def player_disconnected(self, player):
        if (self.player1 == player):
            self.declare_winner([self.player2], 'Your opponent has disconnected')
        elif (self.player2 == player):
            self.declare_winner([self.player1], 'Your opponent has disconnected')

    def game_over(self):
        logger.info(f'The game has ended. ID = {self.game_id}')
        server.send_command(self.players, 'game_over', {})
        self.is_game_over = True

        # remove the game from games list
        running.games.remove(self)
        logger.info(f'Removed a finished game from games')

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        # add the players to waiting list, maintain numbers and run matchmaking (since we're adding new players)
        for player in self.players:
            server.send_message(
                [player],
                "You have been put in the matchmaking lobby again."
            )

        # SPECIAL COMMAND CODE to clients
        for player in self.players:
            server.send_message([player], 'Type in MATCH to be matched again immediately.')
            server.send_command([player], 'waiting_match', {})

    def on_forfeit(self, player):

        if (player == self.player1):
            self.declare_winner([self.player2], 'The opposite player has forfeited the game')

        else:
            self.declare_winner([self.player1], 'The opposite player has forfeited the game')

    def on_move(self, move, player):
        # processes messages and return True/False depending if it was valid

        if ('move' in move and self.verify_move(move['move'])):
            self.make_move(move['move'])
            return True

        else:
            server.send_message([player], 'Incorrect command, try again')
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
