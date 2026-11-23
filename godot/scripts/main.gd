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
var voice_speaking_queue: Array[String] = []
var tts_pending := false
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
    update_dialog = ConfirmationDialog.new()
    update_dialog.title = "Update The Last Connection?"
    update_dialog.confirmed.connect(_install_update)
    update_dialog.canceled.connect(_on_update_dialog_dismissed)
    add_child(update_dialog)
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
    update_button = Button.new()
    update_button.text = "CHECK FOR UPDATES"
    update_button.focus_mode = Control.FOCUS_NONE
    update_button.pressed.connect(_check_for_updates)
    right.add_child(update_button)
    var new_game := Button.new()
    new_game.text = "NEW SESSION / RESET ROOM"
    new_game.focus_mode = Control.FOCUS_NONE
    new_game.pressed.connect(_new_game)
    right.add_child(new_game)

func _message(speaker: String, text: String) -> void:
    log_view.append_text("[" + speaker + "] " + text + "\n\n")
    if speaker == "ELI":
        _queue_eli_speech(text)

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
        # The engine has finished and the local bridge recorded this exact
        # outcome. Do not continue a failed or unrecorded step.
        if not last_step_succeeded:
            var failed_reply := str(response.get("speech", "")).strip_edges()
            if not failed_reply.is_empty():
                _message("ELI", failed_reply)
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
        var final_reply := str(response.get("speech", "")).strip_edges()
        if not final_reply.is_empty():
            _message("ELI", final_reply)
        if queued_actions.size() > 1:
            _message("SYSTEM", "Sequence complete: " + str(queued_actions.size()) +
                " of " + str(queued_actions.size()) + " steps confirmed.")
        _idle()
        return

    # No synthetic spoken placeholder when the local model couldn't
    # ground a reply. The authoritative OBSERVATION still remains visible.
    var eli_reply := str(response.get("speech", "")).strip_edges()
    if not eli_reply.is_empty():
        _message("ELI", eli_reply)
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
    var action: String = str(step.get("action", ""))
    var target: String = str(step.get("target", ""))
    var argument: String = str(step.get("argument", ""))
    if action not in ["move_to", "inspect", "take", "use", "enter_code", "survey"]:
        return false
    if action == "survey":
        return target == "room" and argument.is_empty()
    # Target names are whitelisted, but only the ENGINE at execution time
    # decides if an object is currently visible/reachable. Earlier planned
    # actions may reveal objects, such as restoring power before reading a note.
    if target not in ["flashlight", "breaker_box", "exit_door", "keypad", "maintenance_note"]:
        return false
    if action == "enter_code":
        return target == "keypad" and argument.length() == 4 and argument.is_valid_int()
    if action == "use" and target == "flashlight":
        return argument in ["", "on", "off"]
    return argument.is_empty()


func _start_queued_action() -> void:
    if queue_index >= queued_actions.size():
        _idle()
        return
    var step: Dictionary = queued_actions[queue_index]
    request_stage = "action"
    var step_total := queued_actions.size()
    status.text = ("Eli is performing step " + str(queue_index + 1) + "/" +
        str(step_total) + "...") if step_total > 1 else "Eli is moving..."
    action_context = step.duplicate()
    world.perform_action(str(step["action"]), str(step["target"]),
                         str(step.get("argument", "")))


func _on_world_action_finished(action: String, target: String, success: bool, description: String) -> void:
    last_step_succeeded = success
    _message("OBSERVATION", description)
    if success:
        _save()
    # Intermediate steps only record truth. Eli speaks naturally after the
    # last successful step or immediately after a failure, avoiding repeated
    # slow GGUF calls and canned replies for each queued movement.
    var should_speak := not success or queue_index + 1 >= queued_actions.size()
    var body := {"session_id": session_id, "action": action, "target": target,
        "success": success, "description": description, "world": world.snapshot(),
        "speak": should_speak}
    _request("/api/outcome", body, "outcome")

func _idle() -> void:
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
    if is_instance_valid(update_dialog) and update_dialog.visible:
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


func _new_game() -> void:
    if request_stage != "idle" or world.busy:
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
        voice_mute_button.set_pressed_no_signal(voice_muted)
        voice_text_only_button.set_pressed_no_signal(text_only)
        sensitivity_slider.set_value_no_signal(microphone_sensitivity)
        volume_slider.set_value_no_signal(voice_volume)
    if session_id.is_empty() or session_id.contains("."):
        session_id = "eli_" + str(int(Time.get_unix_time_from_system())) + "_" + str(randi_range(1000,9999))
        _save()

func _save() -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("session", "id", session_id)
    cfg.set_value("world", "state", world.export_state())
    cfg.set_value("voice", "muted", voice_muted)
    cfg.set_value("voice", "text_only", text_only)
    cfg.set_value("voice", "sensitivity", microphone_sensitivity)
    cfg.set_value("voice", "volume", voice_volume)
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
    voice_tts_http.timeout = 105.0
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
    if result == HTTPRequest.RESULT_SUCCESS and code == 200:
        var data = JSON.parse_string(body.get_string_from_utf8())
        if typeof(data) == TYPE_DICTIONARY:
            stt_ready = bool(data.get("stt_ready", false))
            tts_ready = bool(data.get("tts_ready", false))
    microphone_button.disabled = not stt_ready or text_only
    if not text_only:
        audio_link_status.text = ("AUDIO LINK: PUSH TO TALK (V)" if stt_ready
                                 else "AUDIO LINK: TEXT ONLY / MIC UNAVAILABLE") + "       ◦       VIDEO FEED: ACTIVE"
    if stt_ready and tts_ready:
        _message("SYSTEM", "Microphone and Eli's local voice ready. Hold V, release to transmit.")
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

func _queue_eli_speech(speech: String) -> void:
    if text_only or voice_muted or not tts_ready or not is_instance_valid(voice_tts_http):
        return
    # Preserve the complete subtitle. Long lines are spoken in sequential
    # chunks; speech is never truncated mid-sentence by a character limit.
    var chunks := speech.split(" ", false)
    var current := ""
    for word in chunks:
        if word.length() > 1100:
            continue
        if not current.is_empty() and current.length() + word.length() + 1 > 420:
            voice_speaking_queue.append(current)
            current = ""
        current += ("" if current.is_empty() else " ") + word
    if not current.is_empty():
        voice_speaking_queue.append(current)
    _play_next_eli_chunk()

func _play_next_eli_chunk() -> void:
    if text_only or voice_muted or tts_pending or eli_voice_player.playing:
        return
    if voice_speaking_queue.is_empty():
        return
    var segment: String = voice_speaking_queue.pop_front()
    tts_pending = true
    var result := voice_tts_http.request(BRIDGE_URL + "/api/voice/speak",
        PackedStringArray(["Content-Type: application/json"]),
        HTTPClient.METHOD_POST, JSON.stringify({"text": segment}))
    if result != OK:
        tts_pending = false
        _message("SYSTEM", "Eli's local speech engine is unavailable. Subtitles still work.")

func _on_eli_wav(result: int, response_code: int, _headers: PackedStringArray,
        body: PackedByteArray) -> void:
    tts_pending = false
    if text_only or voice_muted:
        return
    if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
        tts_ready = false
        voice_speaking_queue.clear()
        _message("SYSTEM", "Eli's voice couldn't be generated. His subtitles still work.")
        return
    var stream: AudioStreamWAV = AudioStreamWAV.load_from_buffer(body)
    if stream == null:
        _message("SYSTEM", "Eli's voice returned invalid audio. Subtitles still work.")
        _play_next_eli_chunk()
        return
    eli_voice_player.stream = stream
    _set_voice_volume()
    eli_voice_player.play()

func _skip_eli_voice() -> void:
    voice_speaking_queue.clear()
    if is_instance_valid(eli_voice_player):
        eli_voice_player.stop()
    if is_instance_valid(voice_tts_http) and tts_pending:
        voice_tts_http.cancel_request()
        tts_pending = false

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
