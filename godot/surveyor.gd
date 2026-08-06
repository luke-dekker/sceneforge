extends Node3D
## Surveyor mode: live georeferenced readout of the crosshair point, plus
## click-to-measure distances. Geo conversion comes entirely from scene.json
## (UTM offset + WGS84 jacobian) — no projection math in-engine.

var cam: Camera3D
var georef: Dictionary = {}
var exclude_body: CollisionObject3D

var _hit = null  # Vector3 or null — current crosshair terrain point
var _point_a = null
var _point_b = null
var _markers: Array[Node3D] = []
var _line: MeshInstance3D
var _label: Label


func _ready() -> void:
	_line = MeshInstance3D.new()
	_line.mesh = ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color.YELLOW
	_line.material_override = mat
	add_child(_line)
	_build_hud()


func _build_hud() -> void:
	var ui := CanvasLayer.new()
	add_child(ui)
	var crosshair := Label.new()
	crosshair.text = "+"
	crosshair.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	_style(crosshair)
	ui.add_child(crosshair)
	_label = Label.new()
	_label.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	_label.offset_left = 8
	_label.offset_bottom = -8
	_label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_style(_label)
	ui.add_child(_label)


func _style(label: Label) -> void:
	label.add_theme_color_override("font_color", Color.WHITE)
	label.add_theme_constant_override("outline_size", 4)
	label.add_theme_color_override("font_outline_color", Color.BLACK)


func _unhandled_input(event: InputEvent) -> void:
	if Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		return
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT and _hit != null:
		if _point_a == null or _point_b != null:
			_clear_measure()
			_point_a = _hit
			_add_marker(_point_a)
		else:
			_point_b = _hit
			_add_marker(_point_b)
			_draw_line()
	elif event is InputEventKey and event.pressed and event.physical_keycode == KEY_C:
		_clear_measure()


func _physics_process(_delta: float) -> void:
	var from := cam.global_position
	var to := from - cam.global_transform.basis.z * 2000.0
	var query := PhysicsRayQueryParameters3D.create(from, to)
	if exclude_body:
		query.exclude = [exclude_body.get_rid()]
	var result := get_world_3d().direct_space_state.intersect_ray(query)
	_hit = result.get("position") if result else null
	_update_label()


func _geo(p: Vector3) -> Dictionary:
	var offset: Array = georef.get("crs", {}).get("utm_offset", [0.0, 0.0])
	var z0: float = georef.get("crs", {}).get("z_offset", 0.0)
	var de := p.x
	var dn := -p.z
	var out := {"e": de + offset[0], "n": dn + offset[1], "h": p.y + z0}
	var origin: Dictionary = georef.get("origin_geopose", {}).get("position", {})
	var j: Dictionary = georef.get("wgs84_jacobian", {})
	if origin and j:
		out["lat"] = origin["lat"] + j["dlat_de"] * de + j["dlat_dn"] * dn
		out["lon"] = origin["lon"] + j["dlon_de"] * de + j["dlon_dn"] * dn
	return out


func _update_label() -> void:
	var lines := []
	if _hit != null:
		var g := _geo(_hit)
		if g.has("lat"):
			lines.append("%.7f, %.7f" % [g["lat"], g["lon"]])
		lines.append("UTM %.1f E  %.1f N   elev %.2f m" % [g["e"], g["n"], g["h"]])
	else:
		lines.append("no terrain under crosshair")
	if _point_a != null and _point_b == null:
		lines.append("measuring… (LMB to set point B, C to cancel)")
	elif _point_a != null and _point_b != null:
		var d3: float = _point_a.distance_to(_point_b)
		var dh := Vector2(_point_b.x - _point_a.x, _point_b.z - _point_a.z).length()
		var dv: float = _point_b.y - _point_a.y
		lines.append("dist %.2f m   horiz %.2f m   rise %+.2f m" % [d3, dh, dv])
	_label.text = "\n".join(lines)


func _add_marker(p: Vector3) -> void:
	var m := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.15
	sphere.height = 0.3
	m.mesh = sphere
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color.ORANGE
	m.material_override = mat
	m.position = p
	add_child(m)
	_markers.append(m)


func _draw_line() -> void:
	var im: ImmediateMesh = _line.mesh
	im.clear_surfaces()
	im.surface_begin(Mesh.PRIMITIVE_LINES)
	im.surface_add_vertex(_point_a + Vector3.UP * 0.05)
	im.surface_add_vertex(_point_b + Vector3.UP * 0.05)
	im.surface_end()


func _clear_measure() -> void:
	_point_a = null
	_point_b = null
	for m in _markers:
		m.queue_free()
	_markers.clear()
	(_line.mesh as ImmediateMesh).clear_surfaces()
