import QtQuick
import QtQuick.Controls
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
  property real wheelAccumulator: 0
  property string focusSection: "enabled"
  property int selectedIndex: -1
  property bool cursorActive: false
  readonly property string pluginDir: String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string daemonPath: pluginDir + "/daemon.py"
  readonly property var visibleSections: ["enabled", "natural", "damping", "acceleration"]

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function applyConfig(text) {
    var cfg = Model.parse(text)
    root.enabled = cfg.enabled
    root.natural = cfg.natural
    root.damping = cfg.damping
    root.acceleration = cfg.acceleration
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

  function ensureCursorVisible(item) {
    if (!item || !scrollArea) return
    var flick = scrollArea.contentItem
    if (!flick || flick.contentY === undefined) return
    var pt = item.mapToItem(flick.contentItem || flick, 0, 0)
    var top = pt.y
    var bottom = top + (item.height || 0)
    var viewTop = flick.contentY
    var viewBottom = viewTop + flick.height
    var margin = 6
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
    if (focusSection === "enabled") setEnabled(!enabled)
    else if (focusSection === "natural") setNatural(!natural)
    else if (focusSection === "damping") setDamping(damping + delta * 5)
    else if (focusSection === "acceleration") setAcceleration(acceleration + delta * 5)
  }

  function activateCursor() {
    if (focusSection === "enabled") setEnabled(!enabled)
    else if (focusSection === "natural") setNatural(!natural)
  }

  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/smooth-scroll.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyConfig(text())
    onLoadFailed: root.applyConfig("")
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
    tooltipText: root.enabled ? "Smooth scroll on" : "Smooth scroll off"
    onPressed: function() { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(460))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.adjustCurrent(dx)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
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
          spacing: Style.space(14)

          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

            Text {
              id: heroIcon
              text: "󰍽"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                text: "Smooth Scroll"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                text: root.enabled ? "ON" : "OFF"
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
              }
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          Toggle {
            width: parent.width
            label: "Enable"
            description: "Smooth out clicky mouse-wheel steps"
            checked: root.enabled
            hasCursor: root.cursorActive && root.focusSection === "enabled"
            foreground: root.bar.foreground
            onClicked: root.setEnabled(!root.enabled)
            onHovered: function(isHovered) {
              if (isHovered) {
                root.cursorActive = true
                root.focusSection = "enabled"
              }
            }
          }

          Toggle {
            width: parent.width
            label: "Natural direction"
            description: "Wheel down moves content down"
            checked: root.natural
            hasCursor: root.cursorActive && root.focusSection === "natural"
            foreground: root.bar.foreground
            onClicked: root.setNatural(!root.natural)
            onHovered: function(isHovered) {
              if (isHovered) {
                root.cursorActive = true
                root.focusSection = "natural"
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: dampingHeader.implicitHeight

              PanelSectionHeader {
                id: dampingHeader
                text: "DAMPING"
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: root.damping + "%"
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
              id: dampingRow
              width: parent.width
              height: dampingSlider.implicitHeight + Style.spacing.controlGap
              hasCursor: root.cursorActive && root.focusSection === "damping"
              onHasCursorChanged: if (hasCursor) root.ensureCursorVisible(dampingRow)
              foreground: root.bar.foreground
              outline: true

              PanelSlider {
                id: dampingSlider
                bar: root.bar
                anchors.fill: parent
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                minimum: 0
                maximum: 100
                step: 1
                integer: true
                value: root.damping
                onMoved: function(v) { root.damping = Math.round(v) }
                onReleased: function(v) { root.setDamping(v) }
              }

              HoverHandler {
                onHoveredChanged: if (hovered) {
                  root.cursorActive = true
                  root.focusSection = "damping"
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: accelHeader.implicitHeight

              PanelSectionHeader {
                id: accelHeader
                text: "ACCELERATION"
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: root.acceleration + "%"
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
              id: accelRow
              width: parent.width
              height: accelSlider.implicitHeight + Style.spacing.controlGap
              hasCursor: root.cursorActive && root.focusSection === "acceleration"
              onHasCursorChanged: if (hasCursor) root.ensureCursorVisible(accelRow)
              foreground: root.bar.foreground
              outline: true

              PanelSlider {
                id: accelSlider
                bar: root.bar
                anchors.fill: parent
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                minimum: 0
                maximum: 100
                step: 1
                integer: true
                value: root.acceleration
                onMoved: function(v) { root.acceleration = Math.round(v) }
                onReleased: function(v) { root.setAcceleration(v) }
              }

              HoverHandler {
                onHoveredChanged: if (hovered) {
                  root.cursorActive = true
                  root.focusSection = "acceleration"
                }
              }
            }
          }
        }
      }
    }
  }
}
