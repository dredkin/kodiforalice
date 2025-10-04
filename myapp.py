from flask import Flask, request, jsonify
import kodihandler
app = Flask(__name__)

# In-memory session store
emptysession = {'cmd': None, 'media': None, 'tokens': None, 'title': None, 'element': None, 'description': None, 'requireexact': False}
    
commands = [
    {'id': ['play'], 'media': ['film', 'show', 'music'], 'words': {'включи', 'включить', 'поставь', 'поставить'}},
    {'id': ['play'], 'media': ['film', 'show'], 'words': {'смотреть', 'посмотреть'}},
    {'id': ['play'], 'media': ['nusic'], 'words': {'сыграй','послушать', 'слушать'}}
]

media = [
    {'media': ['show'], 'words': {'шоу', 'телешоу', 'сериал', 'серию', 'серия', 'серии', 'эпизод'}},
    {'media': ['film'], 'words': {'фильм', 'кинофильм', 'кино', 'картину'}},
    {'media': ['music'], 'words': {'песню', 'песни', 'композицию', 'композиции', 'трек', 'трэк', 'альбом', 'диск', 'группу'}}
]

allmedias = [
    {'media': 'show',  'title1': 'сериал', 'title2': 'сериалов' },
    {'media': 'film',  'title1': 'фильм', 'title2': 'фильмов' },
    {'media': 'music', 'title1': 'композицию', 'title2': 'композиций'},
    {'media': 'all',   'title1': 'вариант', 'title2': 'вариантов'}
]

def titleformsg(mediatype, plural=False):
    for med in allmedias:
        if med['media'] == mediatype:
            return med['title2'] if plural else med['title1']
    return mediatype

class RequestHandler:
    def __init__(self):
        self.kodi = kodihandler.KodiHandler()
        self.session_store = {}
        self.end_session = False
        self.session_data = emptysession.copy()

    def refine_value(self, newvalues, oldvalues):
        if oldvalues is None:
            return newvalues
        elif newvalues is None:
            return oldvalues
        else:
            return list(set(oldvalues).intersection(set(newvalues))) 

    def get_command_and_media(self, origtokens):
        tokens = origtokens.copy()
        self.session_data['originaltokens'] = origtokens.copy()
        for idx, token in enumerate(tokens):
            for cmd in commands:
                if token.lower() in cmd['words']:
                    self.session_data['cmd'] = self.refine_value(self.session_data['cmd'], cmd['id'])
                    self.session_data['media'] = self.refine_value(self.session_data['media'], cmd['media'])
                    del tokens[idx]
                    break

        for idx, token in enumerate(tokens):
            for med in media:
                if token.lower() in med['words']:
                    self.session_data['media'] = self.refine_value(self.session_data['media'], med['media'])
                    tokens = tokens[idx+1:]
                    break

        self.session_data['tokens'] = tokens

        return self.session_data
    
    def handle_request(self, request) -> str:
        data = request.json
        session_id = data.get('session', {}).get('session_id')

        is_new_session = data.get('session', {}).get('new', False)
        user_request = data.get('request', {})

        self.end_session = False
        # Session handling
        if is_new_session or session_id not in self.session_store:
            # New session: initialize session data
            self.session_store[session_id] = emptysession.copy()
            self.session_data = self.session_store[session_id]
            self.session_data['is_new'] = True
        else:
            # Existing session: retrieve previous session data
            self.session_data = self.session_store[session_id]
            self.session_data['is_new'] = False

        # Optionally, store user request in session history
        #session_data['history'].append(user_request)

        response_text = ''
        if not self.kodi.kodiInitialized:
            response_text = "Загрузка данных с Kodi пока не завершена. Подождите немного."
        elif not self.kodi.kodialive:
            response_text = "Kodi сейчас недоступен. Попробуйте позже."
        elif not self.kodi.library_loaded:
            return "Медиа-библиотека Kodi еще не загружена. Попробуйте позже."

        elif is_new_session:
            if not data.get('request', {}).get('original_utterance'):
                response_text = 'Я могу включить вам фильм, сериал или музыку.'
        
        if not response_text:
            response_text = self._handle_user_request(user_request)

        response = {
            "response": {
                "text": response_text,
                "debug": str(self.session_data),
                "end_session": self.end_session
            },
            "version": "1.0",
            "session": {
                "session_id": session_id
            }
        }
        return jsonify(response)

    def _handle_user_request(self, user_request) -> str:
        tokens = user_request.get('nlu', {}).get('tokens', [])
        self.get_command_and_media(tokens)

        if self.session_data['cmd'] is None or len(self.session_data['cmd']) != 1 :
            return 'Не могу понять, что вы хотите. Я могу включить вам фильм, сериал или музыку.'

        cmds = list(self.session_data['cmd'])
        cmd = cmds[0]
        if cmd == 'play':
            if self.session_data['title'] and self.session_data['element']: 
                self.end_session = True
                return 'Включаю {0}.'.format(self.session_data['description'])

            medias = list(self.session_data['media'])
            tokens = list(self.session_data['tokens'])
            if len(medias) == 0:
                return 'Что именно?'
#                    return 'Что это: фильм, сериал или музыка?'

            mediatitlesfound = []
            media = None
            for tmpmedia in medias:
                if tmpmedia in ['film' , 'show', 'music']:
                    newtitlesfound = KH.findMedia(tmpmedia, tokens, self.session_data['requireexact'])
                    if newtitlesfound:
                        if mediatitlesfound:
                            media = 'all'
                        else:
                            media = tmpmedia
                        mediatitlesfound = mediatitlesfound + newtitlesfound
                else:
                    self.end_session = True
                    return 'Не знаю я, что такое {0}!'.format(media)

            if media is None:
                media = 'all'

            if len(mediatitlesfound) == 0:
                return 'Не могу найти {0} по запросу {1}.'.format(titleformsg(media), ' '.join(tokens))
            elif len(mediatitlesfound) == 1:
                self.end_session = True
                if KH.playMedia(media, mediatitlesfound[0]):
                    return'Включаю {0} {1}.'.format(titleformsg(media), mediatitlesfound[0]['label'])
                else:
                    return 'Не получилось включить {0} {1}.'.format(titleformsg(media), mediatitlesfound[0]['label'])
            else:
                self.session_data['requireexact'] = True
                return 'Найдено несколько {0}: {1}. Что именно включить?'.format(titleformsg(media, plural=True), ', '.join([item['label'] for item in mediatitlesfound]))
        else:
            self.end_session = True
            return 'Не умею я {0}!'.format(cmd)


@app.route('/webhook', methods=['POST','GET'])
def webhook():
    return RH.handle_request(request)


if __name__ == '__main__':
    KH = kodihandler.KodiHandler()
    RH = RequestHandler()
    app.run(port=5000)
