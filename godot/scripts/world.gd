extends Node3D
## A tiny authoritative world simulation. The LLM cannot mutate this node.

signal action_finished(action: String, target: String, success: bool, description: String)

var inventory: Array[String] = []
var busy := false
var breaker_on := false
var actor: Node3D
var flashlight_mesh: Node3D
var overhead_light: OmniLight3D
var handheld_light: OmniLight3D
var flashlight_on := false
var object_positions: Dictionary = {
    "flashlight": Vector3(-1.7, 0.0, -1.4),
    "breaker_box": Vector3(0.0, 0.0, -1.8),
    "exit_door": Vector3(2.0, 0.0, -1.8),
    "keypad": Vector3(2.9, 0.0, -1.8)
}
var descriptions := {
    "flashlight": "A metal flashlight resting on the left-hand desk.",
    "breaker_box": "A breaker box on the back wall; its lever is down.",
    "exit_door": "A heavy locked door on the back wall.",
    "keypad": "A number pad beside the door, its indicator glowing red."
}

func _ready() -> void:
    _construct_room()

func _box(parent: Node3D, pos: Vector3, size: Vector3, color: Color) -> MeshInstance3D:
    var mesh_instance := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = size
    mesh_instance.mesh = mesh
    mesh_instance.position = pos
    var material := StandardMaterial3D.new()
    material.albedo_color = color
    material.roughness = 0.9
    mesh_instance.material_override = material
    parent.add_child(mesh_instance)
    return mesh_instance

func _construct_room() -> void:
    var env_node := WorldEnvironment.new()
    var env := Environment.new()
    env.background_mode = Environment.BG_COLOR
    env.background_color = Color("0a0d13")
    env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    env.ambient_light_color = Color("777f90")
    env.ambient_light_energy = 0.24
    env_node.environment = env
    add_child(env_node)

    _box(self, Vector3(0, -0.12, -0.6), Vector3(8, 0.2, 5.8), Color("343943"))
    _box(self, Vector3(0, 1.9, -3.48), Vector3(8, 3.8, 0.25), Color("242932"))
    _box(self, Vector3(-4, 1.9, -0.6), Vector3(0.25, 3.8, 5.8), Color("292e36"))
    _box(self, Vector3(4, 1.9, -0.6), Vector3(0.25, 3.8, 5.8), Color("292e36"))
    _box(self, Vector3(-1.7, 0.8, -1.4), Vector3(1.7, 0.14, 0.9), Color("66574b"))
    for side in [-2.3, -1.1]:
        _box(self, Vector3(side, 0.36, -1.4), Vector3(0.12, 0.72, 0.7), Color("474441"))

    flashlight_mesh = Node3D.new()
    flashlight_mesh.name = "Flashlight"
    flashlight_mesh.position = Vector3(-1.7, 0.93, -1.4)
    add_child(flashlight_mesh)
    _box(flashlight_mesh, Vector3.ZERO, Vector3(0.44, 0.1, 0.16), Color("d1c99e"))

    _box(self, Vector3(0.0, 1.45, -3.31), Vector3(0.85, 1.0, 0.22), Color("444f57"))
    _box(self, Vector3(0.0, 1.54, -3.17), Vector3(0.4, 0.12, 0.06), Color("b0a78b"))
    _box(self, Vector3(2.0, 1.25, -3.29), Vector3(1.4, 2.5, 0.15), Color("3f454d"))
    _box(self, Vector3(2.54, 1.15, -3.13), Vector3(0.08, 0.21, 0.07), Color("b4b6ac"))
    _box(self, Vector3(3.0, 1.25, -3.3), Vector3(0.3, 0.5, 0.21), Color("535f69"))

    overhead_light = OmniLight3D.new()
    overhead_light.position = Vector3(0, 3.2, -0.8)
    overhead_light.light_color = Color("c3d7eb")
    overhead_light.light_energy = 0.25
    overhead_light.omni_range = 8
    add_child(overhead_light)

    actor = Node3D.new()
    actor.name = "Eli"
    add_child(actor)
    var body_mesh := MeshInstance3D.new()
    var body_shape := CapsuleMesh.new()
    body_shape.radius = 0.28
    body_shape.height = 1.5
    body_mesh.mesh = body_shape
    body_mesh.position.y = 0.87
    var body_mat := StandardMaterial3D.new()
    body_mat.albedo_color = Color("8794a4")
    body_mesh.material_override = body_mat
    actor.add_child(body_mesh)
    var head := MeshInstance3D.new()
    var sphere := SphereMesh.new()
    sphere.radius = 0.21
    sphere.height = 0.42
    head.mesh = sphere
    head.position.y = 1.73
    var head_mat := StandardMaterial3D.new()
    head_mat.albedo_color = Color("bb998a")
    head.material_override = head_mat
    actor.add_child(head)
    handheld_light = OmniLight3D.new()
    handheld_light.position = Vector3(0.15, 1.3, -0.35)
    handheld_light.light_color = Color("e7e2bd")
    handheld_light.light_energy = 1.0
    handheld_light.omni_range = 4.0
    handheld_light.visible = false
    actor.add_child(handheld_light)

    var camera := Camera3D.new()
    camera.position = Vector3(0, 2.8, 5.6)
    camera.fov = 57.0
    add_child(camera)
    camera.look_at(Vector3(0, 1.1, -1.2), Vector3.UP)
    camera.current = true

func snapshot() -> Dictionary:
    var objects := {}
    for key in descriptions.keys():
        var is_held: bool = inventory.has(key)
        if key == "flashlight" and is_held:
            objects[key] = {"visible": true, "reachable": true, "can_take": false,
                "description": "The flashlight is in Eli's inventory. It is " + ("on." if flashlight_on else "off.")}
        else:
            var description: String = descriptions[key]
            if key == "breaker_box" and breaker_on:
                description = "The breaker box is switched on and the lights are working."
            objects[key] = {"visible": true, "reachable": true, "can_take": key == "flashlight",
                "description": description}
    return {"room": "maintenance_chamber", "inventory": inventory.duplicate(),
            "lights_on": breaker_on, "objects": objects}

func perform_action(action: String, target: String) -> void:
    if busy:
        action_finished.emit(action, target, false, "Eli is already performing an action.")
        return
    if not object_positions.has(target):
        action_finished.emit(action, target, false, "That object does not exist in this room.")
        return
    if action not in ["move_to", "inspect", "take", "use"]:
        action_finished.emit(action, target, false, "Unsupported physical action.")
        return
    busy = true
    if target == "flashlight" and inventory.has("flashlight") and action in ["use", "inspect"]:
        call_deferred("_finish_action", action, target)
        return
    var destination: Vector3 = object_positions[target]
    var tween := create_tween()
    tween.tween_property(actor, "position", destination, 1.2)
    tween.finished.connect(_finish_action.bind(action, target))

func _finish_action(action: String, target: String) -> void:
    busy = false
    var success := true
    var description := "Eli moved to " + target + "."
    if action == "inspect":
        description = str(descriptions.get(target, "Nothing unusual is visible."))
    elif action == "take":
        if target == "flashlight" and not inventory.has("flashlight"):
            inventory.append("flashlight")
            flashlight_mesh.visible = false
            description = "Eli picked up the flashlight. It is now in inventory."
        else:
            success = false
            description = "This object cannot be taken."
    elif action == "use":
        if target == "breaker_box" and not breaker_on:
            breaker_on = true
            overhead_light.light_energy = 1.5
            description = "Eli turned on the breaker. The overhead light is now on."
        elif target == "exit_door":
            success = false
            description = "The exit door is locked. A keypad is mounted beside it."
        elif target == "flashlight" and inventory.has("flashlight"):
            flashlight_on = not flashlight_on
            handheld_light.visible = flashlight_on
            description = "Eli switched " + ("on" if flashlight_on else "off") + " the handheld flashlight."
        else:
            success = false
            description = "Nothing happened when Eli tried that."
    action_finished.emit(action, target, success, description)

func export_state() -> Dictionary:
    return {"inventory": inventory.duplicate(), "breaker_on": breaker_on,
            "flashlight_on": flashlight_on,
            "actor_x": actor.position.x, "actor_z": actor.position.z}

func restore_state(data: Dictionary) -> void:
    inventory.clear()
    for item in data.get("inventory", []):
        if item == "flashlight" and not inventory.has(item):
            inventory.append(item)
    flashlight_mesh.visible = not inventory.has("flashlight")
    flashlight_on = bool(data.get("flashlight_on", false)) and inventory.has("flashlight")
    handheld_light.visible = flashlight_on
    breaker_on = bool(data.get("breaker_on", false))
    overhead_light.light_energy = 1.5 if breaker_on else 0.25
    actor.position = Vector3(float(data.get("actor_x", 0)), 0, float(data.get("actor_z", 0)))

func reset_state() -> void:
    restore_state({})
