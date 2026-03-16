import json
import os
import uuid
from typing import Any


def load_sessions(state_file: str) -> dict[str, str]:
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            return {}
    return {}


def save_sessions(state_file: str, sessions: dict[str, str]):
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as handle:
        json.dump(sessions, handle, indent=4)


def get_session(state_file: str, chat_id: str) -> str:
    normalized_chat_id = str(chat_id)
    sessions = load_sessions(state_file)
    if normalized_chat_id not in sessions:
        sessions[normalized_chat_id] = str(uuid.uuid4())
        save_sessions(state_file, sessions)
    return sessions[normalized_chat_id]


def reset_session(state_file: str, chat_id: str):
    normalized_chat_id = str(chat_id)
    sessions = load_sessions(state_file)
    sessions[normalized_chat_id] = str(uuid.uuid4())
    save_sessions(state_file, sessions)


def load_session_settings(settings_file: str) -> dict[str, dict[str, Any]]:
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            return {}
    return {}


def save_session_settings(settings_file: str, settings: dict[str, dict[str, Any]]):
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    with open(settings_file, "w") as handle:
        json.dump(settings, handle, indent=4)


def get_session_settings(settings_file: str, chat_id: str) -> dict[str, Any]:
    all_settings = load_session_settings(settings_file)
    return all_settings.get(str(chat_id), {})


def set_session_setting(settings_file: str, chat_id: str, key: str, value: str):
    normalized_key = str(key or "").strip().lower()
    normalized_value = str(value or "").strip()
    if not normalized_key:
        return

    all_settings = load_session_settings(settings_file)
    chat_settings = all_settings.get(str(chat_id), {})
    chat_settings[normalized_key] = normalized_value
    all_settings[str(chat_id)] = chat_settings
    save_session_settings(settings_file, all_settings)


def reset_session_settings(settings_file: str, chat_id: str):
    all_settings = load_session_settings(settings_file)
    if str(chat_id) in all_settings:
        all_settings.pop(str(chat_id), None)
        save_session_settings(settings_file, all_settings)


def build_client_instructions_for_chat(settings_file: str, base_instructions: str, chat_id: str) -> str:
    instructions = [base_instructions]
    settings = get_session_settings(settings_file, str(chat_id))
    for key, value in settings.items():
        instructions.append(f"{key}: {value}")
    return "\n".join([part for part in instructions if str(part).strip()])
