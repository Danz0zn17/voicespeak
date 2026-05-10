# Voice-Pad Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this task-by-task.

**Goal:** Create a Python-based system for a Raspberry Pi that maps PS5 controller inputs to text-to-speech outputs based on environmental categories.

**Architecture:**
- **Input Modulue:** Captures events from `/dev/input/js0` (PS5 controller).
- **Logic Engine:** Tracks current "Category" and "Selection" via analog sticks and buttons.
- **Mapping System:** External JSON file for phrases/categories.
- **Output Module:** pyttsx3 for offline speech.

**Tech Stack:** Python 3, `evdev` (or `pygame`), `pyttsx3`, `json`.

---

### Task 1: Mapping Configuration (JSON)
**Objective:** Define the phrases for different locations.
**Files:**
- Create: `config/mapping.json`
**Step:** Create a structure with 5 categories (Home, Kitchen, School, Bedroom, Outside). Each category has button-to-phrase mappings.

### Task 2: Controller Input Wrapper
**Objective:** Capture PS5 controller events.
**Files:**
- Create: `src/input_handler.py`
**Step:** Use `evdev` to detect button presses (X, O, Triangle, Square) and analog stick thresholds.

### Task 3: Logic Engine
**Objective:** Handle category switching and selection.
**Files:**
- Create: `src/main.py`
**Step:** Implement the logic where X confirms a selection, and analog sticks toggle through phrases in the active category.

### Task 4: TTS Integration
**Objective:** Speak the selected phrase.
**Files:**
- Modify: `src/main.py`
**Step:** Integrate `pyttsx3` to speak the string when a button is pressed.
