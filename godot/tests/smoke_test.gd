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
    _expect(not world.snapshot()["inventory"].has("flashlight"), "Flashlight begins on desk")
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
