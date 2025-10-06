"""Minimal interactive runner."""

import sys
sys.path.insert(0, '.')  # ensure top-level is on sys.path

from src.weather_assistant import WeatherAssistant

def main():
    print("Xweather + OpenAI (lean) — type a question, or 'exit' to quit.\n")
    bot = WeatherAssistant(verbose=True)
    while True:
        try:
            q = input("You: ").strip()
            if q.lower() in {"exit", "quit", "q"}:
                print("Bye.")
                break
            if not q:
                continue
            ans = bot.ask(q)
            print("\nAssistant:", ans, "\n")
        except KeyboardInterrupt:
            print("\nBye.")
            break
        except Exception as e:
            print(f"\nError: {e}\n")

if __name__ == "__main__":
    main()
