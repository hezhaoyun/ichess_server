from datetime import datetime

from flask import request
from flask_socketio import send


class running:
    connected_players = 0  # number of connected players overall
    playing_players = 0  # players currently in games
    match_making_players = 0  # players waiting to be matched for a game

    clients_list = []  # list of all players connected
    waiting_list = []  # list of players waiting to be matched

    games_list = []  # list of all games
    playing_list = [[]]  # list of all players playing in games with ids of games they are in


def on_connect():

    # what happens when somebody connects
    print(datetime.now().strftime("%H:%M") + " New connection made")

    running.clients_list.append(request.sid)
    running.connected_players = running.connected_players + 1
    running.match_making_players = running.match_making_players + 1

    welcome()
    
    send_to(running.waiting_list, "New player has connected and wants to play!")

    running.waiting_list.insert(0, request.sid)
    match_making()


def on_disconnect():

    # Maintaining numbers and lists of ALL connected players
    running.connected_players = running.connected_players - 1
    running.clients_list.remove(request.sid)

    # Disconnected player was in a waiting list
    if request.sid in running.waiting_list:
        running.waiting_list.remove(request.sid)
        running.match_making_players = running.match_making_players - 1

    # Disconnected player was in a game, checking
    for player_and_game in running.playing_list:

        if request.sid in player_and_game:

            print("Player in a chess game has disconnected")

            gameid = player_and_game[1]
            the_game = running.games_list[gameid]

            # inform the game
            the_game.player_disconnected(request.sid)

            # if player is still on the list
            try:
                running.playing_list.remove([request.sid, gameid])
            except ValueError:
                # player was already removed
                pass

    print("Connection Lost and handled by the server")


def on_message(line):

    # we got something from a client
    print(datetime.now().strftime("%H:%M ") + f"Received a message: {line}")

    # is the client playing in a game
    if (any(request.sid in sublist for sublist in running.playing_list)):

        # find the game's id
        for player_and_game in running.playing_list:
            if (request.sid in player_and_game):
                gameid = player_and_game[1]
                the_game = running.games_list[gameid]

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
    elif (line == "MATCH") and not (request.sid in running.waiting_list):
        running.waiting_list.append(request.sid)
        running.match_making_players = running.match_making_players + 1
        match_making()


def send_to(list_of_users, text):
    # message privately everyone on the list
    for c in list_of_users:
        send(text, to=c)


def welcome():
    # a bunch of on-login messages
    send("Welcome to Chessroad.")
    send("Server time: " + datetime.now().strftime("%H:%M"))
    send("Connected players: " + str(running.connected_players))
    send("Available players for matchmaking: " + str(running.match_making_players))


def match_making():
    # Find two players on a waiting list and make them play
    # Is there enough players in waiting queue
    if (running.match_making_players >= 2):
        print(datetime.now().strftime("%H:%M") + " Matchmaking two players..")

        # Creating a shortlist of matched players at the moment
        two_players = []
        two_players.append(running.waiting_list.pop(0))
        two_players.append(running.waiting_list.pop(0))

        # Maintaining numbers of players
        running.match_making_players = running.match_making_players - 2

        # Messaging players that a game has been found
        send_to(two_players, "Found a pair.. Connecting")

        make_game(two_players)

    else:
        # Not enough players, you have to wait!
        send("Please wait to be matched with another player")


def make_game(two_players):
    
    # Makes the game given list of any free two players

    # Maintaining numbers
    running.playing_players = running.playing_players + 2

    # Sending over the command codes to initialize game modes on clients
    send_to(two_players, "GAMEMODE")

    # Server logs and figuring out game's id
    idnumber = len(running.games_list)
    print(datetime.now().strftime("%H:%M") + " Hosted a game. ID = " + str(idnumber))

    # Adding players to playing players list with the game's id
    running.playing_list.append([two_players[0], idnumber])
    running.playing_list.append([two_players[1], idnumber])

    # running the game
    import src.game as game
    running.games_list.append(game.Game(request.sid, two_players, idnumber))
