extends Node3D
## Loads a prepped sceneforge scene (glb + scene.json sidecar), gives it
## trimesh collision, and drops a walk/fly player into it.

static var scene_idx := 0  # survives reload_current_scene, so Tab cycles

var scene_dirs: Array[String] = []
var georef: Dictionary = {}


func _ready() -> void:
	_discover_scenes()
	_load_georef()
	_build_environment()
	_load_scene()
	_spawn_player()
	_build_hud()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.physical_keycode == KEY_TAB \
			and scene_dirs.size() > 1:
		scene_idx = (scene_idx + 1) % scene_dirs.size()
		get_tree().reload_current_scene()


func _scene_dir() -> String:
	return "res://scenes/" + scene_dirs[scene_idx]


func _discover_scenes() -> void:
	for d in DirAccess.get_directories_at("res://scenes"):
		if FileAccess.file_exists("res://scenes/%s/scene.json" % d):
			scene_dirs.append(d)
	if scene_dirs.is_empty():
		push_error("no scenes with scene.json under res://scenes")


func _load_georef() -> void:
	var f := FileAccess.open(_scene_dir() + "/scene.json", FileAccess.READ)
	if f:
		georef = JSON.parse_string(f.get_as_text())
	else:
		push_warning("scene.json not found in " + _scene_dir())


func _load_scene() -> void:
	var glb := ""
	for f in DirAccess.get_files_at(_scene_dir()):
		if f.ends_with(".glb"):
			glb = _scene_dir() + "/" + f
			break
	var packed: PackedScene = load(glb)
	var scene := packed.instantiate()
	add_child(scene)
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		mi.create_trimesh_collision()


func _spawn_player() -> void:
	var player := preload("res://player.gd").new()
	add_child(player)
	# Start above the terrain's highest point and settle under gravity.
	var elev: Array = georef.get("terrain_elevation_range_m", [0.0, 50.0])
	var z0: float = georef.get("crs", {}).get("z_offset", 0.0)
	player.position = Vector3(0, elev[1] - z0 + 5.0, 0)
	var surveyor := preload("res://surveyor.gd").new()
	surveyor.cam = player.cam
	surveyor.georef = georef
	surveyor.exclude_body = player
	add_child(surveyor)


func _build_environment() -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, 30, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var env := WorldEnvironment.new()
	var e := Environment.new()
	var sky := Sky.new()
	sky.sky_material = ProceduralSkyMaterial.new()
	e.background_mode = Environment.BG_SKY
	e.sky = sky
	env.environment = e
	add_child(env)


func _build_hud() -> void:
	var label := Label.new()
	var origin: Dictionary = georef.get("origin_geopose", {}).get("position", {})
	label.text = "%s | %s\norigin: %.6f, %.6f, h=%.1f m\nWASD move  Shift run  F fly  Esc mouse" % [
		georef.get("name", "scene"),
		georef.get("crs", {}).get("proj4", "no georef"),
		origin.get("lat", 0.0), origin.get("lon", 0.0), origin.get("h", 0.0),
	] + "\nLMB measure  C clear  Tab next scene"
	label.position = Vector2(8, 8)
	label.add_theme_color_override("font_color", Color.WHITE)
	label.add_theme_constant_override("outline_size", 4)
	label.add_theme_color_override("font_outline_color", Color.BLACK)
	var ui := CanvasLayer.new()
	ui.add_child(label)
	add_child(ui)
