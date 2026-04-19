# Backward-compatibility shim for command_service.
# All logic has been moved to focused modules.

from telegram_bot.services.router import (
    extract_required_args,
    parse_command_arguments,
    resolve_template,
    route_command_from_metadata,
    route_service_command,
)

from telegram_bot.services.formatters import (
    format_active_preferences,
    format_command_payload_with_oracle,
    format_documents_list,
    format_recent_alerts,
    format_scout_listings,
    format_subscriptions_list,
    render_direct_command_output,
    strip_formatter_intro,
)

from telegram_bot.services.calendar_wizard import (
    _AFFIRMATIVE,
    _NEGATIVE,
    execute_calendar_create_confirm,
    handle_calendar_step_callback,
    handle_calendar_wizard_text,
)

from telegram_bot.services.registry import (
    build_commands_keyboard,
    build_group_commands_keyboard,
    discover_commands_from_hub,
    fetch_registry_revision,
    get_grouped_commands,
    get_local_command_items,
    get_visible_command_items,
    refresh_command_registry,
    register_telegram_service,
    setup_commands,
    watch_command_registry_loop,
)

from telegram_bot.services.executor import (
    COMMAND_ALIASES,
    TONE_PRESETS,
    _execute_delete_document,
    execute_direct_command,
    execute_local_command,
    handle_doc_callback,
    handle_group_callback,
    open_arg_picker,
    prompt_clear_confirmation,
    prompt_set_parameter_picker,
    prompt_tone_presets,
    start_text_input_flow,
)
