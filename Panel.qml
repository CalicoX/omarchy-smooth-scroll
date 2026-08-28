import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

Panel {
  id: root
  moduleName: "stillpilot.smooth-scroll"
  ipcTarget: "stillpilot.smooth-scroll"

  property bool enabled: true
  property bool natural: true
  property int damping: 65
  property int acceleration: 35
  property var bindings: ({})
  property var bindingList: []
  property bool listening: false
  property string pendingCode: ""
  property string pendingLabel: ""
  property string listenHint: "Press a side button or tilt the wheel"
  property var shortcutOptions: []
  property string shortcutValue: ""
  property string focusSection: "enable"
  property int selectedIndex: -1
  property bool cursorActive: false
  readonly property string pluginDir: String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string daemonPath: pluginDir + "/daemon.py"
  readonly property var volumeActions: [
    { value: "volume-up", label: "Volume up", icon: "󰝝" },
    { value: "volume-down", label: "Volume down", icon: "󰝞" },
    { value: "volume-mute", label: "Mute", icon: "󰝟" }
  ]
  readonly property int bindCount: bindingList.length
  readonly property var visibleSections: ["enable", "natural", "damping", "acceleration", "listen"]

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function applyConfig(text) {
    var cfg = Model.parse(text)
    root.enabled = cfg.enabled
    root.natural = cfg.natural
    root.damping = cfg.damping
    root.acceleration = cfg.acceleration
    root.bindings = cfg.bindings
    root.bindingList = Model.bindingList(cfg.bindings)
  }

  function setKey(key, value) {
    Quickshell.execDetached(["python3", root.daemonPath, "set", key, String(value)])
  }

  function setEnabled(value) {
    root.enabled = value
    setKey("enabled", value)
  }

  function setNatural(value) {
    root.natural = value
    setKey("natural", value)
  }

  function setDamping(value) {
    root.damping = Model.clampInt(value, 0, 100)
    setKey("damping", root.damping)
  }

  function setAcceleration(value) {
    root.acceleration = Model.clampInt(value, 0, 100)
    setKey("acceleration", root.acceleration)
  }

  function bindAction(code, action) {
    if (!code) return
    Quickshell.execDetached(["python3", root.daemonPath, "bind", String(code), String(action)])
    var next = {}
    for (var k in root.bindings) next[k] = root.bindings[k]
    if (action === "none")
      delete next[code]
    else
      next[code] = action
    root.bindings = next
    root.bindingList = Model.bindingList(next)
    root.pendingCode = ""
    root.pendingLabel = ""
    root.shortcutValue = ""
  }

  function bindShortcut(code, jsonValue) {
    if (!code || !jsonValue) return
    Quickshell.execDetached(["python3", root.daemonPath, "bind", String(code), String(jsonValue)])
    var spec = {}
    try { spec = JSON.parse(jsonValue) } catch (e) { spec = { label: "Shortcut" } }
    var next = {}
    for (var k in root.bindings) next[k] = root.bindings[k]
    next[code] = spec
    root.bindings = next
    root.bindingList = Model.bindingList(next)
    root.pendingCode = ""
    root.pendingLabel = ""
    root.shortcutValue = ""
  }

  function loadShortcuts(text) {
    try {
      var rows = JSON.parse(String(text || "[]"))
      root.shortcutOptions = rows || []
    } catch (e) {
      root.shortcutOptions = []
    }
  }

  function startListen() {
    if (learnProc.running) return
    root.listening = true
    root.pendingCode = ""
    root.pendingLabel = ""
    root.listenHint = "Press a side button or tilt the wheel"
    learnProc.running = true
  }

  function cancelListen() {
    learnProc.running = false
    root.listening = false
  }

  function finishLearn(text) {
    root.listening = false
    var raw = String(text || "").trim()
    if (!raw || raw.indexOf("{") !== 0) {
      root.listenHint = "No button captured — try again"
      return
    }
    try {
      var rec = JSON.parse(raw)
      root.pendingCode = String(rec.code || "")
      root.pendingLabel = rec.label || Model.buttonLabel(root.pendingCode)
      root.listenHint = "Search and pick a keyboard shortcut"
    } catch (e) {
      root.listenHint = "No button captured — try again"
    }
  }

  function ensureCursorVisible(item) {
    if (!item || !scrollArea) return
    var flick = scrollArea.contentItem
    if (!flick || flick.contentY === undefined) return
    var pt = item.mapToItem(flick.contentItem || flick, 0, 0)
    var top = pt.y
    var bottom = top + (item.height || 0)
    var viewTop = flick.contentY
    var viewBottom = viewTop + flick.height
    var margin = 8
    if (top < viewTop + margin) flick.contentY = Math.max(0, top - margin)
    else if (bottom > viewBottom - margin)
      flick.contentY = bottom + margin - flick.height
  }

  function moveCursor(delta) {
    var sections = visibleSections
    var idx = sections.indexOf(focusSection)
    if (idx < 0) idx = 0
    idx = Math.max(0, Math.min(sections.length - 1, idx + delta))
    focusSection = sections[idx]
    selectedIndex = -1
    cursorActive = true
  }

  function adjustCurrent(delta) {
    if (focusSection === "enable") setEnabled(!enabled)
    else if (focusSection === "natural") setNatural(!natural)
    else if (focusSection === "damping") setDamping(damping + delta * 5)
    else if (focusSection === "acceleration") setAcceleration(acceleration + delta * 5)
    else if (focusSection === "listen") startListen()
  }

  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/smooth-scroll.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyConfig(text())
    onLoadFailed: root.applyConfig("")
  }

  Process {
    id: shortcutProc
    command: ["python3", root.daemonPath, "shortcuts"]
    running: root.opened
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.loadShortcuts(text)
    }
  }

  Process {
    id: learnProc
    command: ["python3", root.daemonPath, "learn", "12"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.finishLearn(text)
    }
    onRunningChanged: if (!running && root.listening && root.pendingCode === "") {
      root.listening = false
    }
    onExited: function(code) {
      root.listening = false
      if (code !== 0 && root.pendingCode === "")
        root.listenHint = "Timed out — press Bind again"
    }
  }

  Component.onCompleted: {
    if (root.pluginDir)
      Quickshell.execDetached(["bash", root.pluginDir + "/install.sh", "--ensure"])
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.enabled ? "󰍽" : "󰍾"
    tooltipText: root.enabled ? (root.bindCount ? ("Mouse · " + root.bindCount + " binds") : "Mouse") : "Mouse off"
    onPressed: function() { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: shortcutPicker.popupOpen
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.adjustCurrent(dx)
      }
      onActivateRequested: {
        if (root.focusSection === "listen") root.startListen()
        else if (root.focusSection === "enable") root.setEnabled(!root.enabled)
        else if (root.focusSection === "natural") root.setNatural(!root.natural)
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: panelColumn.implicitHeight > height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(16)

          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight, powerSwitch.implicitHeight)

            Text {
              id: heroIcon
              text: "󰍽"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              opacity: root.enabled ? 1 : 0.45
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            ToggleSwitch {
              id: powerSwitch
              checked: root.enabled
              hasCursor: root.cursorActive && root.focusSection === "enable"
              foreground: root.bar.foreground
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onHovered: function(on) {
                if (on) {
                  root.cursorActive = true
                  root.focusSection = "enable"
                }
              }
              onToggled: root.setEnabled(!root.enabled)
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: powerSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                text: "Mouse"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                text: root.enabled
                  ? (root.bindCount === 0 ? "SMOOTH SCROLL" : (root.bindCount + " BUTTON BIND" + (root.bindCount === 1 ? "" : "S")))
                  : "PAUSED"
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
                width: parent.width
              }
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          Column {
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: "SCROLL"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Toggle {
              width: parent.width
              label: "Natural direction"
              description: "Wheel down moves the page down"
              checked: root.natural
              hasCursor: root.cursorActive && root.focusSection === "natural"
              foreground: root.bar.foreground
              onClicked: root.setNatural(!root.natural)
              onHovered: function(on) {
                if (on) { root.cursorActive = true; root.focusSection = "natural" }
              }
            }

            SliderBlock {
              title: "INERTIA"
              valueText: root.damping + "%"
              section: "damping"
              sliderValue: root.damping
              onLive: function(v) { root.damping = Math.round(v) }
              onCommit: function(v) { root.setDamping(v) }
            }

            SliderBlock {
              title: "FLICK"
              valueText: root.acceleration + "%"
              section: "acceleration"
              sliderValue: root.acceleration
              onLive: function(v) { root.acceleration = Math.round(v) }
              onCommit: function(v) { root.setAcceleration(v) }
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          Column {
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: "BUTTONS"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            CursorSurface {
              id: captureCard
              width: parent.width
              implicitHeight: captureInner.implicitHeight + Style.space(22)
              outline: true
              foreground: root.bar.foreground
              hasCursor: root.cursorActive && root.focusSection === "listen"
              onHasCursorChanged: if (hasCursor) root.ensureCursorVisible(captureCard)

              Column {
                id: captureInner
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(14)
                anchors.rightMargin: Style.space(14)
                spacing: Style.space(10)

                Row {
                  width: parent.width
                  spacing: Style.space(10)

                  Text {
                    text: root.listening ? "󰍽" : (root.pendingCode !== "" ? "󰌐" : "󰳽")
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.title
                    opacity: root.listening ? pulse.opacity : 1
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Column {
                    width: parent.width - Style.space(36)
                    spacing: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      text: root.listening
                        ? "Waiting for a press…"
                        : (root.pendingCode !== "" ? root.pendingLabel : "Bind a mouse button")
                      color: root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.subtitle
                      font.bold: true
                      elide: Text.ElideRight
                      width: parent.width
                    }

                    Text {
                      text: root.listenHint
                      color: Qt.darker(root.bar.foreground, 1.45)
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.WordWrap
                      width: parent.width
                    }
                  }
                }

                Button {
                  width: parent.width
                  text: root.listening ? "Cancel" : (root.pendingCode !== "" ? "Press a different button" : "Listen for a button")
                  bordered: true
                  foreground: root.bar.foreground
                  onClicked: root.listening ? root.cancelListen() : root.startListen()
                }

                SearchableDropdown {
                  id: shortcutPicker
                  visible: root.pendingCode !== ""
                  width: parent.width
                  label: "Keyboard shortcut"
                  placeholderText: "Search Super+K shortcuts…"
                  emptyText: "No matching shortcut"
                  triggerLabel: "Choose a shortcut"
                  options: root.shortcutOptions
                  value: root.shortcutValue
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  onChanged: function(v) { root.bindShortcut(root.pendingCode, v) }
                }

                Text {
                  visible: root.pendingCode !== ""
                  text: "OR VOLUME"
                  color: Qt.darker(root.bar.foreground, 1.5)
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 1.4
                }

                Flow {
                  visible: root.pendingCode !== ""
                  width: parent.width
                  spacing: Style.space(6)

                  Repeater {
                    model: root.volumeActions
                    Button {
                      required property var modelData
                      text: modelData.icon + "  " + modelData.label
                      bordered: true
                      foreground: root.bar.foreground
                      onClicked: root.bindAction(root.pendingCode, modelData.value)
                    }
                  }
                }
              }

              HoverHandler {
                onHoveredChanged: if (hovered) {
                  root.cursorActive = true
                  root.focusSection = "listen"
                }
              }

              SequentialAnimation {
                id: pulse
                running: root.listening
                loops: Animation.Infinite
                property real opacity: 1
                NumberAnimation { target: pulse; property: "opacity"; from: 1; to: 0.35; duration: 700; easing.type: Easing.InOutQuad }
                NumberAnimation { target: pulse; property: "opacity"; from: 0.35; to: 1; duration: 700; easing.type: Easing.InOutQuad }
              }
            }

            Repeater {
              model: root.bindingList

              CursorSurface {
                id: bindRow
                required property var modelData
                width: panelColumn.width
                implicitHeight: bindInner.implicitHeight + Style.spacing.xl
                outline: true
                foreground: root.bar.foreground

                Row {
                  id: bindInner
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(12)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(10)

                  Text {
                    text: Model.actionIcon(bindRow.modelData.spec || bindRow.modelData.action)
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.title
                    width: Style.space(22)
                    horizontalAlignment: Text.AlignHCenter
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Column {
                    width: parent.width - Style.space(22) - clearBtn.width - Style.space(20)
                    spacing: 1
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      text: Model.buttonLabel(bindRow.modelData.code)
                      color: root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.body
                      font.bold: true
                      elide: Text.ElideRight
                      width: parent.width
                    }

                    Text {
                      text: bindRow.modelData.label || Model.actionLabel(bindRow.modelData.spec || bindRow.modelData.action)
                      color: Qt.darker(root.bar.foreground, 1.45)
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                      width: parent.width
                    }
                  }

                  Button {
                    id: clearBtn
                    text: "Clear"
                    bordered: true
                    foreground: root.bar.foreground
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: root.bindAction(bindRow.modelData.code, "none")
                  }
                }
              }
            }

            Text {
              visible: root.bindingList.length === 0 && root.pendingCode === ""
              width: parent.width
              text: "No binds yet. Capture a side button, then search the Super+K shortcut list — or pick volume."
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
        }
      }
    }
  }

  component SliderBlock: Column {
    id: block
    width: panelColumn.width
    spacing: Style.space(6)
    required property string title
    required property string valueText
    required property string section
    required property real sliderValue
    signal live(real v)
    signal commit(real v)

    Item {
      width: parent.width
      implicitHeight: hdr.implicitHeight

      PanelSectionHeader {
        id: hdr
        text: block.title
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        text: block.valueText
        color: Qt.darker(root.bar.foreground, 1.4)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        anchors.right: parent.right
        anchors.rightMargin: Style.space(6)
        anchors.verticalCenter: parent.verticalCenter
      }
    }

    CursorSurface {
      id: row
      width: parent.width
      height: slider.implicitHeight + Style.spacing.controlGap
      hasCursor: root.cursorActive && root.focusSection === block.section
      onHasCursorChanged: if (hasCursor) root.ensureCursorVisible(row)
      foreground: root.bar.foreground
      outline: true

      PanelSlider {
        id: slider
        bar: root.bar
        anchors.fill: parent
        anchors.leftMargin: Style.space(6)
        anchors.rightMargin: Style.space(6)
        minimum: 0
        maximum: 100
        step: 1
        integer: true
        value: block.sliderValue
        onMoved: function(v) { block.live(v) }
        onReleased: function(v) { block.commit(v) }
      }

      HoverHandler {
        onHoveredChanged: if (hovered) {
          root.cursorActive = true
          root.focusSection = block.section
        }
      }
    }
  }
}
