# Show some notifiations :
from kodijson import *
import threading
import time
import flask, jsonify, requests
import pymorphy3
import re
from fuzzywuzzy import fuzz
import config  # <-- добавьте импорт конфигурации

#Login with default kodi/kodi credentials

#Login with custom credentials

def roman_to_int(s):
    roman_numerals = {
        'II': '2', 'III': '3', 'IV': '4', 'V': '5', 'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9'   #,'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000 --- IGNORE to reduce noice---
    }

    if s in roman_numerals:
        return roman_numerals[s]
    else:
        return s
    

def log(message):
    print(message)

class KodiHandler():
    def __init__(self):
        log('KodiHandler initializing...')
        pass
        self.kodiInitialized = False
        self.library_loaded = False
        self.kodi = Kodi(
            "http://{config.KODI_HOST}:{config.KODI_PORT}/jsonrpc",
            config.KODI_LOGIN,
            config.KODI_PASSWORD
        )
        self.kodialive = False
        self.movies = None
        self.shows = None
        self.music = None
        self.morph = pymorphy3.MorphAnalyzer()

        self.ping_update_interval = config.PING_UPDATE_INTERVAL  # из config
        log('Pinging Kodi...' )
        self.update_kodi_alive()  # <-- Start ping thread
        log('Updated Kodi alive status: {0}'.format(self.kodialive))
        log('Updating library...' )
        self.updateLibrary()
        log('Library updated. Loaded {0} movies, {1} shows, {2} music albums.'.format(
            len(self.movies['result']['movies']) if self.movies else 0,
            len(self.shows['result']['tvshows']) if self.shows else 0,
            len(self.music['result']['albums']) if self.music else 0
        ))
        self.update_interval = config.LIBRARY_UPDATE_INTERVAL  # из config
        self._start_background_update()
        self._start_backgroud_update_kodi_alive()
        log('KodiHandler initialized.')
        self.kodiInitialized = True

    def normalize_text(self, text, exaact=False):
        words = text.split()
        normalized_words = [self.morph.parse(roman_to_int(word))[0].normal_form for word in words]
        return normalized_words

    def text_resembles(self, norm_a, norm_b, exact=False):
        """
        Возвращает True, если не менее 70% слов из norm_a содержатся в norm_b.
        Если exact=True, то True только если norm_a и norm_b совпадают как списки.
        Иначе — возвращает процент совпадения fuzzy_search строк, построенных по этим спискам.
        """
        if not norm_a or not norm_b:
            return False
        if exact:
            return norm_a == norm_b
        matches = sum(1 for word in norm_a if word in norm_b)
        min_len = len(norm_a)
        ratio = matches / min_len if min_len else 0
        if ratio >= 0.7:
            return True
        # иначе — fuzzy сравнение строк
        str_a = ' '.join(norm_a)
        str_b = ' '.join(norm_b)
        return fuzz.ratio(str_a, str_b) / 100.0 > 0.7
    
    def _start_background_update(self):
        def background_task():
            while True:
                # Если библиотека не загружена, пробуем чаще
                if self.kodialive and self.library_loaded:
                    interval = self.update_interval
                else:
                    interval = self.ping_update_interval 
                time.sleep(interval)
                self.updateLibrary()
        threading.Thread(target=background_task, daemon=True).start()

    def update_kodi_alive(self):
        self.kodialive = self.pingKodi()

    def _start_backgroud_update_kodi_alive(self):
        def background_task():
            while True:
                time.sleep(self.ping_update_interval)
                self.update_kodi_alive()

        threading.Thread(target=background_task, daemon=True).start()

    def pingKodi(self):
        try:
            self.kodi.timeout = 2
            self.kodialive = self.kodi.JSONRPC.Ping() is not None
            self.kodi.timeout = None
        except Exception as e:
            self.kodialive = False
        return self.kodialive
    
    def updateLibrary(self):
        try:
            self.shows = self.kodi.VideoLibrary.GetTVShows()
            if self.shows:  
                for show in self.shows['result']['tvshows']:
                    show['normalizedlabel'] = self.normalize_text(show['label'])
            self.movies = self.kodi.VideoLibrary.GetMovies()
            if self.movies: 
                for movie in self.movies['result']['movies']:
                    movie['normalizedlabel'] = self.normalize_text(movie['label'])
            self.music = self.kodi.AudioLibrary.GetAlbums()
            if self.music:
                for album in self.music['result']['albums']:
                    album['normalizedlabel'] = self.normalize_text(album['label'])
            # Проверяем, что все три типа медиа загружены
            self.library_loaded = bool(self.movies and self.shows and self.music)
        except Exception as e:
            log(f"Ошибка при обновлении библиотеки: {e}")

    def getMediaId(self, media, title):
        if media == 'film':
            listtosearch = self.movies
            node = 'movies'
            id_field = 'movieid'
        elif media == 'show':
            listtosearch = self.shows
            node = 'tvshows'
            id_field = 'tvshowid'
        elif media == 'music':
            listtosearch = self.music
            node = 'albums'
            id_field = 'albumid'
        elif media == 'all':
            return self.getMediaId('film', title) or self.getMediaId('show', title) or self.getMediaId('music', title)
        else:
            return None
        
        if listtosearch:
            for item in listtosearch['result'][node]:
                if item['label'] == title:
                    return item[id_field]
        return None

    def playMedia(self, media, item):
        title_id = self.getMediaId(media, item['label'])
        if title_id:
            if media == 'film':
                self.kodi.Player.Open({"item": {"movieid": title_id}})
            elif media == 'show':
                episode = self.getFirstUnwatchedEpisode(title_id)
                if episode:
                    self.kodi.Player.Open({"item": {"episodeid": episode['episodeid']}})
            elif media == 'music':
                self.kodi.Player.Open({"item": {"albumid": title_id}})
            else:
                return False
            return True
        return False
        
    def getFirstUnwatchedEpisode(self, show_id):
        seasons = self.kodi.VideoLibrary.GetSeasons({"tvshowid": show_id ,  "properties": [ 'season', "episode", "watchedepisodes"]})
        for season in seasons['result']['seasons']:
            if int(season['episode']) > int(season['watchedepisodes']):
                episodes = self.kodi.VideoLibrary.GetEpisodes({ "tvshowid": show_id, "season": int(season['season']), "properties": ["playcount", "lastplayed", 'season', 'episode']})
                for episode in episodes['result']['episodes']:
                    if int(episode['playcount']) <= 0:
                        return episode
        return None


    def findMedia(self, media, tokens, requireexact):
        log('finding {0} {1} {2}'.format(media, tokens, requireexact)) 
        title = ' '.join(tokens).lower()
        found = []
        if media == 'film':
            listtosearch = self.movies
            node = 'movies'
        elif media == 'show':
            listtosearch = self.shows
            node = 'tvshows'
        elif media == 'music':
            listtosearch = self.music
            node = 'albums'
        elif media == 'all':
            return self.findMedia('film', tokens, requireexact) + self.findMedia('show', tokens, requireexact) + self.findMedia('music', tokens, requireexact)
        else:
            return found
    
        title_words = self.normalize_text(title)
        print(title_words)
        if listtosearch:
            for item in listtosearch['result'][node]:
                if self.text_resembles(title_words, item['normalizedlabel'], requireexact):
                    found.append(item)
        return found





#
#
#
#
#
