.pragma library

function defaults() {
  return { enabled: true, natural: true, damping: 65, acceleration: 35 }
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
  } catch (e) {
  }
  return cfg
}

function clampInt(value, lo, hi) {
  var n = Math.round(Number(value))
  if (isNaN(n)) n = lo
  return Math.max(lo, Math.min(hi, n))
}
