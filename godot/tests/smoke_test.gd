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
    # Turning on an uncollected flashlight must physically pick it up first.
    world.perform_action("use", "flashlight", "on")
    var flashlight_action: Array = await world.action_finished
    _expect(flashlight_action[2] == true, "Using uncollected flashlight succeeds via pickup")
    _expect("picked up" in str(flashlight_action[3]), "Outcome reports flashlight pickup truthfully")
    _expect(world.snapshot()["inventory"].has("flashlight"), "Flashlight is in Eli's hand")
    _expect(world.snapshot()["flashlight_on"] == true, "Flashlight is now on")
    world.perform_action("use", "flashlight", "on")
    flashlight_action = await world.action_finished
    _expect(flashlight_action[2] == true and world.snapshot()["flashlight_on"] == true,
        "Requesting ON twice does not accidentally toggle OFF")
    world.perform_action("use", "flashlight", "off")
    flashlight_action = await world.action_finished
    _expect(flashlight_action[2] == true and world.snapshot()["flashlight_on"] == false,
        "Explicit OFF state is respected")
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
    world.perform_action("use", "breaker_box")
    result = await world.action_finished
    _expect(result[2] == true, "Breaker can be switched on")
    _expect(world.snapshot()["lights_on"] == true, "Breaker changes lighting state")
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
    world.restore_state(saved)
    _expect(world.snapshot()["escaped"] == true, "Escape save restores correctly")
    if failures.is_empty():
        print("GODOT SMOKE PASS: scene, flashlight, breaker, code puzzle, escape and persistence")
        quit(0)
    else:
        printerr("GODOT SMOKE FAILED: ", failures)
        quit(1)
