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
    if failures.is_empty():
        print("GODOT SMOKE PASS: scene, flashlight, breaker and locked exit")
        quit(0)
    else:
        printerr("GODOT SMOKE FAILED: ", failures)
        quit(1)
