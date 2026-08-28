# Smooth Scroll for Omarchy 4

An Omarchy 4 bar plugin that turns a clicky mouse wheel into **smooth, inertial scrolling** on Hyprland.

The bar icon (bottom-right by default) opens a panel where you can:

- **Enable** — turn smoothing on or off
- **Natural direction** — invert the wheel (wheel down moves content down)
- **Damping** — how long the scroll coasts after you stop
- **Acceleration** — extra distance when you flick the wheel quickly

A small userspace daemon grabs your physical mice, passes movement and buttons through unchanged, and interpolates each wheel detent into high-resolution `REL_WHEEL_HI_RES` events.

Works on Wayland. No extra Python packages. You need write access to `/dev/uinput` (Omarchy usually grants this via the `input` group).

## Install

```bash
omarchy plugin add https://github.com/CalicoX/omarchy-smooth-scroll.git --enable
~/.config/omarchy/plugins/stillpilot.smooth-scroll/install.sh
```

`--enable` asks where to put the widget; pick **right** for the bottom-right corner.

`install.sh` writes a systemd **user** unit so the daemon starts with your graphical session.

If `/dev/uinput` is not writable:

```bash
sudo gpasswd -a "$USER" input
```

Then log out and back in.

### Update

```bash
omarchy plugin update stillpilot.smooth-scroll
```

### Uninstall

```bash
~/.config/omarchy/plugins/stillpilot.smooth-scroll/uninstall.sh
omarchy plugin remove stillpilot.smooth-scroll
```

## Controls

| Control | Default | Meaning |
|---|---|---|
| Enable | on | Grab the wheel and interpolate |
| Natural direction | on | Invert scroll direction |
| Damping | 65 | Higher = longer coast, slower stop |
| Acceleration | 35 | Higher = faster flicks travel farther |

The same values live in `~/.config/omarchy/smooth-scroll.json`. The daemon reloads that file on change, so sliders apply immediately.

IPC:

```bash
omarchy-shell stillpilot.smooth-scroll toggle   # open / close the panel
python3 ~/.config/omarchy/plugins/stillpilot.smooth-scroll/daemon.py get
python3 ~/.config/omarchy/plugins/stillpilot.smooth-scroll/daemon.py set damping 50
```

Menu: **Setup → Smooth Scroll** (added by `install.sh`).

## How it works

1. Discover mice that report `REL_X` plus a wheel axis.
2. Create a virtual pointer named `Omarchy Smooth Scroll`.
3. Grab each physical mouse exclusively.
4. Re-emit motion, buttons, and everything except wheel events.
5. Convert each detent into a decaying burst of high-res wheel events (~125 Hz).

While the daemon is running it forces Hyprland `input.natural_scroll` off so direction is not inverted twice. Turning **Enable** off ungrabs the hardware and restores Hyprland's invert from the **Natural direction** toggle.

## Requirements

- Omarchy 4 (Hyprland + omarchy-shell)
- `python3` (stdlib only)
- Membership in the `input` group, or equivalent ACL on `/dev/uinput`

## Troubleshooting

**Bar icon missing.** The widget must have a non-zero width. After updating, run `omarchy restart shell`. Confirm it is in the right section of `~/.config/omarchy/shell.json`.

**Pointer frozen.** Stop the daemon: `systemctl --user stop stillpilot-smooth-scroll`. The kernel ungrabs on process exit. Restart with `install.sh`.

**No smoothing.** `systemctl --user status stillpilot-smooth-scroll`. `daemon.py list` should print your mice. If `/dev/uinput` is not writable, add the `input` group and re-login.

**Double invert.** Disable Hyprland's own invert in `~/.config/hypr/input.lua` (`natural_scroll = false`) and use the plugin toggle.

---

# Omarchy 4 平滑滚动插件

把机械滚轮变成带惯性的平滑滚动。底栏图标默认在右下角，点开可调：

- **Enable**：开关
- **Natural direction**：滚动方向（向下滚，内容跟着向下）
- **Damping**：阻尼 / 惯性，越大滑得越远、停得越慢
- **Acceleration**：连滚加速

## 安装

```bash
omarchy plugin add https://github.com/CalicoX/omarchy-smooth-scroll.git --enable
~/.config/omarchy/plugins/stillpilot.smooth-scroll/install.sh
```

`--enable` 时选 **right**，图标会出现在底栏右侧、电源按钮旁边。

`install.sh` 会注册用户 systemd 服务，登录图形会话后自动启动守护进程。

若无法写入 `/dev/uinput`：

```bash
sudo gpasswd -a "$USER" input
```

然后重新登录。

### 更新 / 卸载

```bash
omarchy plugin update stillpilot.smooth-scroll

~/.config/omarchy/plugins/stillpilot.smooth-scroll/uninstall.sh
omarchy plugin remove stillpilot.smooth-scroll
```

## 配置

配置文件：`~/.config/omarchy/smooth-scroll.json`。面板里拖动滑条会立刻写回，守护进程自动重载。

菜单：**Setup → Smooth Scroll**。

## 故障

- **看不到图标**：`omarchy restart shell`，并确认 `~/.config/omarchy/shell.json` 的 `bar.layout.right` 里有 `stillpilot.smooth-scroll`。
- **鼠标卡住**：`systemctl --user stop stillpilot-smooth-scroll`，再跑 `install.sh`。
- **没有平滑效果**：`systemctl --user status stillpilot-smooth-scroll`，`daemon.py list` 应列出你的鼠标。
