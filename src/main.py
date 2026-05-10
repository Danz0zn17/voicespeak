import pyttsx3
import json
import os

class VoicePad:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', self.config['settings']['tts_rate'])
        self.engine.setProperty('volume', self.config['settings']['tts_volume'])
        
        self.categories = list(self.config['categories'].keys())
        self.current_category_idx = 0
        self.current_selection_idx = 0
        
    def speak(self, text):
        print(f"Speaking: {text}")
        self.engine.say(text)
        self.engine.runAndWait()

    def get_current_category(self):
        return self.categories[self.current_category_idx]

    def handle_input(self, input_type):
        cat_name = self.get_current_category()
        mappings = self.config['categories'][cat_name]['mappings']
        
        if input_type == "button_x":
            self.speak(mappings["button_x"])
        elif input_type == "button_o":
            self.speak(mappings["button_o"])
        elif input_type == "next_category":
            self.current_category_idx = (self.current_category_idx + 1) % len(self.categories)
            self.speak(f"Selected category: {self.get_current_category()}")
        elif input_type == "analog_toggle":
            options = mappings["analog_left"]
            self.current_selection_idx = (self.current_selection_idx + 1) % len(options)
            self.speak(options[self.current_selection_idx])

if __name__ == "__main__":
    # Mock for testing on Mac since PS5 controller might not be plugged in
    vp = VoicePad(os.path.expanduser('~/Documents/projects/voice-pad/config/mapping.json'))
    print(f"Initialized in {vp.get_current_category()}")
    vp.handle_input("button_x")
    vp.handle_input("next_category")
    vp.handle_input("analog_toggle")
