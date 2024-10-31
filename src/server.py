from datetime import datetime

from flask import request
from flask_socketio import send


class running:
    players = []  # list of all players connected
    waiting_players = []  # list of players waiting to be matched

    games = []  # list of all games
    playing_games = [[]]  # list of all players playing in games with ids of games they are in


def on_connect():

    # what happens when somebody connects
    print(datetime.now().strftime("%H:%M") + " New connection made")

    running.players.append(request.sid)

    welcome()
    
    send_to(running.waiting_players, "New player has connected and wants to play!")

    running.waiting_players.insert(0, request.sid)
    
    match_making()


def on_disconnect():

    # Maintaining numbers and lists of ALL connected players
    running.players.remove(request.sid)

    # Disconnected player was in a waiting list
    if request.sid in running.waiting_players:
        running.waiting_players.remove(request.sid)

    # Disconnected player was in a game, checking
    for player_and_game in running.playing_games:

        if request.sid in player_and_game:

            print("Player in a chess game has disconnected")

            game_id = player_and_game[1]
            the_game = running.games[game_id]

            # inform the game
            the_game.player_disconnected(request.sid)

            # if player is still on the list
            try:
                running.playing_games.remove([request.sid, game_id])
            except ValueError:
                # player was already removed
                pass

    print("Connection Lost and handled by the server")


def on_message(line):

    # we got something from a client
    print(datetime.now().strftime("%H:%M ") + f"Received a message: {line}")

    # is the client playing in a game
    if (any(request.sid in sublist for sublist in running.playing_games)):

        # find the game's id
        for player_and_game in running.playing_games:
            if (request.sid in player_and_game):
                game_id = player_and_game[1]
                the_game = running.games[game_id]

        # is it the player's turn and the game hasn't ended
        if (request.sid == the_game.players[the_game.player_turn] and (the_game.is_gameover == False)):
            # was the message legit
            if (the_game.get_message(line, request.sid)):
                print(datetime.now().strftime("%H:%M") + " Legit command was received and processed")
                # Engange the next turn function
                the_game.after_move()

            else:
                # the message was somehow incorrect, sending special client side code to try again
                list = []
                list.append(request.sid)
                send_to(list, "TRYAGAIN")

    # the client is in the lobby but after having played the game
    elif (line == "MATCH") and not (request.sid in running.waiting_players):
        running.waiting_players.append(request.sid)
        match_making()


def send_to(list_of_users, text):
    # message privately everyone on the list
    for c in list_of_users:
        send(text, to=c)


def welcome():
    # a bunch of on-login messages
    send("Welcome to Chessroad.")
    send("Server time: " + datetime.now().strftime("%H:%M"))
    send("Connected players: " + str(len(running.players)))
    send("Available players for matchmaking: " + str(len(running.waiting_players) + 1))


def match_making():
    # Find two players on a waiting list and make them play
    # Is there enough players in waiting queue
    if (len(running.waiting_players) >= 2):
        print(datetime.now().strftime("%H:%M") + " Matchmaking two players..")

        # Creating a shortlist of matched players at the moment
        two_players = []
        two_players.append(running.waiting_players.pop(0))
        two_players.append(running.waiting_players.pop(0))

        # Messaging players that a game has been found
        send_to(two_players, "Found a pair.. Connecting")

        make_game(two_players)

    else:
        # Not enough players, you have to wait!
        send("Please wait to be matched with another player")


def make_game(two_players):
    
    # Makes the game given list of any free two players

    # Sending over the command codes to initialize game modes on clients
    send_to(two_players, "GAMEMODE")

    # Server logs and figuring out game's id
    next_game_id = len(running.games)
    print(datetime.now().strftime("%H:%M") + " Hosted a game. ID = " + str(next_game_id))

    # Adding players to playing players list with the game's id
    running.playing_games.append([two_players[0], next_game_id])
    running.playing_games.append([two_players[1], next_game_id])

    # running the game
    import src.game as game
    running.games.append(game.Game(request.sid, two_players, next_game_id))
