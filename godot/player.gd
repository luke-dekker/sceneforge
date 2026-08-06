extends CharacterBody3D
## Minimal walk/fly controller: WASD + mouse look, Shift to run, F toggles fly.

const WALK_SPEED := 4.0
const RUN_MULT := 3.0
const FLY_SPEED := 15.0
const GRAVITY := 9.8
const MOUSE_SENS := 0.002

var flying := false
var cam: Camera3D


func _ready() -> void:
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.height = 1.8
	shape.shape = capsule
	add_child(shape)
	cam = Camera3D.new()
	cam.position.y = 0.7
	cam.far = 2000.0
	add_child(cam)
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotation.y -= event.relative.x * MOUSE_SENS
		cam.rotation.x = clampf(cam.rotation.x - event.relative.y * MOUSE_SENS, -1.5, 1.5)
	elif event is InputEventKey and event.pressed:
		match event.physical_keycode:
			KEY_ESCAPE:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE if \
					Input.mouse_mode == Input.MOUSE_MODE_CAPTURED else Input.MOUSE_MODE_CAPTURED
			KEY_F:
				flying = not flying
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _key_axis(neg: Key, pos: Key) -> float:
	return float(Input.is_physical_key_pressed(pos)) - float(Input.is_physical_key_pressed(neg))


func _physics_process(delta: float) -> void:
	var input := Vector2(
		_key_axis(KEY_A, KEY_D),
		_key_axis(KEY_W, KEY_S))
	var dir := (transform.basis * Vector3(input.x, 0, input.y)).normalized()
	var speed := (FLY_SPEED if flying else WALK_SPEED) \
		* (RUN_MULT if Input.is_physical_key_pressed(KEY_SHIFT) else 1.0)

	if flying:
		var vert := 0.0
		if Input.is_physical_key_pressed(KEY_SPACE): vert += 1.0
		if Input.is_physical_key_pressed(KEY_CTRL): vert -= 1.0
		velocity = (dir + Vector3(0, vert, 0)) * speed
	else:
		velocity.x = dir.x * speed
		velocity.z = dir.z * speed
		velocity.y = 0.0 if is_on_floor() else velocity.y - GRAVITY * delta
	move_and_slide()
