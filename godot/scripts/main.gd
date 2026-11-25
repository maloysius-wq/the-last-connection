extends Control
## Surveillance terminal: typed/voice messages, local Eli speech, authoritative world actions.

const BRIDGE_URL := "http://127.0.0.1:8765"
const SAVE_PATH := "user://tlc_save.cfg"

func _save_path() -> String:
    # Exported portable builds keep progress next to the game on D: rather than AppData on C:.
    if OS.has_feature("standalone"):
        var folder := OS.get_executable_path().get_base_dir().path_join("user_data")
        var error := DirAccess.make_dir_recursive_absolute(folder)
        if error == OK:
            return folder.path_join("tlc_save.cfg")
        push_warning("Cannot create portable save directory; using standard user storage")
    return SAVE_PATH
# One append-only transcript per session. Keep the complete displayed dialogue
# across game restarts so a later diagnostic ZIP includes earlier turns too.
# These text files live alongside the portable save, never in a cloud service.
func _transcript_path() -> String:
    return _save_path().get_base_dir().path_join(session_id + ".transcript.txt")


func _load_transcript() -> void:
    var path := _transcript_path()
    if not FileAccess.file_exists(path):
        return
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        push_warning("Couldn't restore conversation transcript: " + path)
        return
    var transcript := file.get_as_text()
    file.close()
    if not transcript.is_empty():
        # Loading is display-only: do not append the old lines to disk again
        # or replay all of Eli's earlier voice lines.
        log_view.append_text(transcript)


func _append_transcript(line: String) -> void:
    var path := _transcript_path()
    var existed := FileAccess.file_exists(path)
    var file := FileAccess.open(path, FileAccess.READ_WRITE if existed else FileAccess.WRITE)
    if file == null:
        push_warning("Couldn't save conversation transcript: " + path)
        return
    if existed:
        file.seek_end()
    file.store_string(line)
    file.close()


const WorldScript = preload("res://scripts/world.gd")

var world # Concrete world.gd instance; dynamic type allows its custom signals and methods.
var input: LineEdit
var log_view: RichTextLabel
var status: Label
var send_button: Button
var http: HTTPRequest
var update_http: HTTPRequest
var update_button: Button
var update_dialog: ConfirmationDialog
var exit_dialog: ConfirmationDialog
var exit_authorized := false
var export_http: HTTPRequest
var export_button: Button
var export_busy := false
var update_stage := ""
var available_update_tag := ""
var session_id: String
var request_stage := "idle"
var action_context := {"action": "", "target": ""}
var queued_actions: Array[Dictionary] = []
var queue_index := 0
var last_step_succeeded := false

# Offline voice uses separate HTTP requests; it NEVER bypasses _submit(), the
# existing semantic plan review, or Godot's authoritative action queue.
var voice_status_http: HTTPRequest
var voice_stt_http: HTTPRequest
var voice_tts_http: HTTPRequest
var mic_player: AudioStreamPlayer
var mic_recorder: AudioEffectRecord
var eli_voice_player: AudioStreamPlayer
var microphone_button: Button
var voice_mute_button: CheckButton
var voice_text_only_button: CheckButton
var voice_skip_button: Button
var sensitivity_slider: HSlider
var volume_slider: HSlider
var audio_link_status: Label
var stt_ready := false
var tts_ready := false
var microphone_recording := false
var transcribing := false
var voice_speaking_queue: Array[Dictionary] = []
var tts_pending := false
var voice_buffer: Array[AudioStreamWAV] = []
var voice_epoch := 0
var voice_request_epoch := 0
var voice_request_started := 0
var voice_profile := "default"
var voice_threads := 0
var voice_engine := "auto"
var voice_fast := true
var voice_studio: Window
var voice_profiles: OptionButton
var voice_thread_control: SpinBox
var voice_engine_control: OptionButton
var voice_fast_control: CheckButton
var voice_emotion_control: OptionButton
var voice_benchmark_label: Label
var voice_import_dialog: FileDialog
var voice_status_data: Dictionary = {}
var voice_benchmark := false
var voice_muted := false
var text_only := false
var microphone_sensitivity := 0.35
var voice_volume := 0.80
var microphone_started_ms := 0
const MAX_RECORD_MS := 15000
const MIC_BUS := "TLC_MicrophoneCapture"

func _ready() -> void:
    _build_ui()
    _load_save()
    _setup_voice()
    http = HTTPRequest.new()
    http.timeout = 310.0
    add_child(http)
    http.request_completed.connect(_on_http_completed)
    update_http = HTTPRequest.new()
    update_http.timeout = 30.0
    add_child(update_http)
    update_http.request_completed.connect(_on_update_response)
    export_http = HTTPRequest.new()
    export_http.timeout = 30.0
    add_child(export_http)
    export_http.request_completed.connect(_on_session_exported)
    update_dialog = ConfirmationDialog.new()
    update_dialog.title = "Update The Last Connection?"
    update_dialog.confirmed.connect(_install_update)
    update_dialog.canceled.connect(_on_update_dialog_dismissed)
    add_child(update_dialog)
    # Leaving the live camera is irreversible. Only a physical exit that
    # would ACTUALLY succeed prompts for confirmation; inspecting or testing
    # a locked door remains ordinary frictionless play.
    exit_dialog = ConfirmationDialog.new()
    exit_dialog.title = "Have Eli leave the room?"
    exit_dialog.dialog_text = ("The exit is unlocked. Opening it will make Eli "
        + "leave the camera view and end room interactions. Proceed?")
    exit_dialog.ok_button_text = "OPEN & EXIT"
    exit_dialog.confirmed.connect(_on_exit_confirmed)
    exit_dialog.canceled.connect(_on_exit_cancelled)
    add_child(exit_dialog)
    world.action_finished.connect(_on_world_action_finished)
    _message("SYSTEM", "Connected to CAM 01. Type to talk, hold ALT+V (or V outside the editor), or use HOLD TO TALK.")
    _message("SYSTEM", "Eli's speech and microphone transcription run offline. Subtitles remain available.")
    call_deferred("_restore_input_focus")
    call_deferred("_refocus_on_next_frame")

func _build_ui() -> void:
    var background := ColorRect.new()
    background.color = Color("0b1017")
    background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    add_child(background)

    var outer := HBoxContainer.new()
    outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    outer.add_theme_constant_override("separation", 10)
    outer.offset_left = 14
    outer.offset_top = 14
    outer.offset_right = -14
    outer.offset_bottom = -14
    add_child(outer)

    var left := VBoxContainer.new()
    left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    left.size_flags_stretch_ratio = 2.0
    outer.add_child(left)
    var cam_title := Label.new()
    cam_title.text = "● CAM 01   /   MAINTENANCE CHAMBER   /   LIVE"
    cam_title.add_theme_color_override("font_color", Color("aec7d5"))
    left.add_child(cam_title)

    var monitor := SubViewportContainer.new()
    monitor.stretch = true
    monitor.size_flags_vertical = Control.SIZE_EXPAND_FILL
    left.add_child(monitor)
    var viewport := SubViewport.new()
    viewport.size = Vector2i(960, 600)
    viewport.own_world_3d = true
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    monitor.add_child(viewport)
    world = WorldScript.new()
    viewport.add_child(world)

    audio_link_status = Label.new()
    audio_link_status.text = "AUDIO LINK: CONNECTING       ◦       VIDEO FEED: ACTIVE"
    audio_link_status.add_theme_color_override("font_color", Color("7e9ba9"))
    left.add_child(audio_link_status)

    var right := VBoxContainer.new()
    right.custom_minimum_size.x = 300
    right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    right.size_flags_stretch_ratio = 1.0
    outer.add_child(right)
    var header := Label.new()
    header.text = "INCOMING CHANNEL / ELI"
    header.add_theme_color_override("font_color", Color("d4e1eb"))
    right.add_child(header)
    log_view = RichTextLabel.new()
    log_view.bbcode_enabled = false
    log_view.scroll_following = true
    log_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
    right.add_child(log_view)

    status = Label.new()
    status.text = "Ready"
    status.add_theme_color_override("font_color", Color("a0b2c5"))
    right.add_child(status)
    input = LineEdit.new()
    input.placeholder_text = "Talk to Eli..."
    input.text_submitted.connect(_submit)
    # Retain keyboard focus without stealing mouse clicks on other controls.
    right.add_child(input)
    send_button = Button.new()
    send_button.text = "TRANSMIT"
    send_button.focus_mode = Control.FOCUS_NONE
    send_button.pressed.connect(_send_pressed)
    right.add_child(send_button)
    var voice_row := HBoxContainer.new()
    voice_row.add_theme_constant_override("separation", 5)
    right.add_child(voice_row)
    microphone_button = Button.new()
    microphone_button.text = "HOLD TO TALK"
    microphone_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    microphone_button.focus_mode = Control.FOCUS_NONE
    microphone_button.disabled = true
    microphone_button.button_down.connect(_start_microphone_recording)
    microphone_button.button_up.connect(_stop_microphone_recording)
    voice_row.add_child(microphone_button)
    voice_mute_button = CheckButton.new()
    voice_mute_button.text = "MUTE"
    voice_mute_button.focus_mode = Control.FOCUS_NONE
    voice_mute_button.toggled.connect(_on_voice_muted)
    voice_row.add_child(voice_mute_button)
    voice_text_only_button = CheckButton.new()
    voice_text_only_button.text = "TEXT ONLY"
    voice_text_only_button.focus_mode = Control.FOCUS_NONE
    voice_text_only_button.toggled.connect(_on_text_only)
    voice_row.add_child(voice_text_only_button)
    var setting_row := HBoxContainer.new()
    setting_row.add_theme_constant_override("separation", 6)
    right.add_child(setting_row)
    var sensitivity_label := Label.new()
    sensitivity_label.text = "MIC"
    setting_row.add_child(sensitivity_label)
    sensitivity_slider = HSlider.new()
    sensitivity_slider.custom_minimum_size.x = 58
    sensitivity_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    sensitivity_slider.min_value = 0.0
    sensitivity_slider.max_value = 1.0
    sensitivity_slider.step = 0.05
    sensitivity_slider.value_changed.connect(_on_sensitivity_changed)
    setting_row.add_child(sensitivity_slider)
    var volume_label := Label.new()
    volume_label.text = "VOICE"
    setting_row.add_child(volume_label)
    volume_slider = HSlider.new()
    volume_slider.custom_minimum_size.x = 58
    volume_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    volume_slider.min_value = 0.0
    volume_slider.max_value = 1.0
    volume_slider.step = 0.05
    volume_slider.value_changed.connect(_on_voice_volume_changed)
    setting_row.add_child(volume_slider)
    voice_skip_button = Button.new()
    voice_skip_button.text = "SKIP"
    voice_skip_button.focus_mode = Control.FOCUS_NONE
    voice_skip_button.pressed.connect(_skip_eli_voice)
    setting_row.add_child(voice_skip_button)
    var studio_button := Button.new()
    studio_button.text = "VOICE STUDIO"
    studio_button.focus_mode = Control.FOCUS_NONE
    studio_button.pressed.connect(_open_voice_studio)
    right.add_child(studio_button)
    _build_voice_studio()
    update_button = Button.new()
    update_button.text = "CHECK FOR UPDATES"
    update_button.focus_mode = Control.FOCUS_NONE
    update_button.pressed.connect(_check_for_updates)
    right.add_child(update_button)
    export_button = Button.new()
    export_button.text = "EXPORT CONVERSATION + LOGS ZIP"
    export_button.focus_mode = Control.FOCUS_NONE
    export_button.pressed.connect(_export_current_session)
    right.add_child(export_button)
    var new_game := Button.new()
    new_game.text = "NEW SESSION / RESET ROOM"
    new_game.focus_mode = Control.FOCUS_NONE
    new_game.pressed.connect(_new_game)
    right.add_child(new_game)

func _message(speaker: String, text: String, emotion: String = "calm") -> void:
    var line := "[" + speaker + "] " + text + "\n\n"
    log_view.append_text(line)
    if not session_id.is_empty():
        _append_transcript(line)
    if speaker == "ELI":
        _queue_eli_speech(text, emotion)

func _send_pressed() -> void:
    _submit(input.text)
    # Buttons take keyboard focus on a mouse click. Return it after the click
    # completes, not synchronously while the mouse is still held down.
    call_deferred("_restore_input_focus")

func _submit(message: String) -> void:
    var trimmed := message.strip_edges()
    if trimmed.is_empty() or request_stage != "idle" or world.busy or transcribing:
        return
    if trimmed.length() > 600:
        _message("SYSTEM", "Message is too long (maximum 600 characters).")
        return
    input.clear()
    _message("YOU", trimmed)
    var body := {"session_id": session_id, "player_text": trimmed, "world": world.snapshot()}
    _request("/api/decide", body, "decide")
    call_deferred("_restore_input_focus")

func _request(path: String, body: Dictionary, stage: String) -> void:
    request_stage = stage
    status.text = "Eli is thinking..." if stage == "decide" else "Saving the observation..."
    send_button.disabled = true
    # Keep the editor usable while the AI responds. The player can compose
    # the next message, but _submit refuses to transmit until Eli is ready.
    var code := http.request(BRIDGE_URL + path,
        PackedStringArray(["Content-Type: application/json"]),
        HTTPClient.METHOD_POST, JSON.stringify(body))
    if code != OK:
        _message("SYSTEM", "Unable to send request. Code: " + str(code))
        if not queued_actions.is_empty():
            _message("SYSTEM", "Sequence cancelled because the action outcome could not be recorded.")
        _idle()

func _on_http_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
        var detail := body.get_string_from_utf8()
        _message("SYSTEM", "AI bridge error (HTTP " + str(response_code) + "): " + detail.left(350))
        if not queued_actions.is_empty():
            _message("SYSTEM", "The remaining actions were cancelled because the bridge failed.")
        _idle()
        return
    var response = JSON.parse_string(body.get_string_from_utf8())
    if typeof(response) != TYPE_DICTIONARY:
        _message("SYSTEM", "Invalid response from the AI bridge. Sequence cancelled.")
        _idle()
        return

    if request_stage == "outcome" and not queued_actions.is_empty():
        # An actual world exit is TERMINAL regardless of any remaining model
        # steps. React to the successful escape before ending the queue.
        if world.escaped and last_step_succeeded:
            var escape_reply := str(response.get("speech", ""))
            if not escape_reply.strip_edges().is_empty():
                _message("ELI", escape_reply)
            if queue_index + 1 < queued_actions.size():
                _message("SYSTEM", "Eli left the camera view. Remaining room steps were not attempted.")
            _idle()
            return
        # The engine has finished and the local bridge recorded this exact
        # outcome. Do not continue a failed or unrecorded step.
        if not last_step_succeeded:
            var failed_reply := str(response.get("speech", ""))
            if not failed_reply.strip_edges().is_empty():
                _message("ELI", failed_reply, str(response.get("emotion", "calm")))
            if queued_actions.size() > 1:
                _message("SYSTEM", "Sequence stopped at step " + str(queue_index + 1) +
                    " of " + str(queued_actions.size()) +
                    ". Later steps were NOT attempted.")
            _idle()
            return
        if queue_index + 1 < queued_actions.size():
            queue_index += 1
            _start_queued_action()
            return
        var final_reply := str(response.get("speech", ""))
        if not final_reply.strip_edges().is_empty():
            _message("ELI", final_reply, str(response.get("emotion", "calm")))
        if queued_actions.size() > 1:
            _message("SYSTEM", "Sequence complete: " + str(queued_actions.size()) +
                " of " + str(queued_actions.size()) + " steps confirmed.")
        _idle()
        return

    # Engine capability/data failures are SYSTEM diagnostics, not fabricated
    # objections coming from Eli. His model didn't necessarily refuse.
    if request_stage == "decide":
        var goal_status := str(response.get("status", "")).strip_edges()
        if not goal_status.is_empty():
            _message("SYSTEM", goal_status.left(320))

    # No synthetic spoken placeholder when the local model couldn't
    # ground a reply. The authoritative OBSERVATION still remains visible.
    var eli_reply := str(response.get("speech", ""))
    if not eli_reply.strip_edges().is_empty():
        _message("ELI", eli_reply, str(response.get("emotion", "calm")))
    if request_stage == "decide":
        var plan_value: Variant = response.get("actions", [])
        if typeof(plan_value) == TYPE_ARRAY and not plan_value.is_empty():
            if plan_value.size() > 5:
                _message("SYSTEM", "The action sequence is too long. Nothing was attempted.")
                _idle()
                return
            var valid := true
            for step in plan_value:
                if typeof(step) != TYPE_DICTIONARY or not _valid_queue_step(step):
                    valid = false
                    break
            if not valid:
                _message("SYSTEM", "Invalid action sequence from bridge. Nothing was attempted.")
                _idle()
                return
            for step in plan_value:
                queued_actions.append({
                    "action": str(step.get("action", "")),
                    "target": str(step.get("target", "")),
                    "argument": str(step.get("argument", ""))
                })
            queue_index = 0
            _start_queued_action()
            return
        # Backward compatibility with earlier bridge versions: one action.
        var one_action: Dictionary = {
            "action": str(response.get("action", "wait")),
            "target": str(response.get("target", "")),
            "argument": str(response.get("argument", ""))
        }
        if one_action["action"] != "wait":
            if not _valid_queue_step(one_action):
                _message("SYSTEM", "Invalid physical action from bridge. Nothing was attempted.")
                _idle()
                return
            queued_actions = [one_action]
            queue_index = 0
            _start_queued_action()
            return
    _idle()


func _valid_queue_step(step: Dictionary) -> bool:
    # The room owns the goal capabilities; the interface does NOT maintain
    # a second, competing action vocabulary or player-phrase whitelist.
    return bool(world.supports_goal(step))


func _requires_exit_confirmation(step: Dictionary) -> bool:
    # Pure engine-state capability guard. Headless tests can verify it
    # without invoking platform-specific native modal behavior.
    return (str(step.get("action", "")) == "use"
        and str(step.get("target", "")) == "exit_door"
        and world.door_unlocked and not world.escaped
        and not exit_authorized)


func _start_queued_action() -> void:
    if queue_index >= queued_actions.size():
        _idle()
        return
    var step: Dictionary = queued_actions[queue_index]
    if world.escaped:
        _message("SYSTEM", "Eli is outside the camera view. No more room actions can run.")
        _idle()
        return
    if _requires_exit_confirmation(step):
        request_stage = "confirm_exit"
        status.text = "Confirm opening the unlocked exit..."
        exit_dialog.popup_centered()
        return
    request_stage = "action"
    var step_total := queued_actions.size()
    status.text = ("Eli is performing step " + str(queue_index + 1) + "/" +
        str(step_total) + "...") if step_total > 1 else "Eli is moving..."
    action_context = step.duplicate()
    world.perform_goal(step)


func _on_world_action_finished(action: String, target: String, success: bool, description: String) -> void:
    last_step_succeeded = success
    _message("OBSERVATION", description)
    if success:
        _save()
    # Intermediate steps only record truth. Eli speaks naturally after the
    # last successful step or immediately after a failure, avoiding repeated
    # slow GGUF calls and canned replies for each queued movement.
    var should_speak: bool = not success or world.escaped or queue_index + 1 >= queued_actions.size()
    var body := {"session_id": session_id, "action": action, "target": target,
        "success": success, "description": description, "world": world.snapshot(),
        "speak": should_speak}
    _request("/api/outcome", body, "outcome")

func _on_exit_confirmed() -> void:
    if request_stage != "confirm_exit" or queued_actions.is_empty():
        return
    exit_authorized = true
    _start_queued_action()


func _on_exit_cancelled() -> void:
    if request_stage != "confirm_exit":
        return
    _message("SYSTEM", "Eli did not open the exit. The door remains closed.")
    _idle()


func _idle() -> void:
    exit_authorized = false
    queued_actions.clear()
    queue_index = 0
    last_step_succeeded = false
    request_stage = "idle"
    status.text = "Ready"
    send_button.disabled = false
    # Returning to READY must make the editor usable immediately, while an
    # extra frame helps if a UI-layout transition replaces the focus owner.
    _restore_input_focus()
    call_deferred("_refocus_on_next_frame")


func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_WINDOW_FOCUS_IN:
        call_deferred("_restore_input_focus")
    elif what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and microphone_recording:
        _stop_microphone_recording()

func _input(event: InputEvent) -> void:
    if event is InputEventKey:
        var key: InputEventKey = event
        if key.keycode != KEY_V or key.echo or key.ctrl_pressed or key.meta_pressed:
            return
        # Plain V is push-to-talk while the user is NOT editing a message.
        # Alt+V works even with chat focused. Never steal the first V from a
        # message like "Very...", and never shadow Ctrl+V clipboard paste.
        if key.pressed and not microphone_recording:
            if not key.alt_pressed and is_instance_valid(input) and input.has_focus():
                return
            if not key.alt_pressed and is_instance_valid(input) and not input.text.is_empty():
                return
            if _can_record_microphone():
                _start_microphone_recording()
                get_viewport().set_input_as_handled()
        elif not key.pressed and microphone_recording:
            _stop_microphone_recording()
            get_viewport().set_input_as_handled()


func _restore_input_focus() -> void:
    if not is_instance_valid(input) or not input.is_inside_tree():
        return
    # Never steal focus from a modal. In particular, don't bring back the
    # focus_exited callback that interrupted CHECK FOR UPDATES mouse clicks.
    if (is_instance_valid(update_dialog) and update_dialog.visible
            or is_instance_valid(exit_dialog) and exit_dialog.visible):
        return
    input.grab_focus()
    input.caret_column = input.text.length()


func _refocus_on_next_frame() -> void:
    await get_tree().process_frame
    if request_stage == "idle" and update_stage.is_empty():
        _restore_input_focus()


func _unhandled_key_input(event: InputEvent) -> void:
    # Fallback when OS/window focus transitions leave the input looking ready
    # but without a keyboard owner. Preserve the *first* typed character.
    # This is keyboard-only: mouse clicks and update confirmation are untouched.
    if request_stage != "idle" or not update_stage.is_empty():
        return
    if not is_instance_valid(input) or not input.is_inside_tree() or input.has_focus():
        return
    if is_instance_valid(update_dialog) and update_dialog.visible:
        return
    if event is InputEventKey:
        var key: InputEventKey = event
        if not key.pressed or key.echo or key.ctrl_pressed or key.alt_pressed or key.meta_pressed:
            return
        if key.unicode >= 32 and key.unicode != 127:
            input.grab_focus()
            input.insert_text_at_caret(char(key.unicode))
            get_viewport().set_input_as_handled()


func _check_for_updates() -> void:
    if not update_stage.is_empty():
        return
    update_button.disabled = true
    update_button.text = "CHECKING GITHUB..."
    update_stage = "check"
    status.text = "Checking GitHub releases..."
    _message("SYSTEM", "Checking GitHub for a newer Windows game release...")
    var result := update_http.request(BRIDGE_URL + "/api/update/check")
    if result != OK:
        _message("SYSTEM", "Couldn't start update check (error " + str(result) + ").")
        status.text = "Update check failed"
        _update_idle()


func _on_update_dialog_dismissed() -> void:
    call_deferred("_restore_input_focus")


func _install_update() -> void:
    if available_update_tag.is_empty() or request_stage != "idle" or world.busy:
        _message("SYSTEM", "Finish Eli's current action before installing an update.")
        return
    update_stage = "install"
    update_button.disabled = true
    update_button.text = "PREPARING UPDATE..."
    status.text = "Preparing update..."
    var payload := JSON.stringify({"tag": available_update_tag, "confirm": true})
    var headers := PackedStringArray(["Content-Type: application/json", "X-TLC-Update: 1"])
    var result := update_http.request(BRIDGE_URL + "/api/update/request", headers,
        HTTPClient.METHOD_POST, payload)
    if result != OK:
        _message("SYSTEM", "Couldn't request the update (error " + str(result) + ").")
        _update_idle()


func _on_update_response(result: int, response_code: int, _headers: PackedStringArray,
        body: PackedByteArray) -> void:
    var reply = JSON.parse_string(body.get_string_from_utf8())
    if result != HTTPRequest.RESULT_SUCCESS or response_code != 200 or typeof(reply) != TYPE_DICTIONARY:
        var detail := str(reply.get("error", "") if typeof(reply) == TYPE_DICTIONARY else "")
        if detail.is_empty():
            detail = "Couldn't contact the local updater. Check your internet connection."
        _message("SYSTEM", "Update check failed: " + detail.left(250))
        status.text = "GitHub check failed. See the SYSTEM message."
        _update_idle()
        return
    if update_stage == "check":
        if not bool(reply.get("available", false)):
            _message("SYSTEM", "You're on the newest published game version.")
            status.text = "Already up to date"
            _update_idle()
            return
        available_update_tag = str(reply.get("latest", ""))
        var megabytes := int(float(reply.get("size", 0)) / 1000000.0)
        update_dialog.dialog_text = (
            "A new version is available: " + str(reply.get("title", available_update_tag)) +
            "\n\nDownload size: approximately " + str(megabytes) + " MB." +
            "\n\nInstalling will close the game, download and verify the update, preserve saves and model files, then restart." +
            "\n\nInstall this update now?"
        )
        _message("SYSTEM", "A new release is available: " + available_update_tag)
        status.text = "New update available"
        _update_idle()
        update_dialog.popup_centered()
    elif update_stage == "install":
        if bool(reply.get("ok", false)):
            _message("SYSTEM", "Closing the game to install the verified update...")
            status.text = "Installing update"
            _save()
            get_tree().quit()
        else:
            _message("SYSTEM", "The update wasn't accepted. Please try checking again.")
            _update_idle()


func _update_idle() -> void:
    update_stage = ""
    update_button.disabled = false
    update_button.text = "CHECK FOR UPDATES"
    call_deferred("_restore_input_focus")


func _export_folder() -> String:
    var folder := _save_path().get_base_dir().path_join("exports")
    if folder.begins_with("user://"):
        return ProjectSettings.globalize_path(folder)
    return folder


func _export_current_session() -> void:
    if export_busy or session_id.is_empty():
        return
    export_busy = true
    export_button.disabled = true
    export_button.text = "BUILDING SESSION ZIP..."
    # Keep diagnostics aligned with a finished or currently active turn;
    # saving it does not send anything to the internet.
    var transcript := log_view.get_parsed_text()
    var body := JSON.stringify({
        "session_id": session_id,
        "transcript": transcript,
        "world": world.snapshot()
    })
    var code := export_http.request(
        BRIDGE_URL + "/api/session/export",
        PackedStringArray(["Content-Type: application/json", "X-TLC-Export: 1"]),
        HTTPClient.METHOD_POST, body)
    if code != OK:
        _message("SYSTEM", "Couldn't start local conversation ZIP export.")
        _end_export()


func _on_session_exported(result: int, code: int, _headers: PackedStringArray,
        bytes: PackedByteArray) -> void:
    if result != HTTPRequest.RESULT_SUCCESS or code != 200:
        var details = JSON.parse_string(bytes.get_string_from_utf8())
        var error_text := str(details.get("error", "The local export service is unavailable.")
            if typeof(details) == TYPE_DICTIONARY else "The local export service is unavailable.")
        _message("SYSTEM", "ZIP export failed: " + error_text.left(220))
        _end_export()
        return
    if bytes.size() < 30 or bytes[0] != 80 or bytes[1] != 75:
        _message("SYSTEM", "ZIP export failed: the bridge returned an invalid archive.")
        _end_export()
        return
    var folder := _export_folder()
    if DirAccess.make_dir_recursive_absolute(folder) != OK:
        _message("SYSTEM", "ZIP export failed: couldn't create exports folder.")
        _end_export()
        return
    var filename := "TheLastConnection-" + session_id + "-" + str(int(Time.get_unix_time_from_system())) + ".zip"
    var path := folder.path_join(filename)
    var file := FileAccess.open(path, FileAccess.WRITE)
    if file == null:
        _message("SYSTEM", "ZIP export failed: couldn't write to the exports folder.")
        _end_export()
        return
    file.store_buffer(bytes)
    file.close()
    _message("SYSTEM", "Conversation + diagnostic logs saved to: " + path)
    # Open Explorer so the ZIP can be dragged directly into the ChatGPT chat.
    if OS.has_feature("windows"):
        OS.shell_open(folder)
    _end_export()


func _end_export() -> void:
    export_busy = false
    export_button.disabled = false
    export_button.text = "EXPORT CONVERSATION + LOGS ZIP"
    call_deferred("_restore_input_focus")


func _new_game() -> void:
    if request_stage != "idle" or world.busy or export_busy:
        return
    session_id = "eli_" + str(int(Time.get_unix_time_from_system())) + "_" + str(randi_range(1000,9999))
    world.reset_state()
    log_view.clear()
    _save()
    _stop_all_voice()
    _message("SYSTEM", "New session. Eli's room and conversation have been reset.")
    call_deferred("_restore_input_focus")

func _load_save() -> void:
    var cfg := ConfigFile.new()
    if cfg.load(_save_path()) == OK:
        session_id = str(cfg.get_value("session", "id", ""))
        var saved_world: Dictionary = cfg.get_value("world", "state", {})
        world.restore_state(saved_world)
        voice_muted = bool(cfg.get_value("voice", "muted", false))
        text_only = bool(cfg.get_value("voice", "text_only", false))
        microphone_sensitivity = clampf(float(cfg.get_value("voice", "sensitivity", 0.35)), 0.0, 1.0)
        voice_volume = clampf(float(cfg.get_value("voice", "volume", 0.80)), 0.0, 1.0)
        voice_profile = str(cfg.get_value("voice", "profile", "default"))
        voice_threads = clampi(int(cfg.get_value("voice", "threads", 0)), 0, 32)
        voice_engine = str(cfg.get_value("voice", "engine", "auto"))
        voice_fast = bool(cfg.get_value("voice", "fast", true))
        voice_mute_button.set_pressed_no_signal(voice_muted)
        voice_text_only_button.set_pressed_no_signal(text_only)
        sensitivity_slider.set_value_no_signal(microphone_sensitivity)
        volume_slider.set_value_no_signal(voice_volume)
    # Session IDs are used as on-disk transcript basenames. Apply the same
    # strict characters/length boundary as the Python bridge before reading.
    var safe_id := RegEx.new()
    safe_id.compile("^[A-Za-z0-9_-]{1,64}$")
    if safe_id.search(session_id) == null:
        session_id = "eli_" + str(int(Time.get_unix_time_from_system())) + "_" + str(randi_range(1000,9999))
        _save()
    _load_transcript()

func _save() -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("session", "id", session_id)
    cfg.set_value("world", "state", world.export_state())
    cfg.set_value("voice", "muted", voice_muted)
    cfg.set_value("voice", "text_only", text_only)
    cfg.set_value("voice", "sensitivity", microphone_sensitivity)
    cfg.set_value("voice", "volume", voice_volume)
    cfg.set_value("voice", "profile", voice_profile)
    cfg.set_value("voice", "threads", voice_threads)
    cfg.set_value("voice", "engine", voice_engine)
    cfg.set_value("voice", "fast", voice_fast)
    var error := cfg.save(_save_path())
    if error != OK:
        push_warning("Couldn't write save game: " + str(error))


# Voice is optional. There is no cloud fallback and no second input/action path.
# The same transcript is always passed into _submit just like a typed message.
func _setup_voice() -> void:
    voice_status_http = HTTPRequest.new()
    voice_status_http.timeout = 6.0
    add_child(voice_status_http)
    voice_status_http.request_completed.connect(_on_voice_status)
    voice_stt_http = HTTPRequest.new()
    voice_stt_http.timeout = 105.0
    add_child(voice_stt_http)
    voice_stt_http.request_completed.connect(_on_voice_transcription)
    voice_tts_http = HTTPRequest.new()
    voice_tts_http.timeout = 245.0
    add_child(voice_tts_http)
    voice_tts_http.request_completed.connect(_on_eli_wav)
    eli_voice_player = AudioStreamPlayer.new()
    add_child(eli_voice_player)
    eli_voice_player.finished.connect(_play_next_eli_chunk)
    _set_voice_volume()
    var bus_index := AudioServer.get_bus_index(MIC_BUS)
    if bus_index < 0:
        AudioServer.add_bus()
        bus_index = AudioServer.bus_count - 1
        AudioServer.set_bus_name(bus_index, MIC_BUS)
    # Never loop the player's microphone through the speakers.
    AudioServer.set_bus_mute(bus_index, true)
    mic_recorder = AudioEffectRecord.new()
    mic_recorder.format = AudioStreamWAV.FORMAT_16_BITS
    AudioServer.add_bus_effect(bus_index, mic_recorder)
    mic_player = AudioStreamPlayer.new()
    mic_player.stream = AudioStreamMicrophone.new()
    mic_player.bus = MIC_BUS
    add_child(mic_player)
    if text_only:
        audio_link_status.text = "AUDIO LINK: TEXT ONLY       ◦       VIDEO FEED: ACTIVE"
    if voice_status_http.request(BRIDGE_URL + "/api/voice/status") != OK:
        _message("SYSTEM", "Voice engine unavailable. Typing still works.")

func _on_voice_status(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    var voice_name := "local voice"
    if result == HTTPRequest.RESULT_SUCCESS and code == 200:
        var data = JSON.parse_string(body.get_string_from_utf8())
        if typeof(data) == TYPE_DICTIONARY:
            stt_ready = bool(data.get("stt_ready", false))
            tts_ready = bool(data.get("tts_ready", false))
            voice_name = str(data.get("voice", "local voice"))
            voice_status_data = data
            _refresh_voice_profiles()
    microphone_button.disabled = not stt_ready or text_only
    if not text_only:
        audio_link_status.text = ("AUDIO LINK: PUSH TO TALK (V)" if stt_ready
                                 else "AUDIO LINK: TEXT ONLY / MIC UNAVAILABLE") + "       ◦       VIDEO FEED: ACTIVE"
    if stt_ready and tts_ready:
        _message("SYSTEM", "Microphone and Eli's voice ready (" + voice_name + "). Hold V, release to transmit.")
    elif not stt_ready or not tts_ready:
        _message("SYSTEM", "Some offline voice components are unavailable. Text conversation still works.")

func _can_record_microphone() -> bool:
    return (stt_ready and not text_only and not microphone_recording and not transcribing
            and request_stage == "idle" and not world.busy and update_stage.is_empty()
            and not update_dialog.visible)

func _start_microphone_recording() -> void:
    if not _can_record_microphone():
        return
    _skip_eli_voice()
    microphone_recording = true
    microphone_started_ms = Time.get_ticks_msec()
    mic_player.play()
    mic_recorder.set_recording_active(true)
    microphone_button.text = "RECORDING... RELEASE"
    status.text = "Listening to your microphone..."
    audio_link_status.text = "AUDIO LINK: RECORDING       ◦       VIDEO FEED: ACTIVE"

func _process(_delta: float) -> void:
    if microphone_recording and Time.get_ticks_msec() - microphone_started_ms >= MAX_RECORD_MS:
        _stop_microphone_recording()

func _stop_microphone_recording() -> void:
    if not microphone_recording:
        return
    microphone_recording = false
    var duration_ms := Time.get_ticks_msec() - microphone_started_ms
    var recorded: AudioStreamWAV = mic_recorder.get_recording()
    mic_recorder.set_recording_active(false)
    mic_player.stop()
    microphone_button.text = "HOLD TO TALK (V)"
    audio_link_status.text = "AUDIO LINK: PROCESSING       ◦       VIDEO FEED: ACTIVE"
    if duration_ms < 350 or recorded == null:
        _message("SYSTEM", "Hold Alt+V or the microphone button while speaking, then release.")
        _voice_ready()
        return
    var wav_path := _save_path().get_base_dir().path_join(".tlc-mic-temp.wav")
    if recorded.save_to_wav(wav_path) != OK:
        _message("SYSTEM", "Couldn't capture microphone audio. Try typing instead.")
        _voice_ready()
        return
    var samples: PackedByteArray = FileAccess.get_file_as_bytes(wav_path)
    DirAccess.remove_absolute(wav_path)
    if samples.size() < 50 or samples.size() > 6000000:
        _message("SYSTEM", "Microphone recording was empty or too large.")
        _voice_ready()
        return
    transcribing = true
    send_button.disabled = true
    status.text = "Transcribing your voice locally..."
    var payload := JSON.stringify({
        "wav_b64": Marshalls.raw_to_base64(samples),
        "sensitivity": microphone_sensitivity
    })
    var result := voice_stt_http.request(
        BRIDGE_URL + "/api/voice/transcribe",
        PackedStringArray(["Content-Type: application/json"]),
        HTTPClient.METHOD_POST, payload)
    if result != OK:
        transcribing = false
        _message("SYSTEM", "Couldn't send the microphone recording to local speech recognition.")
        _voice_ready()

func _on_voice_transcription(result: int, response_code: int, _headers: PackedStringArray,
        body: PackedByteArray) -> void:
    transcribing = false
    if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
        var reply = JSON.parse_string(body.get_string_from_utf8())
        var detail := str(reply.get("error", "No clear words were recognized.") if
            typeof(reply) == TYPE_DICTIONARY else "Microphone transcription failed.")
        _message("SYSTEM", detail.left(240))
        _voice_ready()
        return
    var decoded = JSON.parse_string(body.get_string_from_utf8())
    if typeof(decoded) != TYPE_DICTIONARY:
        _message("SYSTEM", "Local speech transcription returned invalid data.")
        _voice_ready()
        return
    var words := str(decoded.get("transcript", "")).strip_edges()
    if words.is_empty():
        _message("SYSTEM", "Couldn't hear clear words. Please try again.")
        _voice_ready()
        return
    _voice_ready()
    # One authoritative input path: transcripts are text, not a new engine API.
    _submit(words)

func _voice_ready() -> void:
    if request_stage == "idle" and not world.busy:
        status.text = "Ready"
        send_button.disabled = false
    microphone_button.disabled = text_only or not stt_ready
    audio_link_status.text = ("AUDIO LINK: TEXT ONLY" if text_only else
        "AUDIO LINK: PUSH TO TALK (V)" if stt_ready else
        "AUDIO LINK: MIC UNAVAILABLE") + "       ◦       VIDEO FEED: ACTIVE"
    call_deferred("_restore_input_focus")

# Fast mode sends a short opening clause/sentence, then bounded natural
# chunks. Preserve words and punctuation; never synthesize invented filler.
func _voice_chunks(speech: String, fast: bool) -> Array[String]:
    var parts: Array[String] = []
    var current := ""
    for word in speech.split(" ", false):
        if word.length() > 420:
            if not current.is_empty():
                parts.append(current)
                current = ""
            for offset in range(0, word.length(), 420):
                parts.append(word.substr(offset, 420))
            continue
        var limit := (72 if parts.is_empty() else 150) if fast else 420
        if not current.is_empty() and current.length() + word.length() + 1 > limit:
            parts.append(current)
            current = ""
        current += ("" if current.is_empty() else " ") + word
        if fast and (word.ends_with(".") or word.ends_with("!") or word.ends_with("?") or
                (parts.is_empty() and current.length() >= 35 and
                (word.ends_with(",") or word.ends_with(";")))):
            parts.append(current)
            current = ""
    if not current.is_empty():
        parts.append(current)
    return parts

func _queue_eli_speech(speech: String, emotion: String = "calm") -> void:
    if text_only or voice_muted or not tts_ready or not is_instance_valid(voice_tts_http):
        return
    for part in _voice_chunks(speech, voice_fast and voice_engine != "piper"):
        voice_speaking_queue.append({"text": part, "emotion": emotion,
            "profile": voice_profile, "threads": voice_threads, "engine": voice_engine})
    _play_next_eli_chunk()

func _play_next_eli_chunk() -> void:
    if text_only or voice_muted or not is_instance_valid(eli_voice_player):
        return
    if not eli_voice_player.playing and not voice_buffer.is_empty():
        eli_voice_player.stream = voice_buffer.pop_front()
        _set_voice_volume()
        eli_voice_player.play()
    # At most one ready WAV ahead. Generate it while the current WAV plays.
    if tts_pending or not voice_buffer.is_empty() or voice_speaking_queue.is_empty():
        return
    var segment: Dictionary = voice_speaking_queue.pop_front()
    tts_pending = true
    voice_request_epoch = voice_epoch
    voice_request_started = Time.get_ticks_msec()
    var result := voice_tts_http.request(BRIDGE_URL + "/api/voice/speak",
        PackedStringArray(["Content-Type: application/json"]),
        HTTPClient.METHOD_POST, JSON.stringify(segment))
    if result != OK:
        tts_pending = false
        voice_speaking_queue.clear()
        _message("SYSTEM", "Eli's local speech engine is unavailable. Subtitles still work.")

func _on_eli_wav(result: int, response_code: int, _headers: PackedStringArray,
        body: PackedByteArray) -> void:
    tts_pending = false
    # Skipping cannot cancel Python computation already underway. Drain that
    # response before sending the next request; never play stale audio.
    if voice_request_epoch != voice_epoch or text_only or voice_muted:
        _play_next_eli_chunk()
        return
    if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
        voice_speaking_queue.clear()
        _message("SYSTEM", "Eli's voice couldn't be generated. His subtitles still work.")
        voice_benchmark_label.text = "Synthesis failed. See local voice log."
        voice_benchmark = false
        return
    var stream: AudioStreamWAV = AudioStreamWAV.load_from_buffer(body)
    if stream == null:
        _message("SYSTEM", "Eli's voice returned invalid audio. Subtitles still work.")
        _play_next_eli_chunk()
        return
    var elapsed := float(Time.get_ticks_msec() - voice_request_started) / 1000.0
    var actual_engine := "local voice"
    for header in _headers:
        if header.to_lower().begins_with("x-tlc-voice-engine:"):
            var engine_id := header.get_slice(":", 1).strip_edges()
            match engine_id:
                "native_vulkan": actual_engine = "Native Nano Q8 (Vulkan)"
                "native": actual_engine = "Native Nano Q8 (CPU)"
                "nano_cuda": actual_engine = "Chatterbox Nano CUDA GPU"
                "nano": actual_engine = "Nano CPU"
                "piper": actual_engine = "Piper"
    var metrics := "%s | Playable segment: %.2fs | %.2fs audio" % [actual_engine, elapsed, stream.get_length()]
    print("[Voice] " + metrics)
    voice_benchmark_label.text = metrics
    if voice_benchmark:
        voice_benchmark = false
    voice_buffer.append(stream)
    _play_next_eli_chunk()

func _skip_eli_voice() -> void:
    voice_epoch += 1
    voice_benchmark = false
    voice_speaking_queue.clear()
    voice_buffer.clear()
    if is_instance_valid(eli_voice_player):
        eli_voice_player.stop()

func _build_voice_studio() -> void:
    voice_studio = Window.new()
    voice_studio.title = "Eli Voice Studio"
    voice_studio.size = Vector2i(450, 390)
    voice_studio.visible = false
    voice_studio.close_requested.connect(func(): voice_studio.hide())
    add_child(voice_studio)
    var panel := VBoxContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    panel.add_theme_constant_override("separation", 9)
    voice_studio.add_child(panel)
    var heading := Label.new()
    heading.text = "LOCAL VOICE / PERFORMANCE"
    panel.add_child(heading)
    voice_profiles = OptionButton.new()
    panel.add_child(voice_profiles)
    voice_profiles.item_selected.connect(func(idx: int):
        voice_profile = str(voice_profiles.get_item_metadata(idx))
        _save())
    voice_engine_control = OptionButton.new()
    voice_engine_control.add_item("Chatterbox Nano CPU (automatic Piper fallback)")
    voice_engine_control.add_item("Piper (fast fallback)")
    voice_engine_control.add_item("Native Nano Q8 CPU (experimental)")
    voice_engine_control.add_item("Native Nano Q8 Vulkan GPU (experimental)")
    voice_engine_control.add_item("Chatterbox Nano CUDA GPU (experimental)")
    voice_engine_control.set_item_disabled(4, true)
    voice_engine_control.set_item_disabled(2, true)
    voice_engine_control.set_item_disabled(3, true)
    panel.add_child(voice_engine_control)
    voice_engine_control.item_selected.connect(func(idx: int):
        voice_engine = ["auto", "piper", "native", "native_vulkan", "nano_cuda"][idx]
        _save())
    var thread_label := Label.new()
    thread_label.text = "CPU threads (0 = automatic)"
    panel.add_child(thread_label)
    voice_thread_control = SpinBox.new()
    voice_thread_control.min_value = 0
    voice_thread_control.max_value = 32
    voice_thread_control.step = 1
    panel.add_child(voice_thread_control)
    voice_thread_control.value_changed.connect(func(value: float):
        voice_threads = int(value)
        _save())
    voice_fast_control = CheckButton.new()
    voice_fast_control.text = "Low-latency sentence buffering"
    panel.add_child(voice_fast_control)
    voice_fast_control.toggled.connect(func(enabled: bool):
        voice_fast = enabled
        _save())
    voice_emotion_control = OptionButton.new()
    for emotion in ["calm", "afraid", "angry", "suspicious", "relieved"]:
        voice_emotion_control.add_item(emotion.capitalize())
        voice_emotion_control.set_item_metadata(voice_emotion_control.item_count - 1, emotion)
    panel.add_child(voice_emotion_control)
    var preview := Button.new()
    preview.text = "PREVIEW + BENCHMARK"
    preview.pressed.connect(_preview_voice)
    panel.add_child(preview)
    var import_button := Button.new()
    import_button.text = "IMPORT AUTHORIZED REFERENCE WAV"
    import_button.pressed.connect(func(): voice_import_dialog.popup_centered_ratio(0.75))
    panel.add_child(import_button)
    voice_benchmark_label = Label.new()
    voice_benchmark_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    voice_benchmark_label.text = "Preview measures request-to-playable-audio latency."
    panel.add_child(voice_benchmark_label)
    voice_import_dialog = FileDialog.new()
    voice_import_dialog.access = FileDialog.ACCESS_FILESYSTEM
    voice_import_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
    voice_import_dialog.filters = PackedStringArray(["*.wav ; WAV reference (over 5 seconds)"])
    voice_import_dialog.file_selected.connect(_import_voice_reference)
    voice_studio.add_child(voice_import_dialog)
    _refresh_voice_profiles()

func _refresh_voice_profiles() -> void:
    if not is_instance_valid(voice_profiles):
        return
    voice_profiles.clear()
    var profiles: Variant = voice_status_data.get("profiles", [{"id": "default", "label": "Original Nano"}])
    if typeof(profiles) != TYPE_ARRAY:
        return
    for item in profiles:
        if typeof(item) != TYPE_DICTIONARY:
            continue
        voice_profiles.add_item(str(item.get("label", "Voice")))
        var idx := voice_profiles.item_count - 1
        voice_profiles.set_item_metadata(idx, str(item.get("id", "default")))
        if str(item.get("id", "")) == voice_profile:
            voice_profiles.select(idx)
    if voice_profiles.item_count > 0 and voice_profiles.selected < 0:
        voice_profiles.select(0)

func _open_voice_studio() -> void:
    _refresh_voice_profiles()
    voice_thread_control.set_value_no_signal(voice_threads)
    var native_ready := bool(voice_status_data.get("native_ready", false))
    var vulkan_ready := bool(voice_status_data.get("native_vulkan_ready", false))
    voice_engine_control.set_item_disabled(2, not native_ready)
    voice_engine_control.set_item_disabled(3, not vulkan_ready)
    var cuda_ready := bool(voice_status_data.get("nano_cuda_ready", false))
    voice_engine_control.set_item_disabled(4, not cuda_ready)
    if (voice_engine == "native" and not native_ready) or (voice_engine == "native_vulkan" and not vulkan_ready) or (voice_engine == "nano_cuda" and not cuda_ready):
        voice_engine = "auto"
        _save()
    var engine_index := ["auto", "piper", "native", "native_vulkan", "nano_cuda"].find(voice_engine)
    voice_engine_control.select(maxi(0, engine_index))
    voice_fast_control.set_pressed_no_signal(voice_fast)
    voice_studio.popup_centered()

func _preview_voice() -> void:
    if voice_muted or text_only or not tts_ready:
        voice_benchmark_label.text = "Enable local speech to preview."
        return
    _skip_eli_voice()
    voice_benchmark = true
    voice_benchmark_label.text = "Generating preview locally..."
    var emotion := str(voice_emotion_control.get_item_metadata(voice_emotion_control.selected))
    # Single fixed prompt for repeatable timing; never becomes Eli dialogue.
    voice_speaking_queue.append({"text": "Is someone there? I can hear you.", "emotion": emotion,
        "profile": voice_profile, "threads": voice_threads, "engine": voice_engine})
    _play_next_eli_chunk()

func _import_voice_reference(path: String) -> void:
    var bytes := FileAccess.get_file_as_bytes(path)
    if bytes.size() < 44 or bytes.size() > 16000000:
        voice_benchmark_label.text = "Use a clean 5–30 second WAV under 16 MB."
        return
    var sample := AudioStreamWAV.load_from_buffer(bytes)
    if sample == null or sample.get_length() <= 5.0 or sample.get_length() > 30.0:
        voice_benchmark_label.text = "Reference must be a playable WAV longer than 5 seconds, up to 30."
        return
    var folder := OS.get_executable_path().get_base_dir().path_join("models/chatterbox-nano/voices")
    if DirAccess.make_dir_recursive_absolute(folder) != OK:
        voice_benchmark_label.text = "Could not create local voice directory."
        return
    var safe := RegEx.new()
    safe.compile("[^A-Za-z0-9_-]")
    var name := safe.sub(path.get_file().get_basename(), "_", true).left(36)
    name = name + "_" + str(Time.get_ticks_msec())
    var dest := folder.path_join(name + ".wav")
    var file := FileAccess.open(dest, FileAccess.WRITE)
    if file == null:
        voice_benchmark_label.text = "Could not save reference."
        return
    file.store_buffer(bytes)
    file.close()
    voice_profile = "ref:" + name
    _save()
    voice_benchmark_label.text = "Reference imported locally. Select Preview to audition."
    if is_instance_valid(voice_status_http):
        voice_status_http.request(BRIDGE_URL + "/api/voice/status")

func _stop_all_voice() -> void:
    _skip_eli_voice()
    if microphone_recording:
        microphone_recording = false
        mic_recorder.set_recording_active(false)
        mic_player.stop()
    if transcribing:
        voice_stt_http.cancel_request()
        transcribing = false
    _voice_ready()

func _on_voice_muted(enabled: bool) -> void:
    voice_muted = enabled
    if enabled:
        _skip_eli_voice()
    _save()

func _on_text_only(enabled: bool) -> void:
    text_only = enabled
    if enabled:
        _stop_all_voice()
    _voice_ready()
    _save()

func _on_sensitivity_changed(value: float) -> void:
    microphone_sensitivity = value
    _save()

func _on_voice_volume_changed(value: float) -> void:
    voice_volume = value
    _set_voice_volume()
    _save()

func _set_voice_volume() -> void:
    if is_instance_valid(eli_voice_player):
        eli_voice_player.volume_db = linear_to_db(maxf(0.001, voice_volume))
