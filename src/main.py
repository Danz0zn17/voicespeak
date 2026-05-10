import pyttsx3
import json
import os
import requests
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent.parent / '.env'
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())


def sync_from_supabase() -> dict:
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_ANON_KEY', '')

    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")

    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}

    cats_r = requests.get(f'{url}/rest/v1/categories?select=*&order=display_order', headers=headers, timeout=10)
    cats_r.raise_for_status()

    phs_r = requests.get(f'{url}/rest/v1/phrases?select=*', headers=headers, timeout=10)
    phs_r.raise_for_status()

    phrases_by_cat: dict[str, list] = {}
    for p in phs_r.json():
        phrases_by_cat.setdefault(p['category_id'], []).append(p)

    config: dict = {'categories': {}, 'settings': {'tts_rate': 150, 'tts_volume': 1.0}}

    for i, cat in enumerate(cats_r.json()):
        cp = phrases_by_cat.get(cat['id'], [])
        config['categories'][cat['name']] = {
            'id': i,
            'mappings': {
                'button_x': next((p['text'] for p in cp if p['input_type'] == 'button_x'), ''),
                'button_o': next((p['text'] for p in cp if p['input_type'] == 'button_o'), ''),
                'analog_left': [p['text'] for p in cp if p['input_type'] == 'analog_left'],
            },
        }

    return config


class VoicePad:
    def __init__(self, fallback_config_path: str | None = None):
        self.config = self._load_config(fallback_config_path)

        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', self.config['settings']['tts_rate'])
        self.engine.setProperty('volume', self.config['settings']['tts_volume'])

        self.categories = list(self.config['categories'].keys())
        self.current_category_idx = 0
        self.current_selection_idx = 0

    def _load_config(self, fallback_path: str | None) -> dict:
        try:
            print("Syncing from Supabase...")
            config = sync_from_supabase()
            print(f"Loaded {len(config['categories'])} categories from cloud.")
            return config
        except Exception as e:
            print(f"Cloud sync failed ({e}). Falling back to local config.")
            if fallback_path and os.path.exists(fallback_path):
                with open(fallback_path) as f:
                    return json.load(f)
            raise RuntimeError("No cloud connection and no local fallback available.") from e

    def sync(self):
        try:
            self.config = sync_from_supabase()
            self.categories = list(self.config['categories'].keys())
            self.current_category_idx = 0
            self.speak("Phrases synced from cloud.")
        except Exception as e:
            self.speak("Sync failed.")
            print(f"Sync error: {e}")

    def speak(self, text: str):
        print(f"Speaking: {text}")
        self.engine.say(text)
        self.engine.runAndWait()

    def get_current_category(self) -> str:
        return self.categories[self.current_category_idx]

    def handle_input(self, input_type: str):
        cat_name = self.get_current_category()
        mappings = self.config['categories'][cat_name]['mappings']

        if input_type == 'button_x':
            self.speak(mappings['button_x'])
        elif input_type == 'button_o':
            self.speak(mappings['button_o'])
        elif input_type == 'next_category':
            self.current_category_idx = (self.current_category_idx + 1) % len(self.categories)
            self.speak(f"Category: {self.get_current_category()}")
        elif input_type == 'analog_toggle':
            options = mappings['analog_left']
            if options:
                self.current_selection_idx = (self.current_selection_idx + 1) % len(options)
                self.speak(options[self.current_selection_idx])
        elif input_type == 'sync':
            self.sync()


if __name__ == '__main__':
    load_env()
    fallback = os.path.expanduser('~/Documents/projects/voice-pad/config/mapping.json')
    vp = VoicePad(fallback_config_path=fallback)
    print(f"Started in category: {vp.get_current_category()}")
    vp.handle_input('button_x')
    vp.handle_input('next_category')
    vp.handle_input('analog_toggle')
