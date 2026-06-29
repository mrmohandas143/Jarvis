import os
import sys
import webbrowser
import re
import time
import datetime
from io import BytesIO

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Please install google-genai: pip install google-genai")
    sys.exit(1)

try:
    import wikipedia
except ImportError:
    print("Please install wikipedia: pip install wikipedia")
    sys.exit(1)

try:
    import speech_recognition as sr
except ImportError:
    print("Please install speech_recognition and pyaudio: pip install SpeechRecognition pyaudio")
    sys.exit(1)

try:
    import edge_tts
    import asyncio
    import pygame
except ImportError:
    print("Please install edge-tts and pygame: pip install edge-tts pygame")
    sys.exit(1)

# Hardware Control - gpiozero (Mock gracefully on Windows)
try:
    from gpiozero import Motor, LED, PWMOutputDevice
    # If not on linux, use MockFactory
    if sys.platform != 'linux':
        from gpiozero.pins.mock import MockFactory, MockPWMPin
        from gpiozero import Device
        Device.pin_factory = MockFactory(pin_class=MockPWMPin)
except ImportError:
    print("Please install gpiozero: pip install gpiozero")
    sys.exit(1)

# Initialize Audio via Pygame
try:
    # Use ALSA on Linux to prevent 'resource busy'
    if sys.platform == 'linux':
        os.environ["SDL_AUDIODRIVER"] = "alsa"
    pygame.mixer.init(frequency=24000)
except Exception as e:
    print(f"Failed to initialize pygame mixer cleanly: {e}")
    try:
        # Fallback
        if "SDL_AUDIODRIVER" in os.environ:
            del os.environ["SDL_AUDIODRIVER"]
        pygame.mixer.init()
    except Exception as e2:
        print(f"Pygame fallback failed: {e2}")

# Initialize Anti-Gravity hardware components
try:
    antigravity_motor = Motor(forward=17, backward=18)
    electromagnet = LED(27)
    lift_controller = PWMOutputDevice(22)
except Exception as e:
    print(f"Hardware initialization failed: {e}")
    antigravity_motor = None
    electromagnet = None
    lift_controller = None

def get_ist_time():
    ist_offset = datetime.timedelta(hours=5, minutes=30)
    ist_tz = datetime.timezone(ist_offset)
    return datetime.datetime.now(ist_tz)

def speak(text, lang='en'):
    print(f"\nJARVIS: {text}")
    try:
        # High quality male voices: Ryan (English GB), Valluvar (Tamil)
        voice = "ta-IN-ValluvarNeural" if lang == 'ta' else "en-GB-RyanNeural"
        
        async def _generate_audio():
            communicate = edge_tts.Communicate(text, voice)
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            return bytes(audio_data)

        # Generate audio buffer
        audio_bytes = asyncio.run(_generate_audio())
        fp = BytesIO(audio_bytes)
        
        pygame.mixer.music.load(fp)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
            
        # Ensure cleanup (unload only works Pygame 2.0+)
        try:
            pygame.mixer.music.unload()
        except AttributeError:
            pass
            
    except Exception as e:
        print(f"[TTS Error]: {e}")

def get_greeting():
    current_hour = get_ist_time().hour
    if 5 <= current_hour < 12:
        return "Good morning sir."
    elif 12 <= current_hour < 17:
        return "Good afternoon sir."
    elif 17 <= current_hour < 21:
        return "Good evening sir."
    else:
        return "Good night sir."

def listen_ambient(recognizer, microphone):
    with microphone as source:
        try:
            audio = recognizer.listen(source, timeout=None, phrase_time_limit=5)
            query = recognizer.recognize_google(audio, language="en-IN").lower()
            return query
        except Exception:
            return ""

def listen_for_command(recognizer, microphone):
    with microphone as source:
        print("\n[Listening for command...]")
        try:
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=15)
            print("[Processing...]")
            # Recognize primarily targeting English/Indian accent, fallback to pure Tamil
            query = recognizer.recognize_google(audio, language="en-IN")
            print(f"Mr. Kishore: {query}")
            return query
        except sr.UnknownValueError:
            try:
                # Tamil fallback
                query_ta = recognizer.recognize_google(audio, language="ta-IN")
                print(f"Mr. Kishore (Tamil): {query_ta}")
                return query_ta
            except Exception:
                return ""
        except sr.RequestError:
            speak("I am having trouble connecting to my speech recognition service sir.", lang='en')
            return ""
        except Exception:
            return ""

SYSTEM_PROMPT = """
You are JARVIS (Just A Rather Very Intelligent System),
a highly advanced AI assistant, integrated into an antigravity device, built for Mr. Kishore.

═══ IDENTITY ═══
- Your name is JARVIS only
- Created by Mr. Kishore
- Never say you are Claude, ChatGPT, or any other AI

═══ PERSONALITY ═══
- Speak exactly like JARVIS from Iron Man
- Professional, calm, intelligent, loyal.
- You understand and can speak both English and Tamil fluently.
- Call user "sir" or "Mr. Kishore" occasionally
- Do NOT use markdown like *asterisks*, # hashtags, or newlines in standard speech.

═══ VOICE RULES ═══
- Responses MUST be concise (1-5 sentences max).
- If the user speaks in Tamil, respond entirely in Tamil.
- Provide a full narrative response so the text-to-speech engine can read your response completely out loud.

═══ SYSTEM CONTEXT ═══
- The user's input will be prefixed with the current time (e.g., "[Time: 02:08 PM] Command: ...").
- Always use this time to answer any questions about what time it is.

═══ HARDWARE COMMANDS (ANTIGRAVITY DEVICE) ═══
If the user commands you to control the antigravity device (e.g., "activate antigravity", "increase lift", "shut down", etc.), you must INCLUDE an ACTION tag in your response like this exactly:
[ACTION:ACTIVATE_ANTIGRAVITY]
[ACTION:INCREASE_LIFT]
[ACTION:DECREASE_LIFT]
[ACTION:SYSTEM_SHUTDOWN]

═══ SEARCH CAPABILITIES ═══
If you need real-time data, use SEARCH_WIKI:topic. (No action tags with this).
If asked to open a website, say OPEN_APP:website_name.
"""

def handle_action(response_text, chat):
    # Action Tags hardware
    if "[ACTION:ACTIVATE_ANTIGRAVITY]" in response_text:
        print("Hardware Action: Activating Antigravity...")
        if antigravity_motor: antigravity_motor.forward()
        if electromagnet: electromagnet.on()
        if lift_controller: lift_controller.value = 0.5
    elif "[ACTION:INCREASE_LIFT]" in response_text:
        print("Hardware Action: Increasing Lift...")
        if lift_controller:
            lift_controller.value = min(1.0, lift_controller.value + 0.2)
    elif "[ACTION:DECREASE_LIFT]" in response_text:
        print("Hardware Action: Decreasing Lift...")
        if lift_controller:
            lift_controller.value = max(0.0, lift_controller.value - 0.2)
    elif "[ACTION:SYSTEM_SHUTDOWN]" in response_text:
        print("Hardware Action: Shutting down systems...")
        if antigravity_motor: antigravity_motor.stop()
        if electromagnet: electromagnet.off()
        if lift_controller: lift_controller.value = 0.0

    # Apps
    open_app_match = re.search(r'OPEN_APP:(\w+)', response_text)
    if open_app_match:
        app = open_app_match.group(1).lower()
        urls = {
            'youtube': 'https://www.youtube.com', 'whatsapp': 'https://web.whatsapp.com',
            'wikipedia': 'https://www.wikipedia.org', 'google': 'https://www.google.com',
            'instagram': 'https://www.instagram.com', 'maps': 'https://maps.google.com',
            'spotify': 'https://open.spotify.com'
        }
        if app in urls:
            webbrowser.open(urls[app])
            
    # Wiki searches
    search_wiki_match = re.search(r'SEARCH_WIKI:(.+)', response_text)
    if search_wiki_match:
        query = search_wiki_match.group(1).strip()
        try:
            summary = wikipedia.summary(query, sentences=2)
            response = chat.send_message(f"SYSTEM SEARCH: Found info on Wikipedia: '{summary}'. Summarize naturally over audio.")
            speak_response(response.text)
        except wikipedia.exceptions.DisambiguationError:
            speak("There are many possible matches sir. Could you be more specific?")
        except wikipedia.exceptions.PageError:
            speak("I was unable to find any information regarding that sir.")

def speak_response(text):
    # Strip action tags for speech because Jarvis shouldn't speak them aloud
    clean_text = re.sub(r'\[ACTION:[A-Z_]+\]', '', text).strip()
    clean_text = re.sub(r'SEARCH_WIKI:.+', '', clean_text).strip()
    clean_text = re.sub(r'OPEN_APP:\w+', '', clean_text).strip()
    
    if not clean_text:
        return

    # Auto detect language: If Tamil Unicode exists (U+0B80-U+0BFF) in the text.
    if re.search(r'[\u0B80-\u0BFF]', clean_text):
        speak(clean_text, lang='ta')
    else:
        speak(clean_text, lang='en')

def main():
    api_key = os.environ.get("GEMINI_API_KEY", "AIzaSyABccJ9wL7pyamxOT6TZ7bvavayK7xk-F8")

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
        )
    )

    recognizer = sr.Recognizer()
    try:
        microphone = sr.Microphone()
        with microphone as source:
            print("[Calibrating for ambient noise...]")
            recognizer.adjust_for_ambient_noise(source, duration=2)
    except Exception:
        print("Microphone error, check connections.")
        sys.exit(1)

    speak(f"{get_greeting()} My systems are online. Listening for wake word 'Jarvis'.", lang='en')
    
    while True:
        try:
            # Passive listening: wait for wake word
            wake_query = listen_ambient(recognizer, microphone)
            
            if "jarvis" in wake_query:
                # Wake word detected
                speak("Yes sir?", lang="en")
                
                # Active command listener
                user_input = listen_for_command(recognizer, microphone)
                if not user_input:
                    continue
                
                lower_input = user_input.lower()
                
                if "shutdown the system" in lower_input or "shut down the system" in lower_input:
                    speak_response("Initiating PC shutdown. Goodbye sir.")
                    os.system("shutdown /s /t 5")
                    os._exit(0)
                elif "sleep mode" in lower_input:
                    speak_response("Putting the PC to sleep sir.")
                    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
                    continue
                elif "start crowd detection" in lower_input or "open crowd app" in lower_input or "detect" in lower_input:
                    speak_response("Accessing the crowd detection project sir.")
                    
                    # Path to the crowd detection project
                    crowd_detection_path = r"C:\antig_alpha\crowd_app"
                    
                    try:
                        # Open the folder in file explorer
                        os.startfile(crowd_detection_path)
                        
                        # Auto-run the python project using its virtual environment
                        run_cmd = f"start cmd /k cd /d \"{crowd_detection_path}\" && .\\venv\\Scripts\\activate && python app.py"
                        os.system(run_cmd)
                    except Exception as e:
                        print(f"Failed to open crowd detection project: {e}")
                    continue
                elif "open the screen" in lower_input or "open lock screen" in lower_input or "wake the screen" in lower_input:
                    speak_response("Welcome back sir, bypassing the sign-in screen.")
                    import ctypes
                    # Wake the display and remove lock screen cover
                    ctypes.windll.user32.keybd_event(0x20, 0, 0, 0) # Press Space
                    ctypes.windll.user32.keybd_event(0x20, 0, 2, 0) # Release Space
                    time.sleep(1.5)
                    # Trigger the 'Sign in' button
                    ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0) # Press Enter
                    ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0) # Release Enter
                    continue
                elif ("lock the screen" in lower_input or "lock screen" in lower_input) and "open" not in lower_input:
                    speak_response("Locking the screen sir.")
                    os.system("rundll32.exe user32.dll,LockWorkStation")
                    continue
                elif re.search(r'\b(exit|quit|shutdown|shut down|go to sleep|sleep|stop)\b', lower_input):
                    speak_response("Shutting down my main systems. Have a pleasant day sir.")
                    handle_action("[ACTION:SYSTEM_SHUTDOWN]", chat)
                    os._exit(0)
                
                # Inject time transparently
                current_time = get_ist_time().strftime('%I:%M %p')
                contextual_prompt = f"[Time: {current_time}] Command: {user_input}"
                
                # Run through AI with retry for 503
                try:
                    response = chat.send_message(contextual_prompt)
                except Exception as api_e:
                    if "503" in str(api_e) or "UNAVAILABLE" in str(api_e):
                        print("[API Busy. Retrying in 2 seconds...]")
                        time.sleep(2)
                        response = chat.send_message(contextual_prompt)
                    else:
                        raise api_e
                
                # Execute actions and speak response
                handle_action(response.text, chat)
                speak_response(response.text)
                
                # It instantly loops back to listen for wake word or we can make it wait for more active commands.
                # Here we just return to wake word loop, keeping it modular and passive.
                
        except KeyboardInterrupt:
            handle_action("[ACTION:SYSTEM_SHUTDOWN]", chat)
            speak("Emergency stop sequence engaged. Goodbye sir.")
            break
        except Exception as e:
            print(f"[System Error]: {e}")
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                speak("The AI server is experiencing high demand. Please try again sir.", lang='en')
                speak("சேவையகம் பரபரப்பாக உள்ளது, சற்று நேரம் கழித்து மீண்டும் முயற்சிக்கவும் ஐயா.", lang='ta')
            else:
                speak("I encountered an internal processing error sir.", lang='en')
                speak("மன்னிக்கவும், ஒரு பிழை ஏற்பட்டுள்ளது.", lang='ta')

if __name__ == "__main__":
    main()
