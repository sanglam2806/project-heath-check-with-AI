"""
Standalone smoke test: does the configured "deep" model/gateway (the
Model Configuration page's "deep" settings if saved, else
OPENAI_API_KEY_DEEP / OPENAI_BASE_URL_DEEP / OPENAI_MODEL_DEEP in
server/.env -- see model_config.py -- the same model deep_dive_agent.py's
Layer 4 uses) actually support OpenAI-style tool-calling (the
`tools=`/`tool_choice` chat completion params)?

Sends one trivial request with a single fake tool ("get_weather") and a
prompt that should obviously trigger it, then reports whether the response
came back with `tool_calls` populated. Does not touch any real
repo/ticket/DB -- safe to run standalone.

Usage:
    cd server
    python check_tool_calling_support.py
"""
import json
import sys

import model_config
from openai import OpenAI

_settings = model_config.get_llm_settings()
OPENAI_API_KEY_DEEP = _settings["api_key_deep"]
OPENAI_BASE_URL_DEEP = _settings["base_url_deep"]
OPENAI_MODEL_DEEP = _settings["model_deep"]

_TEST_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name."}},
            "required": ["city"],
        },
    },
}


def main() -> int:
    print(f"Base URL : {OPENAI_BASE_URL_DEEP}")
    print(f"Model    : {OPENAI_MODEL_DEEP}")
    print(f"API key  : {'set' if OPENAI_API_KEY_DEEP and OPENAI_API_KEY_DEEP != 'ollama' else '(default/unset)'}")
    print("-" * 60)

    client = OpenAI(api_key=OPENAI_API_KEY_DEEP, base_url=OPENAI_BASE_URL_DEEP)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL_DEEP,
            messages=[
                {
                    "role": "user",
                    "content": "What is the weather like in Hanoi right now? Use the get_weather tool to find out.",
                }
            ],
            tools=[_TEST_TOOL],
            tool_choice="auto",
            temperature=0.2,
            max_tokens=512,
        )
    except Exception as exc:
        print("RESULT: FAILED -- the API call itself raised an exception.")
        print(f"Exception: {type(exc).__name__}: {exc}")
        print()
        print("This usually means the gateway/model rejects the `tools`/`tool_choice`")
        print("parameters outright (unsupported request shape), or there's a network/")
        print("auth problem unrelated to tool-calling. Layer 4 (deep_dive_agent.py) will")
        print("fail every call the same way and silently fall back to the prior result.")
        return 1

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []

    print("Raw message.content:")
    print(repr(message.content))
    print()
    print("Raw message.tool_calls:")
    print(json.dumps(
        [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
            for tc in tool_calls
        ],
        indent=2,
    ) if tool_calls else "(none)")
    print("-" * 60)

    if tool_calls and any(tc.function.name == "get_weather" for tc in tool_calls):
        print("RESULT: SUPPORTED -- the model correctly returned a tool_call for get_weather.")
        print("Layer 4's tool-calling loop (deep_dive_agent.py) should work with this model.")
        return 0

    print("RESULT: NOT CONFIRMED -- the call succeeded but the model did NOT call the tool.")
    print("Either it doesn't support tool-calling (ignored `tools` and just answered in")
    print("plain text), or it needs a more forceful prompt/tool_choice. Layer 4 relies on")
    print("`submit_result` being called as a tool -- if this model never calls tools, every")
    print("deep-dive will run out of rounds and silently fall back to the prior result.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
