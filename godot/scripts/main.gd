extends Control
## Prototype terminal: typed messages and authoritative in-world actions.

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

func _ready() -> void:
    _build_ui()
    _load_save()
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
    _message("SYSTEM", "Connected to CAM 01. Type an instruction to talk to Eli.")
    _message("SYSTEM", "Run the Python bridge on localhost:8765 first. Voice is scheduled for Phase 3.")
    call_deferred("_restore_input_focus")

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

    var cam_status := Label.new()
    cam_status.text = "AUDIO LINK: STANDBY       ◦       VIDEO FEED: ACTIVE"
    cam_status.add_theme_color_override("font_color", Color("7e9ba9"))
    left.add_child(cam_status)

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

func _send_pressed() -> void:
    _submit(input.text)
    # Buttons take keyboard focus on a mouse click. Return it after the click
    # completes, not synchronously while the mouse is still held down.
    call_deferred("_restore_input_focus")

func _submit(message: String) -> void:
    var trimmed := message.strip_edges()
    if trimmed.is_empty() or request_stage != "idle" or world.busy:
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
            _message("ELI", str(response.get("speech", "That didn't work.")))
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
        _message("ELI", str(response.get("speech", "That's done.")))
        if queued_actions.size() > 1:
            _message("SYSTEM", "Sequence complete: " + str(queued_actions.size()) +
                " of " + str(queued_actions.size()) + " steps confirmed.")
        _idle()
        return

    _message("ELI", str(response.get("speech", "...")))
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
    var body := {"session_id": session_id, "action": action, "target": target,
        "success": success, "description": description, "world": world.snapshot()}
    _request("/api/outcome", body, "outcome")

func _idle() -> void:
    queued_actions.clear()
    queue_index = 0
    last_step_succeeded = false
    request_stage = "idle"
    status.text = "Ready"
    send_button.disabled = false
    call_deferred("_restore_input_focus")


func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_WINDOW_FOCUS_IN:
        call_deferred("_restore_input_focus")


func _restore_input_focus() -> void:
    if not is_instance_valid(input) or not input.is_inside_tree():
        return
    # Update confirmations intentionally own focus while they're open.
    if is_instance_valid(update_dialog) and update_dialog.visible:
        return
    input.grab_focus()
    input.caret_column = input.text.length()


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
    _message("SYSTEM", "New session. Eli's room and conversation have been reset.")
    call_deferred("_restore_input_focus")

func _load_save() -> void:
    var cfg := ConfigFile.new()
    if cfg.load(_save_path()) == OK:
        session_id = str(cfg.get_value("session", "id", ""))
        var saved_world: Dictionary = cfg.get_value("world", "state", {})
        world.restore_state(saved_world)
    if session_id.is_empty() or session_id.contains("."):
        session_id = "eli_" + str(int(Time.get_unix_time_from_system())) + "_" + str(randi_range(1000,9999))
        _save()

func _save() -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("session", "id", session_id)
    cfg.set_value("world", "state", world.export_state())
    var error := cfg.save(_save_path())
    if error != OK:
        push_warning("Couldn't write save game: " + str(error))
