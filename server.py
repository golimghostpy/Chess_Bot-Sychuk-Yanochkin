import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from random import randint
from Chess_Classes import *
from PIL import Image
import sqlite3

TOKEN = 'vk1.a.qOQPyAdJ_Z5WwjzbNl_WFUq2P05QGpwj-537I7vwLTneH1Fz06BBEslq0_rbUGJFabRakR9V-pL7dzhhx6qCeHA-AP2wNndJTFHYQ7sKmPyiAB05KWIkfmH4G_Gl9luw3qqe8UvwB6tTTaojNW1EcIHjgP8uX5Z89ppE5Mv2cpaWrEmrWtD9b9GC1ulJ_viLiTwOfjTcBd4mqifQqazVZw'
GROUP_ID = 219645807


# функция, которая преобразовывает координаты формата e2 в пару координат (1, 4)
def to_cords(loc):
    try:
        if len(loc) != 2:
            return False
        row, col = int(loc[1]) - 1, ord(loc[0].lower()) - ord('a')
        if row not in range(8) or col not in range(8):
            return False
        return row, col
    except Exception:
        return False


# сборка цельного поля из множества маленьких картинок
def build_field_img(field, player):
    img = Image.new('RGB', (680, 680))
    if player:
        for i in range(8):
            for j in range(8):
                figure = Image.open(f"data/figures/{repr(field[i][j])}{(i + j) % 2}.png")
                img.paste(figure, (80 * (7 - j), 80 * (7 - i)))
    else:
        for i in range(8):
            for j in range(8):
                figure = Image.open(f"data/figures/{repr(field[i][j])}{(i + j) % 2}.png")
                img.paste(figure, (80 * j, 80 * i))
    img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if player:
        img.paste(Image.open('data/num_for_white.png'), (0, 0))
        img.paste(Image.open('data/let_for_white.png'), (40, 640))
    else:
        img.paste(Image.open('data/num_for_black.png'), (0, 0))
        img.paste(Image.open('data/let_for_black.png'), (40, 640))
    img.save('data/field.png')


# поле из элемента класса ChessField превращается в форматную строку для БД
def field_to_str(field):
    ans = f'{field.step};'
    for i in range(8):
        for j in range(8):
            ans += repr(field.field[i][j]) + ';'
    return ans[:-1]


# поле из БД превращается в элемент класса ChessField
def str_to_field(string):
    game = ChessField()
    figures = string.split(';')
    game.step = int(figures.pop(0))
    for i in range(8):
        for j in range(8):
            if 'None' not in figures[i * 8 + j]:
                figure_classes[figures[i * 8 + j][:-1]](i, j, int(figures[i * 8 + j][-1]), game).put()
    return game


# преобразование текста из файлов описания команд в одну строку для отправки
def txt_to_str(filename):
    with open(filename) as f:
        return ''.join(f.readlines())


# состояния игроков
NO_ENEMY, WAITING_FOR_ACCEPT, FIGHTING = 0, 1, 2


# класс игрока
class Player:
    def __init__(self):
        self.color = 1  # цвет игрока
        self.edit_field = None  # редактируемое поле
        self.game_field = None  # игровое поле
        self.enemy = None  # текущий противник(id)
        self.condition = NO_ENEMY  # состояние игрока
        self.waiting = set()  # очередь запросов
        self.bet = False  # будет ли сражение рейтинговым


# класс бота
class Bot:
    def __init__(self):
        self.session = vk_api.VkApi(token=TOKEN)
        self.long_poll = None
        self.players = dict()  # словарь игроков

    # отправка текстового сообщения пользователю, принимает id и сообщение
    def send_message(self, user, message):
        self.session.get_api().messages.send(user_id=user, message=message, random_id=randint(0, 2 ** 64))

    # запуск бота
    def start(self):
        self.long_poll = VkBotLongPoll(self.session, GROUP_ID)

    # постоянно ждет новых сообщений
    def main_cycle(self):
        print('--------------------------------------------')
        for event in self.long_poll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                self.process_command(event.object.message["from_id"], event.object.message["text"])
                print(f'sender: {event.object.message["from_id"]}')
                print(f'text: {event.object.message["text"]}')
                print('--------------------------------------------')

    # функция для отправки изображения поля
    def send_field(self, user, color, message, field=False):
        if field:
            send = field
        else:
            if self.players[user].condition == NO_ENEMY:
                send = self.players[user].edit_field.field
            else:
                send = self.players[user].game_field.field
        build_field_img(send, color)
        vk = self.session.get_api()
        upload = vk_api.VkUpload(vk)
        vk_image = upload.photo_messages('data/field.png')
        owner_id = vk_image[0]['owner_id']
        photo_id = vk_image[0]['id']
        access_key = vk_image[0]['access_key']
        attachment = f'photo{owner_id}_{photo_id}_{access_key}'
        vk.messages.send(user_id=user, peer_id=user, random_id=0, attachment=attachment, message=message)

    # функция окнчания игры
    def end_check(self, user):
        if self.players[user].game_field.end:
            self.send_message(user, 'you\'ve won, game is finished')
            self.send_message(self.players[user].enemy, 'you\'ve lost, game is finished')
            # если игра рейтинговая, то рейтинг игроков в БД изменится
            con = sqlite3.connect('data.db')
            cur = con.cursor()
            los = \
                [x[0] for x in
                 cur.execute("""SELECT losses FROM top WHERE user_id = ?""", (self.players[user].enemy,))][0]
            win = [x[0] for x in cur.execute("""SELECT wins FROM top WHERE user_id = ?""", (user,))][0]
            cur.execute("""UPDATE top SET losses = ? WHERE user_id = ?""", (los + 1, self.players[user].enemy))
            cur.execute("""UPDATE top SET wins = ? WHERE user_id = ?""", (win + 1, user))
            if self.players[user].bet:
                rating = [x[0] for x in cur.execute("""SELECT rating FROM top WHERE user_id = ?""", (user,))][0]
                cur.execute("""UPDATE top SET rating = ? WHERE user_id = ?""", (rating + 1, user))
                self.send_message(user, f'your rating now is {rating + 1}')
                rating = [x[0] for x in
                          cur.execute("""SELECT rating FROM top WHERE user_id = ?""", (self.players[user].enemy,))][0]
                cur.execute("""UPDATE top SET rating = ? WHERE user_id = ?""",
                            (rating - 1 if rating > 0 else 0, self.players[user].enemy))
                self.send_message(self.players[user].enemy, f'your rating now is {rating - 1 if rating > 0 else 0}')
            con.commit()
            # менятеся состояние, исчезают противник, игровое поле и ставка
            self.players[user].condition = NO_ENEMY
            self.players[self.players[user].enemy].condition = NO_ENEMY
            self.players[self.players[user].enemy].bet = False
            self.players[user].bet = False
            self.players[user].game_field = None
            self.players[self.players[user].enemy].game_field = None
            self.players[self.players[user].enemy].enemy = None
            self.players[user].enemy = None
            return True
        return False

    # функция постановки фигуры на редактируемое поле
    def process_put(self, user, command):
        if len(command) != 4:
            self.send_message(user, 'wrong command structure\ntype "/help put" for more information')
            return
        if self.players[user].condition != NO_ENEMY:
            self.send_message(user, 'too late for any customisation')
            return
        if self.players[user].edit_field is None:
            self.send_message(user, 'create field with "/field create" first')
            return
        try:
            figure = figure_classes[command[1].lower().capitalize()]
        except KeyError:
            self.send_message(user, 'wrong command arguments\ntype "/help put" for more information')
            return
        if to_cords(command[2]):
            row, col = to_cords(command[2])
        else:
            self.send_message(user, 'wrong command arguments\ntype "/help put" for more information')
            return
        try:
            color = colors[command[3].lower()]
            self.players[user].edit_field.put_figure(figure, row, col, color)
            self.send_field(user, self.players[user].color, 'figure put successfully')
        except Exception:
            self.send_message(user, 'wrong command arguments\ntype "/help put" for more information')

    # функция удаления фигуры с редактируемого поля
    def process_remove(self, user, command):
        if len(command) != 2:
            self.send_message(user, 'wrong command structure\ntype "/help remove" for more information')
            return
        if self.players[user].condition != NO_ENEMY:
            self.send_message(user, 'too late for any customisation')
            return
        if self.players[user].edit_field is None:
            self.send_message(user, 'create field with "/field create" first')
            return
        if to_cords(command[1]):
            row, col = to_cords(command[1])
            if not self.players[user].edit_field.field[row][col]:
                self.send_message(user, 'nothing to remove')
                return
            self.players[user].edit_field.field[row][col].die()
            self.send_field(user, self.players[user].color, 'figure removed successfully')
        else:
            self.send_message(user, 'wrong command arguments\ntype "/help remove" for more information')

    # установка цвета
    def process_set(self, user, command):
        if len(command) != 3:
            self.send_message(user, 'wrong command structure\ntype "/help set" for more information')
            return
        if self.players[user].condition != NO_ENEMY:
            self.send_message(user, 'too late for any customisation')
            return
        if self.players[user].edit_field is None:
            self.send_message(user, 'create field with "/field create" first')
            return
        # цвет, за который будет играть тот, кто отправляет запрос
        if command[1] == 'color':
            if command[2] == 'random':
                self.players[user].color = randint(0, 1)
                self.send_message(user, 'user color set successfully')
                return
            try:
                self.players[user].color = colors[command[2]]
                self.send_message(user, 'user color set successfully')
            except KeyError:
                self.send_message(user, 'wrong command arguments\ntype "/help set" for more information')
                return
        #  цвет того, кто будет ходить первым
        elif command[1] == 'first':
            if command[2] == 'random':
                self.players[user].edit_field.step = randint(0, 1)
                self.send_message(user, 'first step set successfully')
                return
            try:
                self.players[user].edit_field.step = colors[command[2]]
                self.send_message(user, 'first step set successfully')
            except KeyError:
                self.send_message(user, 'wrong command arguments\ntype "/help set" for more information')
                return
        else:
            self.send_message(user, 'wrong command arguments\ntype "/help set" for more information')

    # функция организации поединков между игроками
    def process_challenge(self, user, command):
        if len(command) != 3:
            self.send_message(user, 'wrong command structure\ntype "/help challenge" for more information')
            return
        #  вызвать на поединок
        if command[1] == 'offer':
            if str(user) == command[2]:
                self.send_message(user, 'you can\'t challenge yourself')
                return
            if self.players[user].condition != NO_ENEMY:
                self.send_message(user, 'end your previous conflict first')
                return
            if self.players[user].edit_field is None:
                self.players[user].game_field = ChessField()
                self.players[user].game_field.build()
            else:
                self.players[user].game_field = self.players[user].edit_field.copy()
            if self.players[user].game_field.rigged():
                self.send_message(user, 'unavailable field to play')
                return
            try:
                if int(command[2]) not in self.players:
                    self.players[int(command[2])] = Player()
                self.send_field(int(command[2]), 1 - self.players[user].color,
                                f'you have been challenged by {user}\ntype "/challenge accept {user}" to accept challenge\nelse type "/challenge deny {user}"',
                                self.players[user].game_field.field)
                self.send_message(user, 'waiting for player reply...')
                self.players[user].condition = WAITING_FOR_ACCEPT
                self.players[user].enemy = int(command[2])
                self.players[int(command[2])].waiting.add(user)
            except ValueError:
                self.send_message(user,
                                  'this user hasn\'t started dialog with bot yet or does not exist at all\ntype "/help challenge" for more information')
        # отменить свой вызов
        elif command[1] == 'cancel':
            if self.players[user].condition == NO_ENEMY:
                self.send_message(user, 'no challenge offered to any user right now')
                return
            if self.players[user].condition == FIGHTING:
                self.send_message(user, 'too late to cancel challenge')
                return
            if self.players[user].enemy != int(command[2]):
                self.send_message(user, 'you didn\'t challenge this player')
                return
            self.send_message(int(command[2]), f'{user} canceled his offer')
            self.send_message(user, 'challenge cancelled successfully')
            self.players[user].enemy = None
            self.players[int(command[2])].waiting.remove(user)
            self.players[user].condition = NO_ENEMY
        # принять вызов
        elif command[1] == 'accept':
            if self.players[user].condition == FIGHTING:
                self.send_message(user, 'you can\'t accept challenge while having another fight')
                return
            if int(command[2]) not in self.players[user].waiting:
                self.send_message(user, 'this player didn\'t challenge you')
                return
            self.players[user].condition = FIGHTING
            self.players[int(command[2])].condition = FIGHTING
            self.players[user].enemy = int(command[2])
            self.players[user].waiting.remove(int(command[2]))
            self.players[user].game_field = self.players[int(command[2])].game_field
            self.players[user].color = 1 - self.players[int(command[2])].color
            if self.players[user].game_field.is_basic():
                self.players[user].bet = True
                self.players[int(command[2])].bet = True
            self.send_message(user, 'challenge accepted successfully')
            self.send_message(int(command[2]), 'you challenge has been accepted')
        # отклонить вызов
        elif command[1] == 'deny':
            try:
                if int(command[2]) not in self.players[user].waiting:
                    self.send_message(user, 'this player didn\'t challenge you')
                    return
            except Exception:
                self.send_message(user, 'this player didn\'t challenge you')
                return
            self.players[user].waiting.remove(int(command[2]))
            self.players[int(command[2])].enemy = None
            self.players[int(command[2])].condition = NO_ENEMY
            self.send_message(user, 'challenge denied successfully')
            self.send_message(int(command[2]), 'you challenge has been denied')
        else:
            self.send_message(user, 'wrong command arguments\ntype "/help challenge" for more information')

    # сдаться
    def process_surrender(self, user, command):
        if len(command) != 1:
            self.send_message(user, 'wrong command structure\ntype "/help surrender" for more information')
            return
        if self.players[user].condition != FIGHTING:
            self.send_message(user, 'you\'re not fighting right now')
            return
        vk = self.session.get_api()
        upload = vk_api.VkUpload(vk)
        vk_image = upload.photo_messages('data/fool.png')
        owner_id = vk_image[0]['owner_id']
        photo_id = vk_image[0]['id']
        access_key = vk_image[0]['access_key']
        attachment = f'photo{owner_id}_{photo_id}_{access_key}'
        vk.messages.send(user_id=user, peer_id=user, random_id=0, attachment=attachment, message="you\'ve surrendered")
        self.send_message(self.players[user].enemy, 'your enemy have surrendered')
        con = sqlite3.connect('data.db')
        cur = con.cursor()
        win = [x[0] for x in cur.execute("""SELECT wins FROM top WHERE user_id = ?""", (self.players[user].enemy,))][0]
        los = [x[0] for x in cur.execute("""SELECT losses FROM top WHERE user_id = ?""", (user,))][0]
        cur.execute("""UPDATE top SET wins = ? WHERE user_id = ?""", (win + 1, self.players[user].enemy))
        cur.execute("""UPDATE top SET losses = ? WHERE user_id = ?""", (los + 1, user))
        if self.players[user].bet:
            rating = \
                [x[0] for x in
                 cur.execute("""SELECT rating FROM top WHERE user_id = ?""", (self.players[user].enemy,))][0]
            cur.execute("""UPDATE top SET rating = ? WHERE user_id = ?""", (rating + 1, self.players[user].enemy))
            self.send_message(self.players[user].enemy, f'your rating now is {rating + 1}')
            rating = [x[0] for x in cur.execute("""SELECT rating FROM top WHERE user_id = ?""", (user,))][0]
            cur.execute("""UPDATE top SET rating = ? WHERE user_id = ?""",
                        (rating - 1 if rating > 0 else 0, user))
            self.send_message(user, f'your rating now is {rating - 1 if rating > 0 else 0}')
        con.commit()
        self.players[user].condition = NO_ENEMY
        self.players[self.players[user].enemy].condition = NO_ENEMY
        self.players[self.players[user].enemy].bet = False
        self.players[user].bet = False
        self.players[user].game_field = None
        self.players[self.players[user].enemy].game_field = None
        self.players[self.players[user].enemy].enemy = None
        self.players[user].enemy = None

    # функция, котороя отвечает за действия производимые с полем
    def process_field(self, user, command):
        if len(command) == 2:
            if self.players[user].condition != NO_ENEMY:
                self.send_message(user, 'too late for any field customisation')
                return
            # удалить редактируемое поле
            if command[1] == 'delete':
                if self.players[user].edit_field:
                    self.players[user].edit_field = None
                    self.players[user].color = 1
                    self.send_message(user, 'field deleted successfully')
                else:
                    self.send_message(user, 'no field to delete')
            # очитстить редактируемое поле
            elif command[1] == 'clear':
                self.players[user].edit_field.made_in_heaven()
                self.send_message(user, 'field cleared successfully')
            else:
                self.send_message(user, 'wrong command arguments\ntype "/help field" for more information')
        elif len(command) == 3:
            if self.players[user].condition != NO_ENEMY:
                self.send_message(user, 'too late for any field customisation')
                return
            # сохранить кастомное поле в БД
            if command[1] == 'save':
                field_name = command[2]
                field = field_to_str(self.players[user].edit_field)
                try:
                    con = sqlite3.connect('data.db')
                    cur = con.cursor()
                    cur.execute('INSERT INTO data(title, user, field) VALUES(?, ?, ?)', (field_name, user, field))
                    con.commit()
                    self.send_message(user, 'field saved successfully')
                except Exception:
                    self.send_message(user, 'this name has already used, please try another one')
            # создать новое поле для редактирования
            elif command[1] == 'create':
                if self.players[user].edit_field:
                    self.send_message(user,
                                      'field already exists\ndelete previous field with "/field delete" first to create new one')
                else:
                    # создать пустое поле
                    if command[2] == 'empty':
                        self.players[user].edit_field = ChessField()
                        self.send_field(user, self.players[user].color,
                                        'field created successfully\n"/field save" to save your field')
                    # создать базовое поле
                    elif command[2] == 'basic':
                        self.players[user].edit_field = ChessField()
                        self.players[user].edit_field.build()
                        self.send_field(user, self.players[user].color,
                                        'field created successfully\n"/field save" to save your field')
                    else:
                        self.send_message(user, 'wrong command arguments\ntype "/help field" for more information')
            # загрузить поле из БД
            elif command[1] == 'load':
                try:
                    con = sqlite3.connect('data.db')
                    cur = con.cursor()
                    field = [x[0] for x in cur.execute("""SELECT field FROM data WHERE title = ?""", (command[2],))][0]
                    self.players[user].edit_field = str_to_field(field)
                    self.send_field(user, self.players[user].color, 'field loaded successfully')
                except Exception:
                    self.send_message(user, 'field with this name doesn\'t exist')
            # посмотреть список названий полей, сохраненных в БД
            elif command[1] == 'list':
                con = sqlite3.connect('data.db')
                cur = con.cursor()
                #  посмотреть все названия
                if command[2] == 'all':
                    fields_names = [x[0] for x in cur.execute("""SELECT title FROM data""")]
                # посмотреть только свои поля
                else:
                    fields_names = [x[0] for x in cur.execute("""SELECT title FROM data WHERE user=?""", (user,))]
                send = []
                for i in range(len(fields_names)):
                    send.append(f'{i + 1}. {fields_names[i]}')
                self.send_message(user, '\n'.join(send))
            else:
                self.send_message(user, 'wrong command arguments\ntype "/help field" for more information')
        else:
            self.send_message(user, 'wrong command structure\ntype "/help field" for more information')

    # функция, связанная с движением фигур
    def process_move(self, user, command):
        if len(command) != 3:
            self.send_message(user, 'wrong command structure\ntype "/help move" for more information')
            return
        if self.players[user].condition != FIGHTING:
            self.send_message(user, 'you\'re not fighting right now')
            return
        if self.players[user].color != self.players[user].game_field.step:
            self.send_message(user, 'it\'s not your move now')
            return
        if self.players[user].game_field.transform_check(self.players[user].color):
            self.send_message(user,
                              'choose what figure to transform your pawn into with "/transform {figure_class} first"')
            return
        # передвижение с одной клетки на другую
        if to_cords(command[1]) and to_cords(command[2]):
            row0, col0 = to_cords(command[1])
            row1, col1 = to_cords(command[2])
            self.players[user].game_field.add_act(row0, col0)
            if self.players[user].game_field.add_act(row1, col1):
                if self.players[user].game_field.transform_check(self.players[user].color):
                    self.players[user].game_field.change_step()
                    self.send_field(user, self.players[user].color,
                                    'choose what figure to transform your pawn into with "/transform {figure_class}"')
                    return
                self.send_field(user, self.players[user].color, 'move done successfully')
                self.send_field(self.players[user].enemy, 1 - self.players[user].color, 'enemy move has been done')
                if self.end_check(user):
                    return
            else:
                self.send_message(user, 'this move can\'t be done')
        # рокировка
        elif command[1] == 'castling':
            row = 7 * (1 - self.players[user].color)
            if type(self.players[user].game_field.field[row][4]) != King:
                self.send_message(user, 'castling can\'t be done')
                return
            # длинная рокировка
            if command[2] == 'long':
                for col in (4, 1, 0):
                    self.players[user].game_field.add_act(row, col)
                if len(self.players[user].game_field.acts) != 3:
                    self.send_message(user, 'castling can\'t be done')
                    self.players[user].game_field.acts.clear()
                    return
                if self.players[user].game_field.add_act(row, 2):
                    self.send_field(user, self.players[user].color, 'castling done successfully')
                    self.send_field(self.players[user].enemy, 1 - self.players[user].color, 'enemy move has been done')
                    if self.end_check(user):
                        return
            # короткая рокировка
            elif command[2] == 'short':
                for col in (4, 6, 7):
                    self.players[user].game_field.add_act(row, col)
                if len(self.players[user].game_field.acts) != 3:
                    self.send_message(user, 'castling can\'t be done')
                    self.players[user].game_field.acts.clear()
                    return
                if self.players[user].game_field.add_act(row, 5):
                    self.send_field(user, self.players[user].color, 'castling done successfully')
                    self.send_field(self.players[user].enemy, 1 - self.players[user].color, 'enemy move has been done')
                    if self.end_check(user):
                        return
            else:
                self.send_message(user, 'wrong command arguments\ntype "/help move" for more information')
        else:
            self.send_message(user, 'wrong command arguments\ntype "/help move" for more information')

    # функция превращения пешки по достижении конца поля
    def process_transform(self, user, command):
        if len(command) != 2:
            self.send_message(user, 'wrong command structure\ntype "/help transform" for more information')
            return
        if self.players[user].condition != FIGHTING:
            self.send_message(user, 'you\'re not fighting right now')
            return
        if self.players[user].color != self.players[user].game_field.step:
            self.send_message(user, 'it\'s not your move now')
            return
        if not self.players[user].game_field.transform_check(self.players[user].color):
            self.send_message(user, 'no pawn to transform')
            return
        try:
            figure = figure_classes[command[1].lower().capitalize()]
            if figure in (King, Pawn):
                self.send_message(user, 'pawn can\'t be transformed into that type of figure')
                return
            row, col = self.players[user].game_field.transform_check(self.players[user].color)
            self.players[user].game_field.field[row][col].transform(figure)
            self.players[user].game_field.last_move.clear()
            self.players[user].game_field.change_step()
            self.send_field(user, self.players[user].color, 'figure changed successfully')
            self.send_field(self.players[user].enemy, 1 - self.players[user].color, 'enemy move has been done')
            if self.end_check(user):
                return
        except Exception:
            self.send_message(user, 'wrong command arguments\ntype "/help transform" for more information')

    # отправка сообщений между пользователями(мини-чат)
    def process_message(self, user, command, original):
        message = original[original.find(command[1]) + len(command[1]) + 1:].strip()
        if len(command) < 3:
            self.send_message(user, 'wrong command structure\ntype "/help message" for more information')
            return
        if command[1] == 'enemy':
            if self.players[user].condition != NO_ENEMY:
                self.send_message(self.players[user].enemy, f'message received from user {user}:\n{message}')
                self.send_message(int(command[1]), f'reply user {user} with "/message {user} your_message"')
                self.send_message(user, 'message sent successfully')
        else:
            try:
                self.send_message(int(command[1]), f'message received from user {user}:\n{message}')
                self.send_message(int(command[1]), f'reply user {user} with "/message {user} your_message"')
                self.send_message(user, 'message sent successfully')
            except Exception:
                self.send_message(user,
                                  'this user hasn\'t started dialog with bot yet or does not exist at all\ntype "/help message" for more information')

    # функция, связанная с выводом рейтинга игроков
    def process_top(self, user, command):
        con = sqlite3.connect('data.db')
        cur = con.cursor()
        rating = sorted([x for x in cur.execute("""SELECT * FROM top""")], key=lambda i: i[1], reverse=True)
        # если количесво мест не указано, то выведется топ 10
        if len(command) == 1:
            n = 10
        # иначе выводится n первых мест
        elif len(command) == 2:
            try:
                n = int(command[1])
            except Exception:
                if command[1] == 'all':
                    n = len(rating)
                else:
                    self.send_message(user, 'wrong command structure\ntype "/help top" for more information')
                    return
        else:
            self.send_message(user, 'wrong command structure\ntype "/help top" for more information')
            return
        top = []
        for i in range(n):
            try:
                user_info = self.session.method('users.get', {'user_ids': rating[i][0]})
                url = f"https://vk.com/id{user_info[0]['id']}"
                fullname = f"{user_info[0]['first_name']} {user_info[0]['last_name']}"
                top.append(f'{i + 1}. {fullname} {url} - {rating[i][1]}. Wins: {rating[i][2]} Losses: {rating[i][3]}')
            except Exception:
                break
        top.append('-' * 75)
        user_rating = [(rating[i][1], i + 1) for i in range(len(rating)) if rating[i][0] == user][0]
        top.append(f'You are now on {user_rating[1]} place, your rating: {user_rating[0]}')
        self.send_message(user, '\n'.join(top))

    # функция для нахождения id игрока по имени страницы
    def process_find(self, user, command):
        if not len(command) == 3:
            self.send_message(user, 'wrong command structure\ntype "/help find" for more information')
            return
        else:
            name, surname = command[1:]
            id = []
            con = sqlite3.connect('data.db')
            cur = con.cursor()
            rating = sorted([x for x in cur.execute("""SELECT * FROM top""")], key=lambda i: i[1])
            for i in range(len(rating)):
                user_info = self.session.method('users.get', {'user_ids': rating[i][0]})
                if name == user_info[0]['first_name'] and surname == user_info[0]['last_name']:
                    id.append(f'{rating[i][0]} https://vk.com/id{rating[i][0]}')
            if id:
                for i in id:
                    id, url = i.split()
                    self.send_message(user, f'{name} {surname} id: {id}\nprofile: {url}')
            else:
                self.send_message(user, 'this user doesn\'t exists or never wrote to this bot')

    # функция описания функций
    def process_help(self, user, command):
        if len(command) != 2:
            self.send_message(user, 'wrong command structure, use "/help {command}"')
        commands = ['put', 'remove', 'challenge', 'surrender', 'field',
                    'move', 'transform', 'message', 'top', 'find']
        if command[1] in commands:
            self.send_message(user, txt_to_str(f'data/help/{command[1]}.txt'))
        else:
            self.send_message(user, 'such command doesn\'t exist')

    def process_commands(self, user, command):
        if len(command) == 1:
            self.send_message(user, txt_to_str('data/help/commands.txt'))
        else:
            self.send_message(user, 'just type "/commands"')

    def process_command(self, user, command):
        if user not in self.players:
            self.players[user] = Player()
        con = sqlite3.connect('data.db')
        cur = con.cursor()
        users_ids = [x[0] for x in cur.execute("""SELECT user_id FROM top""")]
        if user not in users_ids:
            cur.execute("""INSERT INTO top(user_id, rating, wins, looses) VALUES(?, ?, ?, ?)""", (user, 0, 0, 0))
        con.commit()
        original = command
        command = command.split()
        if not command:
            self.send_message(user, 'type "/commands" for command list')
            return
        if command[0] == '/put':
            self.process_put(user, command)
        elif command[0] == '/remove':
            self.process_remove(user, command)
        elif command[0] == '/set':
            self.process_set(user, command)
        elif command[0] == '/challenge':
            self.process_challenge(user, command)
        elif command[0] == '/surrender':
            self.process_surrender(user, command)
        elif command[0] == '/field':
            self.process_field(user, command)
        elif command[0] == '/move':
            self.process_move(user, command)
        elif command[0] == '/transform':
            self.process_transform(user, command)
        elif command[0] == '/message':
            self.process_message(user, command, original)
        elif command[0] == '/top':
            self.process_top(user, command)
        elif command[0] == '/find':
            self.process_find(user, command)
        elif command[0] == '/help':
            self.process_help(user, command)
        elif command[0] == '/commands':
            self.process_commands(user, command)
        else:
            self.send_message(user, 'type "/commands" for command list')


if __name__ == '__main__':
    beeg_boi = Bot()
    beeg_boi.start()
    beeg_boi.main_cycle()
