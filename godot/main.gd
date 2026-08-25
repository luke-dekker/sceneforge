extends Node3D
## Loads a prepped sceneforge scene (glb + scene.json sidecar), gives it
## trimesh collision, and drops a walk/fly player into it.

static var scene_idx := 0  # survives reload_current_scene, so Tab cycles

var scene_dirs: Array[String] = []
var scene_names: Array[String] = []
var georef: Dictionary = {}
var menu: CanvasLayer


func _ready() -> void:
	# Main stays ALWAYS so Esc works while paused; gameplay children are
	# explicitly PAUSABLE so the menu actually freezes the world.
	process_mode = Node.PROCESS_MODE_ALWAYS
	_discover_scenes()
	_load_georef()
	_build_environment()
	_load_scene()
	_spawn_player()
	_build_hud()
	_build_menu()


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey and event.pressed):
		return
	if event.physical_keycode == KEY_ESCAPE:
		_toggle_menu()
	elif event.physical_keycode == KEY_TAB and not get_tree().paused \
			and scene_dirs.size() > 1:
		_switch_scene((scene_idx + 1) % scene_dirs.size())
	elif event.physical_keycode == KEY_F12:
		_save_screenshot()


func _save_screenshot() -> void:
	# Full-resolution frame grab next to the exe (or the project in the editor),
	# named by scene + timestamp; for reports, story maps and bug reports.
	var dir := ("res://" if OS.has_feature("editor")
			else OS.get_executable_path().get_base_dir()) + "/screenshots"
	DirAccess.make_dir_recursive_absolute(dir)
	var stamp := Time.get_datetime_string_from_system(false, true).replace(":", "-").replace(" ", "_")
	var path := "%s/%s_%s.png" % [dir, scene_names[scene_idx] if scene_names.size() > 0 else "scene", stamp]
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(path)
	print("screenshot %s -> %s" % [path, "ok" if err == OK else error_string(err)])


func _switch_scene(i: int) -> void:
	scene_idx = i
	get_tree().paused = false
	get_tree().reload_current_scene()


func _toggle_menu() -> void:
	var opening := not menu.visible
	menu.visible = opening
	get_tree().paused = opening
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE if opening else Input.MOUSE_MODE_CAPTURED


func _build_menu() -> void:
	menu = CanvasLayer.new()
	menu.layer = 100
	menu.process_mode = Node.PROCESS_MODE_ALWAYS
	var bg := ColorRect.new()
	bg.color = Color(0.055, 0.06, 0.075, 0.93)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	menu.add_child(bg)
	var box := VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_CENTER)
	box.add_theme_constant_override("separation", 10)
	var title := Label.new()
	title.text = "SCENEFORGE / WALKER"
	title.add_theme_color_override("font_color", Color("#ff6a00"))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(title)
	for i in scene_dirs.size():
		var b := Button.new()
		b.text = scene_names[i] + ("   ◂" if i == scene_idx else "")
		b.custom_minimum_size = Vector2(340, 40)
		if i != scene_idx:
			b.pressed.connect(_switch_scene.bind(i))
		box.add_child(b)
	var resume := Button.new()
	resume.text = "RESUME"
	resume.custom_minimum_size = Vector2(340, 40)
	resume.pressed.connect(_toggle_menu)
	box.add_child(resume)
	var quit := Button.new()
	quit.text = "QUIT"
	quit.custom_minimum_size = Vector2(340, 40)
	quit.pressed.connect(func(): get_tree().quit())
	box.add_child(quit)
	menu.add_child(box)
	menu.visible = false
	add_child(menu)


func _scenes_root() -> String:
	# In the editor, scenes live in the project; in an exported build they sit
	# in a plain folder next to the executable so anyone can drop new ones in.
	if OS.has_feature("editor"):
		return "res://scenes"
	return OS.get_executable_path().get_base_dir() + "/scenes"


func _scene_dir() -> String:
	return _scenes_root() + "/" + scene_dirs[scene_idx]


func _discover_scenes() -> void:
	var root := _scenes_root()
	if DirAccess.dir_exists_absolute(root):
		for d in DirAccess.get_directories_at(root):
			var sj := "%s/%s/scene.json" % [root, d]
			if FileAccess.file_exists(sj):
				scene_dirs.append(d)
				var j = JSON.parse_string(FileAccess.open(sj, FileAccess.READ).get_as_text())
				scene_names.append(j.get("name", d) if j is Dictionary else d)
	if scene_dirs.is_empty():
		push_error("no scenes with scene.json under " + root)


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
	var scene: Node
	if glb.begins_with("res://"):
		scene = (load(glb) as PackedScene).instantiate()
	else:
		# Exported build: parse the glb at runtime from the external folder.
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		if doc.append_from_file(glb, state) != OK:
			push_error("failed to load " + glb)
			return
		scene = doc.generate_scene(state)
	add_child(scene)
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		mi.create_trimesh_collision()


func _spawn_player() -> void:
	var player := preload("res://player.gd").new()
	player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(player)
	# Start above the terrain's highest point and settle under gravity.
	var elev: Array = georef.get("terrain_elevation_range_m", [0.0, 50.0])
	var z0: float = georef.get("crs", {}).get("z_offset", 0.0)
	player.position = Vector3(0, elev[1] - z0 + 5.0, 0)
	var surveyor := preload("res://surveyor.gd").new()
	surveyor.process_mode = Node.PROCESS_MODE_PAUSABLE
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
	] + "\nLMB measure  C clear  Tab next scene  F12 screenshot  Esc menu"
	label.position = Vector2(8, 8)
	label.add_theme_color_override("font_color", Color.WHITE)
	label.add_theme_constant_override("outline_size", 4)
	label.add_theme_color_override("font_outline_color", Color.BLACK)
	var ui := CanvasLayer.new()
	ui.add_child(label)
	add_child(ui)
