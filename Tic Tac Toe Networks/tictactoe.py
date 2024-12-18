import game


def tic_tac_toe() -> None:
    # Modify this function in any way you like
    board = game.create_board()
    player = game.CROSS

    game_won = game_drawn = False
    while not game_won and not game_drawn:
        game.print_board(board)
        print()
        # turn = "Noughts'" if player == game.NOUGHT else "Crosses'"
        # print(turn, "turn")

        position = game.player_turn(player, board)
        # Implement any relevant logic here for sending the position/board
        print()

        if game.player_wins(player, board):
            game_won = True
        elif game.players_draw(board):
            game_drawn = True
        else:
            player = game.NOUGHT if player == game.CROSS else game.CROSS

    game.print_board(board)
    print()

    if game_won:
        pass
        # winner = "Noughts" if player == game.NOUGHT else "Crosses"
        # print(winner, "wins!")
    elif game_drawn:
        print("Draw!")

tic_tac_toe()
