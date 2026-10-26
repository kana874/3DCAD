# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD Web's reversible Fusion-style input preset.

Executed *inside* the already-booted FreeCAD Python runtime by fusion-mode.js.
The default uses the built-in Gui::RevitNavigationStyle:
middle-drag pan, Shift+middle-drag orbit, wheel zoom.
No DOM pointer-event interception (which can break Qt/WebAssembly).
"""
import sys

_MODE = "__FUSION_MODE__"  # replaced by trusted JS with "on" or "off" only
VIEW_PATH = "User parameter:BaseApp/Preferences/View"
BACKUP_PATH = "User parameter:BaseApp/Preferences/Mod/FusionWeb/Backup"
SHORTCUT_PATH = "User parameter:BaseApp/Preferences/Shortcut"
STYLE = "Gui::RevitNavigationStyle"
SHORTCUTS = {
    "L": "Sketcher_CreateLine",
    "R": "Sketcher_CreateRectangle",
    "C": "Sketcher_CreateCircle",
    "D": "Sketcher_Dimension",
    "X": "Sketcher_ToggleConstruction",
    "T": "Sketcher_Trimming",
    "O": "Sketcher_Offset",
    "P": "Sketcher_Projection",
    "E": "PartDesign_Pad",
    "H": "PartDesign_Hole",
    "F": "PartDesign_Fillet",
    "M": "Std_TransformManip",
    "I": "Std_Measure",
}
MARK = "/tmp/freecad-fusion-mode-status.txt"


def _all_views(app, gui):
    for name in app.listDocuments():
        doc = gui.getDocument(name)
        if doc is None:
            continue
        for view in doc.mdiViewsOfType("Gui::View3DInventor"):
            yield view


def _cmd(gui, name):
    try:
        return gui.Command.get(name)
    except Exception:
        return None


def _capture_command(app, gui, backup, name):
    flag = "captured." + name
    if backup.GetBool(flag, False):
        return
    custom = app.ParamGet(SHORTCUT_PATH)
    has_custom = name in custom.GetStrings()
    backup.SetBool("custom." + name, has_custom)
    if has_custom:
        backup.SetString("key." + name, custom.GetString(name))
    backup.SetBool(flag, True)


def _restore_command(backup, gui, name):
    if not backup.GetBool("captured." + name, False):
        return
    cmd = _cmd(gui, name)
    if cmd is None:
        return
    if backup.GetBool("custom." + name, False):
        cmd.setShortcut(backup.GetString("key." + name))
    else:
        cmd.resetShortcut()


def apply(app, gui):
    view = app.ParamGet(VIEW_PATH)
    backup = app.ParamGet(BACKUP_PATH)
    if not backup.GetBool("Captured", False):
        backup.SetString("NavigationStyle", view.GetString("NavigationStyle", "Gui::CADNavigationStyle"))
        backup.SetBool("ZoomAtCursor", view.GetBool("ZoomAtCursor", False))
        backup.SetBool("Captured", True)

    view.SetString("NavigationStyle", STYLE)
    view.SetBool("ZoomAtCursor", True)
    for v in _all_views(app, gui):
        try:
            v.setNavigationType(STYLE)
        except Exception:
            pass

    # Workbench imports register commands before shortcut collision removal.
    for mod in ("SketcherGui", "PartDesignGui", "PartGui"):
        try:
            __import__(mod)
        except Exception:
            pass

    count = 0
    skipped = []
    for key, target in SHORTCUTS.items():
        command = _cmd(gui, target)
        if command is None:
            skipped.append(key + ": " + target + " unavailable")
            continue
        _capture_command(app, gui, backup, target)
        try:
            conflicts = list(gui.Command.listByShortcut(key))
        except Exception:
            conflicts = []
        for other in conflicts:
            if other == target:
                continue
            displaced = _cmd(gui, other)
            if displaced is None:
                continue
            _capture_command(app, gui, backup, other)
            try:
                displaced.setShortcut("")
            except Exception:
                skipped.append("collision: " + other)
        try:
            command.setShortcut(key)
            count += 1
        except Exception as error:
            skipped.append(key + ": " + str(error))
    return "ok:on;navigation=Revit;shortcuts=" + str(count) + ";skipped=" + repr(skipped)


def restore(app, gui):
    backup = app.ParamGet(BACKUP_PATH)
    if not backup.GetBool("Captured", False):
        return "ok:off;no previous Fusion preset"
    view = app.ParamGet(VIEW_PATH)
    previous = backup.GetString("NavigationStyle", "Gui::CADNavigationStyle")
    view.SetString("NavigationStyle", previous)
    view.SetBool("ZoomAtCursor", backup.GetBool("ZoomAtCursor", False))
    for v in _all_views(app, gui):
        try:
            v.setNavigationType(previous)
        except Exception:
            pass
    # Restore targets and displaced shortcuts, including command defaults.
    for item in list(backup.GetBools()):
        if item.startswith("captured.") and backup.GetBool(item, False):
            try:
                _restore_command(backup, gui, item[len("captured."):])
            except Exception:
                pass
    # Do not keep an old backup after a full restore; the next opt-in captures
    # the current user state again.
    try:
        app.ParamGet("User parameter:BaseApp/Preferences/Mod/FusionWeb").RemGroup("Backup")
    except Exception:
        pass
    return "ok:off;navigation=" + previous


try:
    import FreeCAD as _fusion_app
    import FreeCADGui as _fusion_gui
    if _MODE == "on":
        _fusion_status = apply(_fusion_app, _fusion_gui)
    elif _MODE == "off":
        _fusion_status = restore(_fusion_app, _fusion_gui)
    else:
        raise ValueError("Invalid Fusion mode")
except Exception as _fusion_exception:
    _fusion_status = "error:" + repr(_fusion_exception)
    sys.stderr.write("[fusion-mode] " + _fusion_status + "\n")
try:
    with open(MARK, "w", encoding="utf-8") as _fusion_status_file:
        _fusion_status_file.write(_fusion_status)
except Exception:
    pass
