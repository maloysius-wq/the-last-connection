extends SceneTree
## Real Godot smoke test. Use: godot --headless --path godot --script res://tests/smoke_test.gd

var failures: Array[String] = []

func _initialize() -> void:
    call_deferred("_run")

func _expect(condition: bool, message: String) -> void:
    if not condition:
        failures.append(message)
        push_error("SMOKE FAILED: " + message)

func _run() -> void:
    var scene: PackedScene = load("res://scenes/Main.tscn")
    _expect(scene != null, "Main scene loads")
    if scene == null:
        quit(1)
        return
    var app := scene.instantiate()
    root.add_child(app)
    await process_frame
    var world = app.get("world")
    _expect(world != null, "Main initializes the 3D world")
    if world == null:
        quit(1)
        return
    # The world smoke test drives actions directly. Disconnect the real
    # terminal's bridge callback so it does not attempt localhost POSTs
    # without a server and interfere with the input-focus test.
    var bridge_callback := Callable(app, "_on_world_action_finished")
    if world.action_finished.is_connected(bridge_callback):
        world.action_finished.disconnect(bridge_callback)
    var entry: LineEdit = app.get("input")
    _expect(entry != null, "Terminal chat field exists")
    if entry != null:
        # Check editor focus without an AI bridge and verify that drafting is
        # possible while a previous request is still pending.
        entry.release_focus()
        app.call("_send_pressed")
        await process_frame
        _expect(entry.has_focus(), "Clicking TRANSMIT returns focus to chat")
        var payload := {"session_id": "smoke", "player_text": "Check", "world": world.snapshot()}
        app.call("_request", "/api/decide", payload, "decide")
        _expect(entry.editable, "Chat stays editable while Eli thinks")
        entry.text = "next instruction"
        app.get("http").cancel_request()
        app.call("_idle")
        await process_frame
        _expect(entry.has_focus(), "Chat regains focus after request is done")
        _expect(entry.text == "next instruction", "Draft survives between interactions")
        entry.clear()
        # Lost Windows focus must not swallow the FIRST character when the
        # terminal is already showing READY. No focus-exited regrab callback.
        entry.release_focus()
        var first_key := InputEventKey.new()
        first_key.pressed = true
        first_key.unicode = 120 # x
        app.call("_unhandled_key_input", first_key)
        _expect(entry.has_focus(), "Unfocused READY chat accepts a keyboard press")
        _expect(entry.text == "x", "Unfocused READY chat does not lose the first typed character")
        entry.clear()
        # The UI logs the full bridge response; the bridge itself must ensure
        # its text has a complete ending, not truncate at 650 characters.
        var full_reply := "I'm listening. " + "This is an intentionally long complete sentence. ".repeat(18)
        app.set("request_stage", "decide")
        entry.release_focus()
        app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
            PackedStringArray(),
            JSON.stringify({"speech": full_reply, "action": "wait", "target": ""}).to_utf8_buffer())
        _expect(full_reply in str(app.get("log_view").get_parsed_text()),
            "Terminal preserves full responses beyond the old 650-character cutoff")
        _expect(entry.has_focus(), "Chat focus is restored immediately when READY is shown")
        entry.clear()
    # Phase 3 voice is opt-in and must not replace keyboard, subtitles or
    # the saved action queue when no microphone/AI engine exists in CI.
    var mic_control: Button = app.get("microphone_button")
    var mute_control: CheckButton = app.get("voice_mute_button")
    var text_mode: CheckButton = app.get("voice_text_only_button")
    _expect(mic_control != null and mute_control != null and text_mode != null,
        "Voice push-to-talk, mute and text-only controls exist")
    _expect(app.get("mic_recorder") != null and app.get("eli_voice_player") != null,
        "Godot initializes capture and synthesized speech playback")
    _expect(app.get("voice_stt_http") != null and app.get("voice_tts_http") != null,
        "Mic and speech have separate HTTP clients from the action queue")
    if mic_control != null and text_mode != null:
        _expect(mic_control.focus_mode == Control.FOCUS_NONE,
            "Holding the microphone button does not steal chat keyboard focus")
        app.call("_on_text_only", true)
        app.call("_start_microphone_recording")
        _expect(not bool(app.get("microphone_recording")),
            "Text-only mode physically disables microphone capture")
        app.call("_message", "ELI", "This reply stays visible without voice hardware.")
        _expect("This reply stays visible" in str(app.get("log_view").get_parsed_text()),
            "Eli's subtitles remain when speech output is disabled")
        app.call("_on_text_only", false)
    # A prior focus-exited callback forced the input to grab focus while the
    # player was clicking CHECK FOR UPDATES, potentially canceling its press.
    var update_btn: Button = app.get("update_button")
    var transmit_btn: Button = app.get("send_button")
    _expect(update_btn != null and transmit_btn != null, "Terminal buttons exist")
    if update_btn != null and transmit_btn != null and entry != null:
        _expect(update_btn.focus_mode == Control.FOCUS_NONE,
            "Checking for updates does not steal chat keyboard focus")
        _expect(transmit_btn.focus_mode == Control.FOCUS_NONE,
            "Transmit does not steal chat keyboard focus")
        _expect(entry.get_signal_connection_list("focus_exited").is_empty(),
            "No focus-exited callback can interrupt a button click")
        # Exercise the actual signal wiring and immediate feedback without
        # relying on GitHub or an AI bridge in the headless test runner.
        update_btn.pressed.emit()
        _expect(str(app.get("update_stage")) == "check",
            "Update button press starts a release check")
        _expect(update_btn.text == "CHECKING GITHUB...",
            "Release check immediately changes the button label")
        _expect(str(app.get("status").text) == "Checking GitHub releases...",
            "Release check immediately shows feedback beside the conversation")
        _expect("Checking GitHub for a newer Windows game release" in str(app.get("log_view").get_parsed_text()),
            "Release check leaves a visible SYSTEM status in the chat log")
        app.get("update_http").cancel_request()
        app.call("_update_idle")
        _expect(not update_btn.disabled and update_btn.text == "CHECK FOR UPDATES",
            "Update button can be used again after a check finishes")
    _expect(not world.snapshot()["inventory"].has("flashlight"), "Flashlight begins on desk")
    world.perform_action("move_to", "breaker_box")
    var moved: Array = await world.action_finished
    _expect(moved[2] == true, "Movement to the breaker box completed")
    _expect(world.snapshot().get("actor_at") == "breaker_box",
        "Snapshot reports actual breaker position")
    _expect(world.actor.position.distance_to(world.object_positions["breaker_box"]) < 0.12,
        "Eli physically reached the breaker box")
    _expect("breaker" in str(world.snapshot().get("last_observation", "")),
        "Snapshot carries actual recent observation")
    world.perform_action("move_to", "breaker_box")
    moved = await world.action_finished
    _expect(moved[2] == true and "already" in str(moved[3]),
        "Repeated move correctly reports Eli already standing there")
    var saved_position: Dictionary = world.export_state()
    world.reset_state()
    world.restore_state(saved_position)
    _expect(world.snapshot().get("actor_at") == "breaker_box",
        "Current position persists after save and restore")
    world.reset_state()
    world.perform_action("move_to", "keypad")
    moved = await world.action_finished
    _expect(world.snapshot().get("actor_at") == "keypad",
        "A second destination changes actual position")
    world.reset_state()
    # The user can request "go to the pin pad and take a look": a single
    # inspect action must actually WALK to the keypad, then examine its red
    # indicator. It must not just say that Eli is walking.
    world.perform_action("inspect", "keypad")
    moved = await world.action_finished
    _expect(moved[2] == true and "glows red" in str(moved[3]),
        "Keypad inspection reports the real red indicator")
    _expect(world.snapshot().get("actor_at") == "keypad",
        "Inspect physically walks Eli from desk to keypad")
    _expect(world.actor.position.distance_to(world.object_positions["keypad"]) < 0.12,
        "Eli stands by keypad after inspecting it")
    world.reset_state()
    # Recreate screenshot: Eli stands at breaker, flashlight remains on desk.
    # The player's indirect "pick that up and turn it on" resolves in the
    # bridge to use/flashlight/on. Godot must actually walk back to the desk.
    world.perform_action("move_to", "breaker_box")
    moved = await world.action_finished
    _expect(moved[2] == true and world.snapshot().get("actor_at") == "breaker_box",
        "Flashlight scenario begins with Eli physically at the breaker")
    _expect(not world.snapshot()["inventory"].has("flashlight"),
        "Flashlight still rests on the desk before instruction")
    # Turning on an uncollected flashlight must physically pick it up first.
    world.perform_action("use", "flashlight", "on")
    var flashlight_action: Array = await world.action_finished
    _expect(flashlight_action[2] == true, "Using uncollected flashlight succeeds via pickup")
    _expect("picked up" in str(flashlight_action[3]), "Outcome reports flashlight pickup truthfully")
    _expect(world.snapshot()["inventory"].has("flashlight"), "Flashlight is in Eli's hand")
    _expect(world.snapshot()["flashlight_on"] == true, "Flashlight is now on")
    _expect(world.snapshot().get("actor_at") == "flashlight",
        "Eli's confirmed location changes from breaker to flashlight desk")
    _expect(world.actor.position.distance_to(world.object_positions["flashlight"]) < 0.12,
        "Eli visibly travels to flashlight before claiming pickup")
    _expect(world.actor.position.z > -0.70,
        "Eli stands in front of the desk instead of intersecting its tabletop")
    _expect(world.object_positions["maintenance_note"].z > -0.70,
        "The maintenance note is also accessible without standing inside the table")
    world.perform_action("use", "flashlight", "on")
    flashlight_action = await world.action_finished
    _expect(flashlight_action[2] == true and world.snapshot()["flashlight_on"] == true,
        "Requesting ON twice does not accidentally toggle OFF")
    world.perform_action("use", "flashlight", "off")
    flashlight_action = await world.action_finished
    _expect(flashlight_action[2] == true and world.snapshot()["flashlight_on"] == false,
        "Explicit OFF state is respected")
    var legacy_desk: Dictionary = world.export_state()
    legacy_desk["actor_z"] = -1.40
    legacy_desk["actor_at"] = "flashlight"
    world.restore_state(legacy_desk)
    _expect(world.actor.position.z > -0.70,
        "Older save positions embedded in the desk are moved to its accessible front")
    world.reset_state()
    _expect(not world.snapshot()["inventory"].has("flashlight"), "Reset returns flashlight to the desk")
    world.perform_action("use", "flashlight", "off")
    flashlight_action = await world.action_finished
    _expect(flashlight_action[2] == true and not world.snapshot()["inventory"].has("flashlight"),
        "Turning OFF a desk flashlight does not make Eli pick it up")
    world.perform_action("take", "flashlight")
    var result: Array = await world.action_finished
    _expect(result[2] == true, "Flashlight pickup succeeds")
    _expect(world.snapshot()["inventory"].has("flashlight"), "Inventory updates after pickup")
    # The user reported "I flipped it but nothing happened". Distinguish
    # a look at the switch from actual activation before and after power.
    world.perform_action("inspect", "breaker_box")
    result = await world.action_finished
    _expect(result[2] == true and "has not flipped" in str(result[3]),
        "Pre-power inspection does not claim the breaker was activated")
    _expect(not world.snapshot()["lights_on"] and not world.note_mesh.visible,
        "Inspecting never changes power or reveals the code note")
    _expect(world.breaker_lever.position.y < 1.5,
        "Unpowered breaker lever is visibly down")
    world.perform_action("use", "breaker_box")
    result = await world.action_finished
    _expect(result[2] == true and "restored" in str(result[3]),
        "Breaker can be switched on and reports restoration")
    _expect(world.snapshot()["lights_on"] == true, "Breaker changes lighting state")
    _expect(world.breaker_lever.position.y > 1.5 and world.note_mesh.visible,
        "Restoring power physically raises the switch and reveals the note")
    _expect(world.overhead_light.light_energy > 1.0,
        "Power restoration visibly brightens the overhead lights")
    _expect("lever is up" in str(world.snapshot()["objects"]["breaker_box"]["description"]),
        "World snapshot and dialogue context know the switch is now up")
    world.perform_action("inspect", "breaker_box")
    result = await world.action_finished
    _expect(result[2] == true and "lever is up" in str(result[3]),
        "Inspecting after power restoration cannot claim the lever remains down")
    world.perform_action("use", "breaker_box")
    result = await world.action_finished
    _expect(result[2] == true and "already up" in str(result[3]),
        "Repeating an already completed breaker action reports the true state")
    _expect("Nothing happened" not in str(result[3]) and
            "knocks" not in str(result[3]),
        "Repeated action neither falsely fails nor replays one-time knocking")
    _expect(world.snapshot()["lights_on"] == true and
            world.snapshot()["objects"].has("maintenance_note"),
        "Repeated breaker use preserves power and the visible clue")
    world.perform_action("use", "exit_door")
    result = await world.action_finished
    _expect(result[2] == false, "Exit remains locked before solving puzzle")
    _expect(world.snapshot()["heard_knocks"] == true, "Authored knocks fire after power")
    _expect(world.snapshot()["objects"].has("maintenance_note"), "Clue appears after lights")
    world.perform_action("inspect", "maintenance_note")
    result = await world.action_finished
    _expect(result[2] == true and "4317" in str(result[3]), "Inspect reveals code")
    world.perform_action("enter_code", "keypad", "0000")
    result = await world.action_finished
    _expect(result[2] == false, "Incorrect code rejected")
    world.perform_action("enter_code", "keypad", "4317")
    result = await world.action_finished
    _expect(result[2] == true, "Correct code accepted")
    _expect(world.snapshot()["door_unlocked"] == true, "Door unlocks")
    world.perform_action("use", "exit_door")
    result = await world.action_finished
    _expect(result[2] == true and world.snapshot()["escaped"] == true, "Eli escapes")
    var saved: Dictionary = world.export_state()
    world.reset_state()
    _expect(world.snapshot()["escaped"] == false, "Room reset works")
    _expect(world.snapshot()["lights_on"] == false and not world.note_mesh.visible and
            world.breaker_lever.position.y < 1.5,
        "Reset restores powered-off visuals as well as saved puzzle state")
    world.restore_state(saved)
    _expect(world.snapshot()["escaped"] == true, "Escape save restores correctly")
    _expect(world.snapshot()["lights_on"] == true and world.note_mesh.visible and
            world.breaker_lever.position.y > 1.5,
        "Restoring an old power-on save also restores visible breaker and note")
    # Exercise the ACTUAL terminal decision -> world-action handoff, not just
    # direct world.perform_action tests. A response with action=use must move
    # Eli and change authoritative inventory/flashlight state.
    world.reset_state()
    app.set("request_stage", "decide")
    var bridge_decision := {
        "speech": "I'll pick up the flashlight and switch it on.",
        "action": "use", "target": "flashlight", "argument": "on",
        "emotion": "curious",
    }
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify(bridge_decision).to_utf8_buffer())
    _expect(str(app.get("request_stage")) == "action",
        "Game terminal dispatches a returned physical action")
    _expect(world.busy, "Engine starts moving after HTTP decision")
    var routed_outcome: Array = await world.action_finished
    _expect(routed_outcome[2] == true, "Routed flashlight action succeeds")
    _expect(world.snapshot()["inventory"].has("flashlight"),
        "Routed command actually picks flashlight up")
    _expect(world.snapshot()["flashlight_on"] == true,
        "Routed command actually switches flashlight on")
    _expect(world.snapshot()["actor_at"] == "flashlight",
        "Eli physically reaches desk after routed command")
    _expect("picked up" in str(routed_outcome[3]),
        "Routed action emits an authoritative pickup observation")
    # The preceding legacy single-action smoke intentionally skipped its
    # bridge outcome callback. Clear that simulated in-flight request first.
    app.call("_idle")
    # Full queued player order: take flashlight, switch it on, survey room.
    # Inject only one /api/decide response. Simulate the tiny /api/outcome
    # acknowledgments to avoid a real localhost bridge in headless CI.
    world.reset_state()
    app.set("request_stage", "decide")
    var three_steps := [
        {"action": "take", "target": "flashlight", "argument": ""},
        {"action": "use", "target": "flashlight", "argument": "on"},
        {"action": "survey", "target": "room", "argument": ""},
    ]
    var queue_response := {
        "speech": "I'll pick it up, switch it on, then look around.",
        "action": "take", "target": "flashlight",
        "argument": "", "actions": three_steps,
    }
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify(queue_response).to_utf8_buffer())
    _expect(str(app.get("request_stage")) == "action",
        "Queued response dispatches first step, not a conversational wait")
    _expect(app.get("queued_actions").size() == 3,
        "All three requested actions are queued")
    _expect("1/3" in str(app.get("status").text), "Queue shows progress 1 of 3")
    var queue_result: Array = await world.action_finished
    _expect(queue_result[0] == "take" and queue_result[2] == true,
        "First queued step physically picks up flashlight")
    _expect(world.snapshot()["inventory"].has("flashlight"),
        "Flashlight is genuinely in inventory before step two")
    _expect(world.snapshot()["flashlight_on"] == false,
        "Pickup alone does not claim flashlight was switched on")
    app.set("request_stage", "outcome")
    app.set("last_step_succeeded", queue_result[2])
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify({"speech": "Got it."}).to_utf8_buffer())
    _expect("2/3" in str(app.get("status").text),
        "Only after a confirmed successful pickup does step two begin")
    queue_result = await world.action_finished
    _expect(queue_result[0] == "use" and queue_result[2] == true,
        "Second queued step switches on the flashlight")
    _expect(world.snapshot()["flashlight_on"] == true,
        "Flashlight is physically on before survey starts")
    app.set("request_stage", "outcome")
    app.set("last_step_succeeded", queue_result[2])
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify({"speech": "It's on."}).to_utf8_buffer())
    _expect("3/3" in str(app.get("status").text),
        "Final survey runs only after light was confirmed on")
    queue_result = await world.action_finished
    _expect(queue_result[0] == "survey" and queue_result[2] == true,
        "Room survey is a real in-engine action")
    _expect("looks around" in str(queue_result[3]) and
        "flashlight is on" in str(queue_result[3]).to_lower(),
        "Room survey describes verified, illuminated room")
    _expect(not str(queue_result[3]).contains("4317"),
        "Survey never reveals hidden note code without inspecting it")
    app.set("request_stage", "outcome")
    app.set("last_step_succeeded", queue_result[2])
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify({"speech": "That's what I can see."}).to_utf8_buffer())
    _expect(str(app.get("request_stage")) == "idle" and
        app.get("queued_actions").is_empty(),
        "Completed sequence clears queue and returns terminal to Ready")
    _expect("Sequence complete: 3 of 3" in str(app.get("log_view").get_parsed_text()),
        "Terminal confirms exactly three completed steps")

    # When a real Godot action fails, later queued actions must NEVER run.
    world.reset_state()
    app.set("request_stage", "decide")
    var stop_steps := [
        {"action": "use", "target": "exit_door", "argument": ""},
        {"action": "use", "target": "breaker_box", "argument": ""}
    ]
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify({
            "speech": "I'll try the door, then the breaker.",
            "action": "use", "target": "exit_door",
            "argument": "", "actions": stop_steps
        }).to_utf8_buffer())
    var stop_result: Array = await world.action_finished
    _expect(stop_result[0] == "use" and stop_result[1] == "exit_door"
        and stop_result[2] == false, "Locked door fails first queued action")
    app.set("request_stage", "outcome")
    app.set("last_step_succeeded", stop_result[2])
    app.call("_on_http_completed", HTTPRequest.RESULT_SUCCESS, 200,
        PackedStringArray(), JSON.stringify({"speech": "The door is locked."}).to_utf8_buffer())
    _expect(str(app.get("request_stage")) == "idle" and
        app.get("queued_actions").is_empty(),
        "Failed step cancels the remaining queue")
    _expect(world.snapshot()["lights_on"] == false,
        "Breaker is not touched after the locked door failure")
    _expect("Sequence stopped at step 1 of 2" in
        str(app.get("log_view").get_parsed_text()),
        "Terminal visibly reports cancelled later steps")
    if failures.is_empty():
        print("GODOT SMOKE PASS: scene, flashlight, breaker, code puzzle, escape and persistence")
        quit(0)
    else:
        printerr("GODOT SMOKE FAILED: ", failures)
        quit(1)
