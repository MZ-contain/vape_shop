from telebot import types


def generate_markup(keyboard):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True,one_time_keyboard=False,row_width=3)
    markup.add(*keyboard)
    return markup

def generate_message(list_tuple):
    message='В наличии:\n\n'
    for l in list_tuple:
        #l[0] - description
        #l[1] - price
        #l[2] - small_discount
        #l[3] - small_discount_treshold
        #l[4] - big_discount
        #l[5] - big_discount_treshold
        #l[6] - unit
        message = message + 'описание - {0}\n'.format(l[0])
        message = message +'цена до {0}{1} - {2}руб.\n'.format(str(l[3]),l[6],str(l[1]))
        if l[4]:
            message = message+'цена {0}-{1}{2} - {3}руб.\n'.format(str(l[3]),str(l[5]),l[6],str(l[2]))
            message = message + 'цена от {0}{1} - {2}руб.\n'.format(str(l[5]), l[6], str(l[4]))
        else:
            message = message+'цена от {0}{1} - {2}руб.\n'.format(str(l[3]),l[6],str(l[2]))
        message = message +'\n'
    return message

def isFloat(value):
    try:
        float(value)
        return True
    except ValueError:
        return False
    except TypeError:
        return False
