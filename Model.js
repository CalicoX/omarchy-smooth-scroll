.pragma library

function defaults() {
  return {
    enabled: true,
    natural: true,
    damping: 65,
    acceleration: 35,
    autoUpdate: true,
    bindings: {}
  }
}

function actions() {
  return [
    { value: "keybindings", label: "Keybindings", hint: "Super+K", icon: "" },
    { value: "volume-up", label: "Volume up", hint: "Raise", icon: "󰝝" },
    { value: "volume-down", label: "Volume down", hint: "Lower", icon: "󰝞" },
    { value: "volume-mute", label: "Mute", hint: "Toggle", icon: "󰝟" },
    { value: "play-pause", label: "Play / Pause", hint: "Media", icon: "󰐎" },
    { value: "next-track", label: "Next track", hint: "Media", icon: "󰒭" },
    { value: "prev-track", label: "Previous track", hint: "Media", icon: "󰒮" }
  ]
}

function actionLabel(id) {
  if (id && typeof id === "object")
    return id.label || "Shortcut"
  var list = actions()
  for (var i = 0; i < list.length; i++)
    if (list[i].value === id) return list[i].label
  return id || "Unbound"
}

function actionIcon(id) {
  if (id && typeof id === "object")
    return ""
  var list = actions()
  for (var i = 0; i < list.length; i++)
    if (list[i].value === id) return list[i].icon
  return "󰌌"
}

function buttonLabel(code) {
  var map = {
    "272": "Left click",
    "273": "Right click",
    "274": "Wheel click",
    "275": "Thumb back",
    "276": "Thumb forward",
    "277": "Forward",
    "278": "Back",
    "279": "Task",
    "tilt-left": "Wheel tilt left",
    "tilt-right": "Wheel tilt right"
  }
  if (map[String(code)]) return map[String(code)]
  if (String(code).indexOf("tilt-") === 0) return String(code)
  return "Button " + code
}

function parse(text) {
  var cfg = defaults()
  if (!text)
    return cfg
  try {
    var raw = JSON.parse(text)
    if (!raw || typeof raw !== "object")
      return cfg
    if (raw.enabled !== undefined) cfg.enabled = !!raw.enabled
    if (raw.natural !== undefined) cfg.natural = !!raw.natural
    if (raw.damping !== undefined) cfg.damping = clampInt(raw.damping, 0, 100)
    if (raw.acceleration !== undefined) cfg.acceleration = clampInt(raw.acceleration, 0, 100)
    if (raw.auto_update !== undefined) cfg.autoUpdate = !!raw.auto_update
    if (raw.bindings && typeof raw.bindings === "object") {
      var b = {}
      for (var k in raw.bindings) {
        if (raw.bindings[k] && raw.bindings[k] !== "none")
          b[String(k)] = raw.bindings[k]
      }
      cfg.bindings = b
    }
  } catch (e) {
  }
  return cfg
}

function bindingList(bindings) {
  var rows = []
  if (!bindings) return rows
  for (var k in bindings) {
    var spec = bindings[k]
    rows.push({
      code: String(k),
      action: (spec && typeof spec === "object") ? "shortcut" : String(spec),
      spec: spec,
      label: actionLabel(spec)
    })
  }
  rows.sort(function(a, b) { return a.code.localeCompare(b.code) })
  return rows
}

function clampInt(value, lo, hi) {
  var n = Math.round(Number(value))
  if (isNaN(n)) n = lo
  return Math.max(lo, Math.min(hi, n))
}
