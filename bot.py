import settings
import sql_handler
from decimal import *
from order_calc import TempShelve, CustomerTempData
import telebot
from settings import fsm_name
import shelve
from telebot import types


# класс, отвечающий за конечный автомат
# для хранения состояний конечного автомата для каждого пользователя используется временное хранилище shelve

class FSM:

    # инициализация покупателя, конечному автомату присваивается значение 'start'
    @staticmethod
    def initialize_customer(chat_id):
        with shelve.open(fsm_name) as fsm:
            fsm[str(chat_id)] = 'start'

    # изменение значения конечного автомата
    @staticmethod
    def set_state(chat_id, state):
        with shelve.open(fsm_name) as fsm:
            try:
                fsm.update([(str(chat_id), state)])
            except KeyError:
                fsm[str(chat_id)] = state

    # получение значения конечного автомата
    @staticmethod
    def get_current_state(chat_id):
        with shelve.open(fsm_name) as fsm:
            try:
                return fsm[str(chat_id)]
            except KeyError:
                fsm[str(chat_id)] = 'start'
                return fsm[str(chat_id)]


# основной класс реализующий бота, наследуется от класса TeleBot из библиотеки pyTelegramBotAPI
class Bot(telebot.TeleBot):
    def __init__(self, token):
        super().__init__(token)
        self.fsm = FSM()
        self.temp_shelve = TempShelve()
        self.temp_data = CustomerTempData()

        # диалоговые обработчики для заказа

        # обработчик для комманды "order"
        @self.message_handler(commands=['order'])
        def order(message):
            text, markup = self.get_order_keyboard_and_message(message.chat.id)
            self.fsm.set_state(message.chat.id, 'order_categories')
            self.send_message(chat_id=message.chat.id, text=text, reply_markup=markup)

        # обрабатывает сообщение, если оно входит в перечень категорий
        # и состояние конечного автомата для пользователя = "order_categories"
        # служит для показа производителей продукта
        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_categories() and self.fsm.
                              get_current_state(mess.chat.id) == 'order_categories',
                              content_types=['text'])
        def order_categories(message):
            db = sql_handler.SqlHandler()
            markup = self.generate_markup(db.get_assortment(message.text))
            db.close()
            self.fsm.set_state(message.chat.id, 'order_product')
            self.send_message(chat_id=message.chat.id, text='Выберите необходимого производителя', reply_markup=markup)

        # обрабатывает сообщение, если оно входит в перечень ассортимента магазина
        # и состояние конечного автомата для пользователя = "order_products"
        # служит для показа типа товара для выбранного ранее пользователем производителя
        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_full_assortment() and self.fsm.
                              get_current_state(mess.chat.id) == 'order_product',
                              content_types=['text'])
        def order_product(message):
            db = sql_handler.SqlHandler()
            for text in self.generate_message(message.text):
                self.send_message(chat_id=message.chat.id, text=text)
            markup = self.generate_markup(db.get_subproduct_info(message.text))
            self.temp_data.initialize_customer(str(message.chat.id), message.text)
            if db.get_category_of_product(message.text) == 'Табак':
                self.fsm.set_state(message.chat.id, 'choose_flavor')
            else:
                self.fsm.set_state(message.chat.id, 'set_weight')
            self.send_message(chat_id=message.chat.id, text='Выберите необходимый тип товара', reply_markup=markup)
            db.close()

        # обрабатывает сообщение, если оно входит в перечень всех продуктов
        # и состояние конечного автомата для пользователя = "choose_flavor"
        # служит для показа всех подкатегорий данного продукта, если они имеются
        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_full_subproduct_info() and
                                                self.fsm.get_current_state(mess.chat.id) == 'choose_flavor',
                              content_types=['text'])
        def choose_flavor(message):
            db = sql_handler.SqlHandler()
            markup = self.generate_markup(db.get_flavor(message.text, self.temp_data.temp_data(message.chat.id)))
            self.send_message(chat_id=message.chat.id, text = 'Выберите вкус', reply_markup=markup)
            self.temp_data.set_description(message.chat.id,message.text)
            self.fsm.set_state(message.chat.id, 'set_weight')
            db.close()

        # обрабатывает сообщение, если оно входит в список продуктов, если для него нет подкатегорий или
        # если оно входит в список подкатегорий
        # и состояние конечного автомата для пользователя = "set_weight"
        # служит для диалога с пользователем для получения количества необходимого количества товара
        @self.message_handler(func = lambda mess: mess.text in sql_handler.SqlHandler().get_all_flavors() and self.fsm.
                              get_current_state(mess.chat.id) == 'set_weight',
                              content_types=['text'])
        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_full_subproduct_info() and
                                                self.fsm.get_current_state(mess.chat.id) == 'set_weight',
                              content_types=['text'])
        def set_weight(message):
            markup = telebot.types.ReplyKeyboardRemove()
            db = sql_handler.SqlHandler()
            if message.text in db.get_full_subproduct_info():
                self.temp_data.set_description(message.chat.id, message.text)
            db.set_subproduct_id(message.chat.id, message.text)
            text = 'Введите необходимое количество в {0}'.format(
                db.get_unit(self.temp_data.get_subproduct_id(message.chat.id)))
            db.close()
            self.fsm.set_state(message.chat.id, 'count_order')
            self.send_message(chat_id=message.chat.id, text=text, reply_markup=markup)

        # обрабатывает сообщение, если оно является и числом
        # и состояние конечного автомата для пользователя = "count_order"
        # используется для подсчёта стоимости заказа с учётом различных скидок для оптовой продажи
        @self.message_handler(func=lambda message: self.isFloat(message.text)
                                                   and self.fsm.get_current_state(message.chat.id) == 'count_order',
                              content_types=['text'])
        def count_order(message):
            db = sql_handler.SqlHandler()
            subproduct_id = self.temp_data.get_subproduct_id(message.chat.id)
            weight = float(message.text)
            Price, Small_discount, Small_discount_treshold, Big_discount, Big_discount_treshold, Unit_size = db.count_order_info(
                self.temp_data.get_subproduct_id(message.chat.id))
            if not db.get_min_weight(subproduct_id):
                min_weight = Unit_size
            else:
                min_weight = db.get_min_weight(subproduct_id)
            if Decimal(str(weight)) % Decimal(str(Unit_size)) != 0.0 or weight<min_weight:
                text = 'Вы указали неправильное количество товара\n' \
                       'Выберите из предложенных или введите новое значение сами'
                markup = self.generate_help_markup(weight,Unit_size,min_weight)
                self.send_message(chat_id=message.chat.id, text=text, reply_markup=markup)
                return
            count = weight / Unit_size
            if not Big_discount_treshold and not Small_discount_treshold:
                price = count * Price
            elif not Big_discount_treshold:
                if weight < Small_discount_treshold:
                    price = count * Price
                else:
                    price = count * Small_discount
            else:
                if weight < Small_discount_treshold:
                    price = count * Price
                elif weight >= Small_discount_treshold and weight < Big_discount_treshold:
                    price = count * Small_discount
                else:
                    price = count * Big_discount
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton(text='Подтвердить', callback_data='accept'))
            markup.add(telebot.types.InlineKeyboardButton(text='Изменить количество товара', callback_data='change'))
            markup.add(telebot.types.InlineKeyboardButton(text='Удалить товар', callback_data='delete'))
            text = 'Идёт подсчёт'
            self.send_message(chat_id=message.chat.id, text=text, reply_markup=types.ReplyKeyboardRemove())
            text = 'Вы выбрали\n'+self.temp_shelve.order_description(subproduct_id,weight,price)
            self.temp_data.add_order_product(message.chat.id, int(price), weight)
            self.send_message(chat_id=message.chat.id, text=text, reply_markup=markup)
            self.fsm.set_state(str(message.chat.id),'accept_order')
            db.close()

        # обработчик для кнопки оформить заказ
        # используется для диалога с пользователем по поводу дополнительной информации о заказе
        @self.callback_query_handler(func=lambda call: call.data == 'execute_order')
        def execute_order(call):
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            markup.add(telebot.types.KeyboardButton(text='Пропустить'))
            self.fsm.set_state(call.message.chat.id, 'set_description_to_order')
            self.edit_message_text(text=call.message.text, chat_id=call.message.chat.id,
                                   message_id=call.message.message_id)
            self.send_message(text='Введите комментарии к заказу или нажмите пропустить, чтобы перейти дальше', chat_id=call.message.chat.id,
                              reply_markup=markup)

        # обработчик для дополнительной информации о заказе,
        # активируется только при состоянии конечного автомата для пользователя =
        # = "set_description_to_order"
        @self.message_handler(func= lambda mess: self.fsm.get_current_state(mess.chat.id) == 'set_description_to_order',
                              content_types=['text'])
        def description(message):
            if message.text == 'Пропустить':
                description = 'нет'
            else:
                description = message.text
            self.temp_data.set_description_of_order(message.chat.id,description)
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            markup.add(telebot.types.KeyboardButton(text='Нажмите на кнопку, чтобы передать номер телефона',
                                                    request_contact=True))
            self.fsm.set_state(message.chat.id, 'contact')
            self.send_message(text='Cообщите свой номер телефона', chat_id=message.chat.id,
                              reply_markup=markup)

        # обработчик для получения телефонного номера покупателя
        # активируется только, когда тип сообщения является контактом и
        # и состояние конечного автомата для пользователя = 'contact'
        @self.message_handler(func=lambda message: self.fsm.get_current_state(message.chat.id) == 'contact',
                              content_types=['contact'])
        def contact(message):
            db = sql_handler.SqlHandler()
            db.add_customer(message.chat.id, message.contact.phone_number)
            order_id = db.add_order(message.chat.id, self.temp_shelve.get_full_price(message.chat.id),
                                    self.temp_data.get_order_description(message.chat.id))
            self.add_products(db, message.chat.id, order_id)
            text = 'Ваш заказ №{} был оформлен, ожидайте, пока мы вам позвоним'.format(order_id)

            self.send_message(text=text, chat_id=message.chat.id,reply_markup=types.ReplyKeyboardRemove())
            text = 'Новый заказ №{0}!\n'.format(order_id) + self.temp_shelve.order_info(message.chat.id)
            text = text+'\nКомментарии к заказу:\n'+self.temp_data.get_order_description(message.chat.id)
            self.temp_shelve.del_order(message.chat.id)
            db.close()

        # обработчик кнопки для удаления определенного товара в заказе
        @self.callback_query_handler(func=lambda call: call.data.isdigit())
        def delete_buttons(call):
            self.temp_shelve.del_product(call.message.chat.id, call.data)
            message, markup = self.get_order_keyboard_and_message(call.message.chat.id)
            if isinstance(markup, telebot.types.ReplyKeyboardMarkup):
                text = 'Вы удалили все товары в заказе\n' \
                       'Выберите /order, чтобы начать заново'
                self.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=call.message.message_id)
            else:
                self.edit_message_text(text=message, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                       reply_markup=markup)

        # обработчик кнопки подтверждения выбранного товара
        @self.callback_query_handler(func=lambda call:call.data=='accept')
        def accept(call):
            db = sql_handler.SqlHandler()
            subproduct_id, weigth, price = self.temp_data.get_order_product(call.message.chat.id)
            message = 'Вы успешно добавили продукт\n' + self.temp_shelve.order_description(subproduct_id,weigth,price)
            self.temp_shelve.add_product(call.message.chat.id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(text='Продолжить работу с заказом',callback_data='continue_work_with_order'))
            markup.add(types.InlineKeyboardButton(text='Вернуться к выбору товаров данного продукта',callback_data='return'))
            self.edit_message_text(text=message, chat_id=call.message.chat.id, message_id=call.message.message_id,reply_markup=markup)
            self.fsm.set_state(call.message.chat.id,'decision')
            db.close()

        # обработчик кнопки для продолжения работы с заказом
        @self.callback_query_handler(func=lambda call: call.data =='continue_work_with_order')
        def continue_work(call):
            self.edit_message_text(chat_id=call.message.chat.id,message_id = call.message.message_id, text = call.message.text)
            order(call.message)

        #обработчик кнопки для возврата к выбору товара продукта
        @self.callback_query_handler(func=lambda call:call.data == 'return')
        def return_to_product(call):
            subproduct_id = self.temp_data.get_order_product(call.message.chat.id)[0]
            self.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                   text=call.message.text)
            db = sql_handler.SqlHandler()
            call.message.text = db.get_product_name(subproduct_id)
            self.fsm.set_state(call.message.chat.id,'order_product')
            order_product(call.message)

        # обработчик кнопки для изменения количества товара
        @self.callback_query_handler(func=lambda call: call.data == 'change')
        def change(call):
            message = 'Изменение количества товара\n' \
                      'Введите необходимое количество товара'
            self.edit_message_text(text=message, chat_id=call.message.chat.id, message_id=call.message.message_id)
            self.fsm.set_state(str(call.message.chat.id),'count_order')

        # обработчик кнопки для удаления выбранного товара
        @self.callback_query_handler(func=lambda call: call.data == 'delete')
        def delete(call):
            self.temp_data.del_order(call.message.chat.id)
            message = 'Вы удалили товар из данного заказа\n' \
                      'Выберите /order, чтобы продолжить работу с заказом'
            self.edit_message_text(text=message, chat_id=call.message.chat.id, message_id=call.message.message_id)

        # обработчик кнопки для продолжения заказа
        @self.callback_query_handler(func=lambda call: call.data == 'continue')
        def continue_order(call):
            db = sql_handler.SqlHandler()
            markup = self.generate_markup(db.get_categories())
            self.edit_message_text(text='Продолжение выбора заказа', chat_id=call.message.chat.id,
                                   message_id=call.message.message_id)
            self.send_message(chat_id=call.message.chat.id, text='Выбор категории', reply_markup=markup)
            db.close()

        # обработчик кнопки для удаления некоторых товаров из корзины
        @self.callback_query_handler(func=lambda call: call.data == 'delete_order_product')
        def delete_order_product(call):
            markup = self.set_keyboard(call.message.chat.id)
            self.edit_message_text(text=call.message.text, chat_id=call.message.chat.id,
                                   message_id=call.message.message_id, reply_markup=markup)

        # обработчик кнопки для удаления всего заказа
        @self.callback_query_handler(func=lambda call:call.data == 'delete_order')
        def delete_order(call):
            message = 'Удаление заказа\n' \
                      'Выберите /order, чтобы начать заново'
            self.temp_shelve.del_order(call.message.chat.id)
            self.edit_message_text(text=message, chat_id=call.message.chat.id, message_id=call.message.message_id)

        #диалоговые обработчики для прайс-листа

        # обработчик для команды 'price'
        @self.message_handler(commands=['price'],content_types=['text'])
        def price(message):
            db = sql_handler.SqlHandler()
            markup = self.generate_markup(db.get_categories())
            self.send_message(chat_id=message.chat.id,text = 'Выберите категорию', reply_markup=markup)
            self.fsm.set_state(message.chat.id, 'product')
            db.close()

        # обрабатывает сообщение, если оно входит в перечень категорий
        # и состояние конечного автомата для пользователя = "product"
        # служит для показа производителей продукта
        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_categories()
                                                and self.fsm.get_current_state(mess.chat.id) == 'product',
                              content_types=['text'])
        def product(message):
            db = sql_handler.SqlHandler()
            markup = self.generate_markup(db.get_assortment(message.text))
            self.send_message(chat_id=message.chat.id, text='Выберите продукт', reply_markup=markup)
            db.close()
            self.fsm.set_state(message.chat.id,'product_info')

        @self.message_handler(func=lambda mess: mess.text in sql_handler.SqlHandler().get_full_assortment()
                                                and self.fsm.get_current_state(mess.chat.id) == 'product_info',
                              content_types=['text'])
        def product_info(message):
            db = sql_handler.SqlHandler()
            markup = types.ReplyKeyboardRemove()
            for text in self.generate_message(message.text):
                self.send_message(chat_id=message.chat.id, text=text, reply_markup=markup)
            db.close()

        # обработчик команды 'help'
        @self.message_handler(commands=['help'],content_types=['text'])
        def helper(message):
            text = '/price - цена определенного продукта\n' \
                   '/order - оформление заказа'
            self.send_message(chat_id=message.chat.id, text=text)

        # обработчик команды 'start'
        @self.message_handler(commands=['start'],content_types=['text'])
        def start(message):
            text = 'Здравствуйте, вас приветствует бот HookahService Челябинск\n' \
                      'vk.com/hookahservice01\n' \
                      'Напишите /price, чтобы увидеть цену продукта\n'
            self.fsm.set_state(message.chat.id,"start")
            self.send_message(chat_id=message.chat.id, text=text, reply_markup=types.ReplyKeyboardRemove())

        # обработчик для команды my_orders
        @self.message_handler(commands=['my_orders'],content_types=['text'])
        def show_orders(message):
            db = sql_handler.SqlHandler()
            order_ids = db.get_order_ids(chat_id=message.chat.id)
            if len(order_ids)==0:
                self.send_message(chat_id=message.chat.id, text = 'У вас нет заказов')
            else:
                for order_id in order_ids:
                    self.send_message(chat_id=message.chat.id,text = self.generate_order_info(db,order_id))
            db.close()

        # обработчик для остальных сообщений, которые не являются правильными
        @self.message_handler(func = lambda message: True, content_types=['text'])
        def error(message):
            text = 'Вы ввели, что-то неправильно\n' \
                   'Выберите /help для помощи'
            self.send_message(chat_id=message.chat.id,text = text)

    # генерациия информации о заказе
    def generate_order_info(self,db,order_id):
        message ='Заказ №{}\n\n'.format(order_id)
        total_price = 0
        product_list = db.get_product_info_from_order(order_id)
        for product in product_list:
            subproduct_id = product[0]
            weight = product[1]
            price = product[2]
            message = message+self.temp_shelve.order_description(subproduct_id,weight,price)
            total_price = total_price+price
        return message+'Общая стоимость - {} рублей'.format(total_price)

    # генерация сообщения для команды /order
    def get_order_keyboard_and_message(self, chat_id):
        message = self.temp_shelve.order_info(chat_id)
        db = sql_handler.SqlHandler()
        if not message:
            message = 'Калькулятор заказов\n' \
                      'Выберите категорию'
            markup = self.generate_markup(db.get_categories())
        else:
            message = 'Ваш заказ\n' + message
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton('Оформить заказ', callback_data='execute_order'),
                       telebot.types.InlineKeyboardButton('Удалить заказ', callback_data='delete_order'))
            markup.add(telebot.types.InlineKeyboardButton('Удалить некоторые товары',
                                                          callback_data='delete_order_product'))
            markup.add(telebot.types.InlineKeyboardButton('Продолжить выбор товаров', callback_data='continue'))
        db.close()
        return message, markup

    # генерация кнопок для удаления продуктов из корзины
    def set_keyboard(self, chat_id):
        markup = telebot.types.InlineKeyboardMarkup()
        for subproduct_id in self.temp_shelve.get_order_keys(chat_id):
            markup.add(telebot.types.InlineKeyboardButton(self.temp_shelve.order_description(subproduct_id),
                                                          callback_data=str(subproduct_id)))
        return markup

    # добавление заказа в таблицу OrderProducts базы данных
    def add_products(self, db, chat_id, order_id):
        for product in self.temp_shelve.get_order_items(chat_id):
            subproduct_id = product[0]
            weigth, price = product[1]
            db.add_order_product(order_id, int(subproduct_id), weigth, price)

    # генерация клавиатуры помощника для выбора правильного количества продукта
    def generate_help_markup(self,weight,unit_size,min_weight):
        weight = Decimal(str(weight))
        unit_size = Decimal(str(unit_size))
        count = weight//unit_size
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        min_offer = min_weight if count==0 or weight<min_weight else count*unit_size
        markup.add(str(float(min_offer)))
        markup.add(str(float(min_offer)+float(unit_size)))
        return markup

    # генерация клавиатуры для перемещения по каталогам
    def generate_markup(self,keyboard):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=3)
        #markup.add(*list(set(keyboard)))
        keyboard = list(dict(zip(keyboard,keyboard)).values())
        markup.add(*keyboard)
        return markup

    # генерация информации о выбранном продукте
    def generate_message(self, product_name):
        db = sql_handler.SqlHandler()
        message = product_name + '\nВ наличии:\n\n'
        decription_list = db.get_product_description(product_name)
        decription_list = list(set(decription_list))
        for description in decription_list:
            #description[0] - description
            #description[1] - subproduct_id
            # l[0] - price
            # l[1] - small_discount
            # l[2] - small_discount_treshold
            # l[3] - big_discount
            # l[4] - big_discount_treshold
            # l[5] - unit
            # l[6] - flavor
            message = message + 'описание - {0}\n\n'.format(description)
            info_list = db.get_product_info(description,product_name)
            for l in info_list:
                if l[1]:
                    message = message + 'цена до {0}{1} - {2}руб.\n'.format(str(l[2]), l[5], str(l[0]))
                    if l[4]:
                        message = message + 'цена {0}-{1}{2} - {3}руб.\n'.format(str(l[2]), str(l[4]), l[5], str(l[1]))
                        message = message + 'цена от {0}{1} - {2}руб.\n'.format(str(l[4]), l[5], str(l[3]))
                    else:
                        message = message + 'цена от {0}{1} - {2}руб.\n'.format(str(l[2]), l[5], str(l[1]))
                    if db.get_category_of_product(product_name) == 'Табак':
                        message = message + 'вкус - {}\n'.format(l[6])
                else:
                    message = message + '{} - {}руб'.format(l[6], l[0])
                message = message +'\n'
            yield message
            message = ''

    # проверка является ли сообщение числом
    def isFloat(self,value):
        try:
            float(value)
            return True
        except ValueError:
            return False
        except TypeError:
            return False

# инициализация бота
if __name__ == '__main__':
    bot = Bot(settings.token)
    bot.polling(none_stop=True)

