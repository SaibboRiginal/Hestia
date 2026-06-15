# Hestia-Telegram — Test Cases

> Per-service test plan. Root index: `TESTING.md`

## PHASE 2 — Telegram: Every User Path (🔴 CRITICAL — The Only Client)

### 2.1 Message Formatting Contract (`message_format.py`)

**File:** `Hestia-Telegram/tests/test_message_format.py`
**Markers:** `format, unit`

| # | Test Case | Status |
|---|-----------|--------|
| 2.1.1 | `test_format_for_telegram_converts_bold` | ⬜ |
| 2.1.2 | `test_format_for_telegram_converts_italic` | ⬜ |
| 2.1.3 | `test_format_for_telegram_converts_headings` | ⬜ |
| 2.1.4 | `test_format_for_telegram_converts_markdown_link` | ⬜ |
| 2.1.5 | `test_format_for_telegram_converts_bullet_dash` | ⬜ |
| 2.1.6 | `test_format_for_telegram_converts_bullet_asterisk` | ⬜ |
| 2.1.7 | `test_format_for_telegram_converts_code_block` | ⬜ |
| 2.1.8 | `test_format_for_telegram_escapes_html_entities` | ⬜ |
| 2.1.9 | `test_format_for_telegram_no_markdown_leaks_in_output` | ⬜ |
| 2.1.10 | `test_format_for_telegram_prettify_link_with_good_label` | ⬜ |
| 2.1.11 | `test_format_for_telegram_prettify_link_url_label_replaced` | ⬜ |
| 2.1.12 | `test_split_long_message_short_stays_single` | ⬜ |
| 2.1.13 | `test_split_long_message_splits_at_double_newline` | ⬜ |
| 2.1.14 | `test_split_long_message_never_in_sentence` | ⬜ |
| 2.1.15 | `test_split_long_message_pre_tag_unclosed` | ⬜ |
| 2.1.16 | `test_build_delivery_messages_link_block_split` | ⬜ |
| 2.1.17 | `test_build_delivery_messages_no_link_keeps_together` | ⬜ |
| 2.1.18 | `test_build_delivery_messages_signal_minimal_style` | ⬜ |
| 2.1.19 | `test_build_delivery_messages_signal_compact_style` | ⬜ |
| 2.1.20 | `test_build_delivery_messages_signal_rich_style` | ⬜ |
| 2.1.21 | `test_build_delivery_messages_html_input_not_double_escaped` | ⬜ |
| 2.1.22 | `test_build_delivery_messages_markdown_input_converted` | ⬜ |
| 2.1.23 | `test_build_chat_messages_oracle_reply` | ⬜ |
| 2.1.24 | `test_signal_family_memory` | ⬜ |
| 2.1.25 | `test_signal_family_subscription` | ⬜ |
| 2.1.26 | `test_signal_style_override_per_family` | ⬜ |

### 2.2 Command Catalog (`command_catalog.py`)

**File:** `Hestia-Telegram/tests/test_command_catalog.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 2.2.1 | `test_local_commands_are_valid_structs` | ⬜ |
| 2.2.2 | `test_local_commands_have_titles` | ⬜ |
| 2.2.3 | `test_local_command_names_snake_case` | ⬜ |
| 2.2.4 | `test_local_command_response_modes_valid` | ⬜ |
| 2.2.5 | `test_no_duplicate_command_names` | ⬜ |
| 2.2.6 | `test_hub_commands_merged_no_collision` | ⬜ |

### 2.3 Bot Handlers (`telegram_runtime.py`, `chat_service.py`)

**File:** `Hestia-Telegram/tests/test_bot_handlers.py`
**Markers:** `unit, api`

| # | Test Case | Status |
|---|-----------|--------|
| 2.3.1 | `test_on_welcome_authorized` | ⬜ |
| 2.3.2 | `test_on_welcome_unauthorized` | ⬜ |
| 2.3.3 | `test_on_clear_clears_session` | ⬜ |
| 2.3.4 | `test_on_chat_plain_text_routed_to_oracle` | ⬜ |
| 2.3.5 | `test_on_chat_oracle_reply_html_sent` | ⬜ |
| 2.3.6 | `test_on_chat_oracle_reply_never_markdown` | ⬜ |
| 2.3.7 | `test_on_chat_long_reply_split_into_parts` | ⬜ |
| 2.3.8 | `test_on_chat_oracle_stream_typing_indicators` | ⬜ |
| 2.3.9 | `test_on_file_photo_forwarded_to_oracle_document` | ⬜ |
| 2.3.10 | `test_on_file_pdf_forwarded_to_oracle_document` | ⬜ |
| 2.3.11 | `test_on_file_audio_forwarded_to_oracle_document` | ⬜ |
| 2.3.12 | `test_on_file_unknown_type_graceful` | ⬜ |
| 2.3.13 | `test_on_confirmation_approve` | ⬜ |
| 2.3.14 | `test_on_confirmation_cancel` | ⬜ |
| 2.3.15 | `test_on_confirmation_cmd_approve` | ⬜ |
| 2.3.16 | `test_on_arg_picker_callback` | ⬜ |
| 2.3.17 | `test_on_run_command_callback` | ⬜ |
| 2.3.18 | `test_on_set_picker_callback` | ⬜ |
| 2.3.19 | `test_on_cancel_flow_callback` | ⬜ |
| 2.3.20 | `test_on_calendar_step_callback` | ⬜ |
| 2.3.21 | `test_on_doc_callback` | ⬜ |
| 2.3.22 | `test_on_group_nav_callback` | ⬜ |
| 2.3.23 | `test_unauthorized_user_all_paths_blocked` | ⬜ |

### 2.4 Command Execution (`command_service.py`, `executor.py`)

**File:** `Hestia-Telegram/tests/test_command_execution.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 2.4.1 | `test_execute_local_command_start` | ⬜ |
| 2.4.2 | `test_execute_local_command_help` | ⬜ |
| 2.4.3 | `test_execute_local_command_settings` | ⬜ |
| 2.4.4 | `test_execute_local_command_reset_settings` | ⬜ |
| 2.4.5 | `test_execute_hub_command_get_request` | ⬜ |
| 2.4.6 | `test_execute_hub_command_post_request` | ⬜ |
| 2.4.7 | `test_execute_hub_command_oracle_natural_response` | ⬜ |
| 2.4.8 | `test_execute_hub_command_direct_response` | ⬜ |
| 2.4.9 | `test_execute_hub_command_hub_down_graceful` | ⬜ |
| 2.4.10 | `test_execute_hub_command_result_never_raw_json` | ⬜ |
| 2.4.11 | `test_render_direct_command_output_html` | ⬜ |
| 2.4.12 | `test_build_commands_keyboard_grouped` | ⬜ |
| 2.4.13 | `test_route_command_from_metadata_get` | ⬜ |
| 2.4.14 | `test_route_command_args_substituted` | ⬜ |
| 2.4.15 | `test_calendar_wizard_flow_step1` | ⬜ |
| 2.4.16 | `test_calendar_wizard_flow_complete` | ⬜ |
| 2.4.17 | `test_refresh_command_registry_deduplicated` | ⬜ |
| 2.4.18 | `test_setup_commands_debounced` | ⬜ |
| 2.4.19 | `test_setup_commands_429_absorbed` | ⬜ |

### 2.5 Control API (`control_service.py`)

**File:** `Hestia-Telegram/tests/test_control_api.py`
**Markers:** `api`

| # | Test Case | Status |
|---|-----------|--------|
| 2.5.1 | `test_control_api_health` | ⬜ |
| 2.5.2 | `test_control_api_registry_push_webhook` | ⬜ |
| 2.5.3 | `test_control_api_registry_push_debounce` | ⬜ |

### 2.6 Formatters (`formatters.py`)

**File:** `Hestia-Telegram/tests/test_formatters.py`
**Markers:** `format, unit`

| # | Test Case | Status |
|---|-----------|--------|
| 2.6.1 | `test_format_command_output_real_estate` | ⬜ |
| 2.6.2 | `test_format_command_output_no_nd` | ⬜ |
| 2.6.3 | `test_format_command_output_emoji_count` | ⬜ |
| 2.6.4 | `test_format_command_output_link_becomes_anchor` | ⬜ |
| 2.6.5 | `test_proactive_alert_reads_natural` | ⬜ |
