# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in Qt-native modeling workspace for FreeCAD Web.

Install once after the application and translations are ready. Widgets, native
selection and shortcuts share Qt's own event loop; no DOM pointer injection.
"""
import json
import time
from functools import partial
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets
from cad_core import (CadError, ExtrusionSession, add_circle, add_rectangle,
                      body_of, create_sketch, length, selected_sketch,
                      sketch_in_edit, transaction, valid_shape)

VERSION = '0.2.3'
WORKSPACE = None


class Observer:
    def __init__(self, workspace):
        self.workspace = workspace

    def changed(self, *args):
        self.workspace.dirty = True

    addSelection = changed
    removeSelection = changed
    clearSelection = changed
    setSelection = changed
    def slotCreatedDocument(self, *args):
        self.changed(*args)
        try:
            self.workspace.file_tokens.pop(args[0].Name, None)
        except Exception:
            self.workspace.file_tokens.clear()
        # Set immediately: a user can close the page before the next Qt tick.
        try:
            with open('/tmp/cad-open-documents', 'w') as marker:
                marker.write('1')
        except OSError:
            pass
    def slotDeletedDocument(self, *args):
        self.changed(*args)
        try:
            self.workspace.file_tokens.pop(args[0].Name, None)
        except Exception:
            self.workspace.file_tokens.clear()
    slotActivateDocument = changed
    slotCreatedObject = changed
    slotDeletedObject = changed
    slotChangedObject = changed
    slotRecomputedDocument = changed
    slotUndoDocument = changed
    slotRedoDocument = changed


class Workspace(QtCore.QObject):
    def __init__(self):
        from cad_profiles import restore_proxies
        restore_proxies()
        self.main = Gui.getMainWindow()
        super().__init__(self.main)
        self.dirty = True
        self.file_tokens = {}
        self.file_token_epoch = str(time.time_ns())
        self.file_token_counter = 0
        self.native_task_pending = False
        self.native_task_widget = None
        self.native_task_dock = None
        self.native_actions = {}
        self.region_picker = None
        self.plane_picker = None
        self.reference_scene = None
        self.reference_root = None
        self.grid_visible = True
        self.theme_signature = None
        self.session = None
        self.fields = {}
        self.actions = {}
        self.key_actions = {}
        self.shortcuts = []
        self.saved_shortcuts = {}
        self.saved_visibility = []
        self.signature = None
        self.last_history_click = None
        self.history_event_time = None
        self.history_signature = None
        self.tree_signature = None
        self.tree_items = {}
        self.editing = False
        self.current_command = None
        self.syncing = False
        self.last_sketch = None
        self.preview_ok = False
        self.native_task_sketch = False
        self.native_task_active = False
        self.native_widgets = list(self.main.findChildren(QtWidgets.QDockWidget)) + list(self.main.findChildren(QtWidgets.QToolBar))
        self.saved_visibility = [(w, w.isVisible()) for w in self.native_widgets]
        self.menu_visible = self.main.menuBar().isVisible()
        self.overlay_state = []
        for side in ('Left', 'Right', 'Top', 'Bottom'):
            params = App.ParamGet('User parameter:BaseApp/MainWindow/DockWindows/Overlay' + side)
            present = 'Widgets' in params.GetStrings()
            self.overlay_state.append((params, present, params.GetString('Widgets', '')))
            params.SetString('Widgets', '')
        self.main.menuBar().hide()
        QtWidgets.QApplication.instance().installEventFilter(self)
        preferences = App.ParamGet('User parameter:BaseApp/Preferences/View')
        self.previous_navigation = preferences.GetString('NavigationStyle', 'Gui::CADNavigationStyle')
        self.previous_zoom = preferences.GetBool('ZoomAtCursor', False)
        preferences.SetString('NavigationStyle', 'Gui::RevitNavigationStyle')
        preferences.SetBool('ZoomAtCursor', True)
        for widget, _ in self.saved_visibility:
            widget.hide()
        self.build_toolbar()
        self.build_tree()
        self.build_panel()
        self.build_history()
        self.build_view_menu()
        self.build_command_menus()
        from cad_catalog import CommandCatalog
        self.catalog = CommandCatalog(self)
        self.observer = Observer(self)
        Gui.Selection.addObserver(self.observer)
        App.addDocumentObserver(self.observer)
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(180)
        self.preview_timer.timeout.connect(self.update_preview)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.sync()
        self.home()
        self.status('専用ワークスペースを起動しました。スケッチから始めてください。')
        self.restore_panel_preferences()

    def status(self, text, error=False):
        self.message.setText(text)
        dark = self.main.palette().color(QtGui.QPalette.Window).lightness() < 128
        self.message.setStyleSheet('color:' + (('#ff9696' if dark else '#c73737') if error else ('#9ad4ff' if dark else '#27658b')))
        self.main.statusBar().showMessage(text, 12000)

    def safe(self, function, *args):
        try:
            return function(*args)
        except Exception as error:
            self.status(str(error), True)
            App.Console.PrintError('[cad-workspace] ' + repr(error) + '\n')
            return None
        finally:
            self.dirty = True

    def route(self, name, *_):
        if self.native_task_active and not self.native_task_sketch and name not in ('cancel', 'layout_reset', 'show_browser', 'show_design', 'show_history'):
            self.status('現在の操作を確定またはキャンセルしてください。', True)
            return
        if self.session and name not in ('cancel',):
            self.status('押し出しを確定するか、キャンセルしてください。', True)
            return
        return self.safe(self.dispatch, name)

    def dispatch(self, name):
        if name == 'new':
            if Gui.activeDocument() and Gui.activeDocument().getInEdit():
                raise CadError('現在の編集を終了してください。')
            App.newDocument()
            self.home()
        elif name == 'sketch':
            self.sketch_panel()
        elif name == 'finish':
            self.finish_sketch()
        elif name == 'extrude':
            self.extrude_panel()
        elif name in ('rectangle_exact', 'rectangle_center_exact', 'circle_exact'):
            self.geometry_panel(name)
        elif name in ('rectangle_three_points', 'circle_two_points'):
            self.point_geometry_panel(name)
        elif name == 'sketch_settings':
            self.sketch_settings_panel()
        elif name == 'measure':
            self.measure_panel()
        elif name == 'preferences':
            Gui.runCommand('Std_DlgPreferences')
        elif name == 'search':
            self.search_panel()
        elif name in ('save', 'save_as'):
            self.request_file_operation(name)
        elif name == 'open':
            self.request_file_operation('open')
        elif name == 'export':
            self.export_panel()
        elif name == 'grid':
            sketch = sketch_in_edit(Gui)
            if sketch and hasattr(sketch.ViewObject, 'ShowGrid'):
                sketch.ViewObject.ShowGrid = not sketch.ViewObject.ShowGrid
            else:
                self.grid_visible = not self.grid_visible
                self.update_references()
        elif name in self.catalog.workbenches:
            if Gui.activeDocument() and Gui.activeDocument().getInEdit():
                raise CadError('現在の編集を終了してから機能を切り替えてください。')
            self.close_plane_picker()
            self.catalog.activate(name)
        elif name == 'new_3d_view':
            Gui.runCommand('Std_ViewCreate')
        elif name in self.native_actions:
            self.close_plane_picker()
            command, sketch_only = self.native_actions[name]
            if sketch_only and not sketch_in_edit(Gui):
                raise CadError('スケッチを作成・編集してから実行してください。')
            # A normal Body command completes immediately. Its native Start
            # Part page is navigation, not a pending edit to embed/lock on.
            # A selected sketch is different: FreeCAD opens a plane picker
            # for rebasing it, which still needs the native task controls.
            if command == 'PartDesign_Body' and not any(
                    obj.TypeId == 'Sketcher::SketchObject' for obj in Gui.Selection.getSelection()):
                Gui.runCommand(command)
                self.home()
                return
            self.show_native_tasks(sketch=sketch_only)
            Gui.runCommand(command)
        elif name == 'cancel':
            self.cancel()
        elif name in ('undo', 'redo'):
            doc = App.ActiveDocument
            if doc:
                getattr(doc, name)()
                self.home()
        elif name == 'fit':
            self.fit_view()
        elif name == 'layout_reset':
            self.restore_layout()
        elif name.startswith('show_'):
            getattr(self, {'show_browser': 'tree_dock', 'show_design': 'panel_dock', 'show_history': 'history_dock'}[name]).show()
        else:
            commands = {'line': 'Sketcher_CreatePolyline', 'rectangle': 'Sketcher_CreateRectangle',
                        'circle': 'Sketcher_CreateCircle', 'dimension': 'Sketcher_Dimension',
                        'trim': 'Sketcher_Trimming', 'construction': 'Sketcher_ToggleConstruction',
                        'fillet': 'PartDesign_Fillet', 'chamfer': 'PartDesign_Chamfer',
                        'save': 'Std_Save', 'open': 'Std_Open', 'export': 'Std_Export',
                        'measure': 'Std_Measure'}
            if name not in commands:
                raise CadError('未対応の操作です。')
            if name in ('line', 'rectangle', 'circle', 'dimension', 'trim', 'construction') and not sketch_in_edit(Gui):
                raise CadError('スケッチを作成・編集してから実行してください。')
            if name in ('fillet', 'chamfer', 'measure'):
                self.show_native_tasks()
            elif name in ('line', 'rectangle', 'circle', 'dimension', 'trim', 'construction'):
                self.show_native_tasks(sketch=True)
            Gui.runCommand(commands[name])

    def action(self, name, title, key=None):
        action = QtGui.QAction(title, self.main)
        action.setObjectName('CAD_Action_' + name)
        action.triggered.connect(partial(self.route, name))
        if key:
            # Clear native command collisions; restore exactly on workspace exit.
            for native in self.main.findChildren(QtGui.QAction):
                if native != action and native.shortcut().toString() == key:
                    self.shortcuts.append((native, native.shortcut()))
                    native.setShortcut(QtGui.QKeySequence())
            self.key_actions[key.upper()] = name
            action.setToolTip(title + ' — ' + key)
        self.main.addAction(action)
        self.actions[name] = action
        return action

    def build_toolbar(self):
        bar = QtWidgets.QToolBar('デザイン', self.main)
        bar.setObjectName('CAD_Toolbar')
        bar.setMovable(False)
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        bar.setStyleSheet('QToolBar {background:palette(window);color:palette(window-text);spacing:5px;padding:6px;} QToolButton {padding:7px;color:palette(button-text);} QToolButton:disabled {color:palette(mid);}')
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, bar)
        groups = [
            [('new', '新規', None), ('open', '開く', None), ('save', '保存', None), ('export', '書出し', None)],
            [('sketch', 'スケッチを作成', None), ('finish', 'スケッチ終了', None)],
            [('line', '線 L', 'L'), ('rectangle', '長方形 R', 'R'), ('circle', '円 C', 'C'),
             ('dimension', '寸法 D', 'D'), ('trim', 'トリム T', 'T'), ('construction', '補助線 X', 'X')],
            [('extrude', '押し出し E', 'E'), ('fillet', 'フィレット F', 'F'), ('chamfer', '面取り', None)],
            [('search', '検索 S', 'S'), ('grid', '原点・グリッド', None), ('fit', '全体表示', None)]
        ]
        for group in groups:
            if bar.actions():
                bar.addSeparator()
            for name, title, key in group:
                bar.addAction(self.action(name, title, key))
        # Keep normal Save available on the main button; its small menu offers
        # an explicit new destination without adding another wide toolbar item.
        save_button = bar.widgetForAction(self.actions['save'])
        save_menu = QtWidgets.QMenu(save_button)
        save_menu.addAction(self.action('save_as', '名前を付けて保存'))
        save_button.setMenu(save_menu)
        save_button.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.action('cancel', 'キャンセル', 'Esc')
        self.bar = bar

    def build_command_menus(self):
        from cad_commands import SKETCH_TOOLS
        available = set(Gui.listCommands())
        def adapter(menu, title, command, sketch_only):
            if command not in available:
                return
            name = 'native_' + command
            if name not in self.actions:
                self.native_actions[name] = (command, sketch_only)
                self.action(name, title)
            menu.addAction(self.actions[name])
        def add_menu(title, menu):
            button = QtWidgets.QToolButton(self.bar)
            button.setText(title)
            button.setMenu(menu)
            button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            self.bar.addWidget(button)
        sketch = QtWidgets.QMenu('作図', self.bar)
        for title, commands in SKETCH_TOOLS:
            submenu = sketch.addMenu(title)
            for label, command in commands:
                adapter(submenu, label, command, True)
        sketch.addSeparator()
        sketch.addAction(self.action('rectangle_three_points', '3点矩形（座標指定）'))
        sketch.addAction(self.action('circle_two_points', '2点円（直径の両端を座標指定）'))
        sketch.addAction(self.action('sketch_settings', 'スケッチ表示・スナップ設定'))
        sketch.addAction(self.action('rectangle_center_exact', '中心・幅・高さを数値指定'))
        add_menu('作図', sketch)
        for title, prefix in [('修正・拘束', 'Sketcher_'), ('ソリッド', 'PartDesign_'), ('形状・検査', 'Part_')]:
            menu = QtWidgets.QMenu(title, self.bar)
            for command in sorted(available):
                if not command.startswith(prefix) or command.startswith(prefix + 'Comp') or (prefix == 'Sketcher_' and command.startswith('Sketcher_Create')):
                    continue
                try:
                    label = Gui.Command.get(command).getInfo().get('menuText', command).replace('&', '')
                    label = QtCore.QCoreApplication.translate(command, label)
                except Exception:
                    label = command
                adapter(menu, label, command, prefix == 'Sketcher_')
            add_menu(title, menu)

    def measure_panel(self):
        self.clear_panel('測定')
        import Part
        shapes = []
        for selection in Gui.Selection.getSelectionEx():
            for shape in selection.SubObjects or [getattr(selection.Object, 'Shape', Part.Shape())]:
                if not shape.isNull():
                    shapes.append(shape)
        if not shapes:
            self.form.addRow(QtWidgets.QLabel('形状・面・エッジ・頂点を選択して、もう一度測定してください。'))
        for i, shape in enumerate(shapes):
            label = QtWidgets.QLabel('形状 %d\n長さ %.6g mm\n面積 %.6g mm²\n体積 %.6g mm³' % (i + 1, shape.Length, shape.Area, shape.Volume))
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.form.addRow(label)
        if len(shapes) == 2:
            self.form.addRow('最短距離', QtWidgets.QLabel('%.6g mm' % shapes[0].distToShape(shapes[1])[0]))
        self.button('選択を測定し直す', self.measure_panel, 'measure_refresh')
        self.button('閉じる', self.home, 'measure_close')

    def sketch_settings_panel(self):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中に設定してください。')
        self.clear_panel('スケッチ設定')
        params = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher/Tools')
        ovp = self.combo('on_view_parameters', 'カーソル付近の数値入力', [('非表示', 0), ('寸法', 1), ('位置と寸法', 2)])
        ovp.setCurrentIndex(max(0, min(2, params.GetInt('OnViewParameterVisibility', 1))))
        ovp.currentIndexChanged.connect(lambda index: params.SetInt('OnViewParameterVisibility', index))
        self.form.addRow(QtWidgets.QLabel('次に開始する作図ツールから反映されます。Tabで入力項目を切り替えます。'))
        titles = {'ShowGrid': 'グリッド表示', 'GridSnap': 'グリッドにスナップ', 'GridAuto': 'グリッド間隔を自動調整', 'ShowConstraints': '拘束を表示', 'ShowAxes': '軸を表示', 'ShowPoints': '点を表示'}
        for name in sketch.ViewObject.PropertiesList:
            if (name.startswith('Show') or name in titles) and isinstance(getattr(sketch.ViewObject, name), bool):
                box = QtWidgets.QCheckBox(titles.get(name, name))
                box.setChecked(getattr(sketch.ViewObject, name))
                box.toggled.connect(lambda value, prop=name: setattr(sketch.ViewObject, prop, value))
                self.form.addRow(box)
        self.button('戻る', self.sketch_home, 'settings_back')

    def build_view_menu(self):
        menu = QtWidgets.QMenu('表示', self.bar)
        for dock in (self.tree_dock, self.panel_dock, self.history_dock):
            menu.addAction(dock.toggleViewAction())
        menu.addSeparator()
        menu.addAction(self.action('layout_reset', 'レイアウトを初期化'))
        menu.addAction(self.action('preferences', '設定'))
        menu.addAction(self.action('measure', '選択形状を測定'))
        for name, title in [('show_browser', 'ブラウザを表示'), ('show_design', 'デザインを表示'), ('show_history', '履歴を表示')]:
            self.action(name, title)
        button = QtWidgets.QToolButton(self.bar)
        button.setText('表示')
        button.setObjectName('CAD_ViewMenu')
        button.setMenu(menu)
        button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.bar.addWidget(button)

    def restore_panel_preferences(self):
        params = App.ParamGet('User parameter:BaseApp/Preferences/CADWorkspace')
        for dock in (self.tree_dock, self.panel_dock, self.history_dock):
            dock.setVisible(params.GetBool(dock.objectName() + 'Visible', True))
            dock.visibilityChanged.connect(lambda visible, name=dock.objectName(): params.SetBool(name + 'Visible', visible))
        widths = [max(185, min(500, params.GetInt('BrowserWidth', 240))),
                  max(245, min(600, params.GetInt('DesignWidth', 320)))]
        self.main.resizeDocks([self.tree_dock, self.panel_dock], widths, QtCore.Qt.Horizontal)

    def restore_layout(self):
        for dock in (self.tree_dock, self.panel_dock, self.history_dock):
            dock.show()
        self.main.resizeDocks([self.tree_dock, self.panel_dock], [240, 320], QtCore.Qt.Horizontal)
        params = App.ParamGet('User parameter:BaseApp/Preferences/CADWorkspace')
        params.SetInt('BrowserWidth', 240)
        params.SetInt('DesignWidth', 320)

    def close_plane_picker(self):
        if self.plane_picker:
            self.plane_picker.close()
            self.plane_picker = None

    def dock(self, name, title, area):
        dock = QtWidgets.QDockWidget(title, self.main)
        dock.setObjectName('CAD_' + name)
        dock.setAllowedAreas(area)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetClosable)
        self.main.addDockWidget(area, dock)
        return dock

    def build_tree(self):
        self.tree_dock = self.dock('Browser', 'ブラウザ', QtCore.Qt.LeftDockWidgetArea)
        host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(host)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(185)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        # Only a user's tree click may replace native subelement selection.
        # Selection-model notifications during a rebuild otherwise collapse
        # Face/Edge picks into whole-object picks on Qt/WASM.
        self.tree.itemClicked.connect(lambda *_: self.tree_selection())
        self.tree.itemDoubleClicked.connect(lambda item, col: self.safe(self.edit_item, item))
        self.tree.itemChanged.connect(self.tree_changed)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        tools = QtWidgets.QHBoxLayout()
        for title, function in [('展開', self.tree.expandAll), ('格納', self.tree.collapseAll)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(function)
            tools.addWidget(button)
        layout.addLayout(tools)
        layout.addWidget(self.tree)
        self.tree_dock.setWidget(host)

    def build_panel(self):
        self.panel_dock = self.dock('Command', 'デザイン', QtCore.Qt.RightDockWidgetArea)
        host = QtWidgets.QWidget()
        host.setMinimumWidth(245)
        layout = QtWidgets.QVBoxLayout(host)
        self.heading = QtWidgets.QLabel('デザイン')
        self.heading.setStyleSheet('font-size:16px;font-weight:600;padding:8px 0')
        self.body = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.body)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.heading)
        layout.addWidget(self.body)
        layout.addStretch()
        layout.addWidget(self.message)
        self.panel_dock.setWidget(host)

    def build_history(self):
        self.history_dock = self.dock('History', 'デザイン履歴 — ダブルクリックで編集', QtCore.Qt.BottomDockWidgetArea)
        self.history = QtWidgets.QListWidget()
        self.history.setFlow(QtWidgets.QListView.LeftToRight)
        self.history.setWrapping(False)
        self.history.setMaximumHeight(70)
        self.history.itemActivated.connect(lambda item: self.safe(self.edit_item, item))
        self.history.itemClicked.connect(self.history_click)
        self.history_dock.setWidget(self.history)

    def clear_panel(self, title):
        self.release_native_tasks()
        self.heading.setText(title)
        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.fields = {}
        self.panel_dock.show()

    def field(self, name, title, default):
        widget = QtWidgets.QLineEdit(str(default))
        widget.setObjectName('CAD_Input_' + name)
        self.fields[name] = widget
        self.form.addRow(title, widget)
        return widget

    def combo(self, name, title, options):
        widget = QtWidgets.QComboBox()
        widget.setObjectName('CAD_Input_' + name)
        for label, data in options:
            widget.addItem(label, data)
        self.fields[name] = widget
        self.form.addRow(title, widget)
        return widget

    def button(self, title, function, name=''):
        button = QtWidgets.QPushButton(title)
        button.setObjectName('CAD_Button_' + name)
        button.clicked.connect(lambda *_: self.safe(function))
        self.form.addRow(button)
        return button

    def value(self, name, positive=True):
        return length(App, self.fields[name].text(), positive)

    def request_file_operation(self, operation, scope='visible'):
        doc = App.ActiveDocument
        if operation not in ('open', 'recover') and doc is None:
            raise CadError('保存する設計がありません。')
        selected = [o.Name for o in Gui.Selection.getSelection() if o.Document == doc] if doc else []
        if operation == 'step' and scope == 'selected' and not selected:
            raise CadError('書き出すボディを選択してください。')
        request = {'operation': operation, 'document': doc.Name if doc else None,
                   'token': self.file_token(doc) if doc else None,
                   'label': doc.Label if doc else '', 'scope': scope, 'selected': selected}
        with open('/tmp/cad-file-request.json', 'w', encoding='utf-8') as out:
            json.dump(request, out, ensure_ascii=False)
        self.status('ブラウザのファイル操作を続けてください。')

    def file_token(self, doc):
        if doc.Name not in self.file_tokens:
            self.file_token_counter += 1
            self.file_tokens[doc.Name] = self.file_token_epoch + '-' + str(self.file_token_counter)
        return self.file_tokens[doc.Name]

    def export_panel(self):
        self.clear_panel('STEPを書き出し')
        self.combo('export_scope', '対象', [('表示中のボディ', 'visible'),
                   ('選択したボディ', 'selected'), ('すべてのボディ', 'all')])
        self.button('STEPとして保存', lambda: self.request_file_operation(
            'step', self.fields['export_scope'].currentData()), 'export_step')
        self.button('キャンセル', self.home, 'export_cancel')

    def home(self):
        self.close_plane_picker()
        self.current_command = None
        self.native_task_active = False
        self.clear_panel('デザイン')
        label = QtWidgets.QLabel('面または基準面にスケッチを作成し、Eで領域を選んで押し出します。\n作図の種類は上部の「作図」、パネルの復元は「表示」です。')
        label.setWordWrap(True)
        label.setMinimumHeight(64)
        self.form.addRow(label)
        self.button('スケッチを作成', self.sketch_panel, 'create_sketch')
        self.button('ブラウザを表示', self.tree_dock.show, 'show_browser')
        self.button('履歴を表示', self.history_dock.show, 'show_history')
        # Existing browser recovery copies remain available for explicit local
        # retrieval, but are never opened or deleted automatically.
        try:
            import os
            extensions = ('.fcstd', '.step', '.stp', '.iges', '.igs', '.brep', '.brp',
                          '.stl', '.obj', '.ply', '.3mf', '.ifc', '.dxf')
            roots = ('/home/web_user/.fcweb-autosave', '/home/web_user/_up', '/home/web_user/_dl')
            found = any(name.lower().endswith(extensions) for name in os.listdir('/home/web_user'))
            for old in roots:
                if found:
                    break
                for _, _, files in os.walk(old):
                    if any(name.lower().endswith(extensions) for name in files):
                        found = True
                        break
            if found:
                self.button('以前のブラウザ保存データを取り出す',
                            lambda: self.request_file_operation('recover'), 'legacy_files')
        except OSError:
            pass
        self.editing = False

    def face_selection(self):
        selected = Gui.Selection.getSelectionEx()
        if len(selected) == 1:
            names = selected[0].SubElementNames
            if len(names) == 1 and names[0].startswith('Face'):
                return selected[0].Object, names[0]
        return None

    def sketch_panel(self):
        face = self.face_selection()
        if face:
            self.start_sketch(face=face)
            return
        picked = Gui.Selection.getSelection()
        if len(picked) == 1:
            body = body_of(picked[0])
            if body:
                Gui.activeDocument().activeView().setActiveObject('pdbody', body)
        self.close_plane_picker()
        if App.ActiveDocument is None:
            App.newDocument()
        from cad_selection import PlanePicker
        self.plane_picker = PlanePicker(lambda plane: self.safe(self.start_sketch, plane))
        self.current_command = 'plane_select'
        self.clear_panel('平面をクリックして選択')
        self.combo('plane', '基準平面', [('XY（上面）', 'XY'), ('YZ（右側面）', 'YZ'), ('XZ（正面）', 'XZ')])
        self.button('この平面で開始', lambda: self.start_sketch(self.fields['plane'].currentData()), 'start_sketch')
        self.button('キャンセル', self.cancel, 'cancel_plane')
        self.button('選択した面で開始', lambda: self.start_sketch(face=self.face_selection(), require_face=True), 'start_face')

    def start_sketch(self, plane='XY', face=None, require_face=False):
        if require_face and not face:
            raise CadError('3Dビューで平面の面を一つ選択してください。')
        self.close_plane_picker()
        sketch = create_sketch(App, Gui, plane, face)
        self.sketch_home(sketch)
        self.dirty = True

    def sketch_home(self, sketch=None):
        # The WASM compositor also repairs hidden edit providers on its 1.5s
        # timer. Complete that repair before accepting drawing input, otherwise
        # its delayed ViewFit can change the camera between consecutive picks.
        if sketch is not None and not sketch.ViewObject.Visibility:
            sketch.ViewObject.Visibility = True
            Gui.SendMsgToActiveView('ViewFit')
        self.current_command = None
        self.clear_panel('スケッチ')
        self.button('幅・高さを指定して長方形', lambda: self.geometry_panel('rectangle_exact'), 'rectangle_exact')
        self.button('中心・幅・高さを指定して長方形', lambda: self.geometry_panel('rectangle_center_exact'), 'rectangle_center_exact')
        self.button('直径を指定して円', lambda: self.geometry_panel('circle_exact'), 'circle_exact')
        self.button('寸法を追加 D', lambda: self.route('dimension'), 'dimension')
        self.button('押し出しへ E', self.extrude_panel, 'extrude')
        self.button('スケッチを終了', self.finish_sketch, 'finish')

    def finish_sketch(self):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中ではありません。')
        self.release_native_tasks()
        Gui.activeDocument().resetEdit()
        sketch.Document.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sketch)
        self.last_sketch = sketch
        self.home()

    def point_geometry_panel(self, mode):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中に作図してください。')
        self.clear_panel('3点矩形' if mode == 'rectangle_three_points' else '2点円')
        count = 3 if mode == 'rectangle_three_points' else 2
        defaults = [(0, 0), (40, 20), (30, 40)]
        for i in range(count):
            for axis, value in zip(('x', 'y'), defaults[i]):
                self.field(axis + str(i), '点%d %s' % (i + 1, axis.upper()), str(value) + ' mm')
        def create():
            from cad_core import add_three_point_rectangle, add_two_point_circle
            values = [self.value(axis + str(i), False) for i in range(count) for axis in ('x', 'y')]
            function = add_three_point_rectangle if count == 3 else add_two_point_circle
            function(App, sketch, *values)
            self.fit_view()
            self.sketch_home(sketch)
        self.button('作成', create, 'add_point_geometry')
        self.button('戻る', self.sketch_home, 'back')

    def geometry_panel(self, mode):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中に実行してください。')
        self.current_command = mode
        self.clear_panel('寸法付き長方形' if mode in ('rectangle_exact', 'rectangle_center_exact') else '直径指定の円')
        self.field('x', 'X位置', '0 mm')
        self.field('y', 'Y位置', '0 mm')
        if mode in ('rectangle_exact', 'rectangle_center_exact'):
            self.field('width', '幅', '50 mm')
            self.field('height', '高さ', '30 mm')
        else:
            self.field('diameter', '直径', '10 mm')
        def create():
            x, y = self.value('x', False), self.value('y', False)
            if mode in ('rectangle_exact', 'rectangle_center_exact'):
                add_rectangle(App, sketch, self.value('width'), self.value('height'), x, y, center=mode == 'rectangle_center_exact')
            else:
                add_circle(App, sketch, self.value('diameter'), x, y)
            self.fit_view()
            self.sketch_home(sketch)
            self.status('寸法拘束付きの図形を作成しました。位置は必要に応じて拘束してください。')
        self.button('作成', create, 'add_geometry')
        self.button('戻る', self.sketch_home, 'back')

    def extrude_panel(self):
        sketch = selected_sketch(App, Gui)
        if sketch_in_edit(Gui):
            self.finish_sketch()
        elif Gui.activeDocument().getInEdit():
            raise CadError('現在の編集を終了してください。')
        self.session = ExtrusionSession(App, Gui, sketch)
        self.current_command = 'extrude'
        self.clear_panel('押し出し')
        label = QtWidgets.QLabel(sketch.Label + '：塗られた領域をクリックして選択')
        label.setWordWrap(True)
        self.form.addRow('プロファイル', label)
        self.region_list = QtWidgets.QListWidget()
        self.region_list.setObjectName('CAD_Regions')
        self.region_list.setMaximumHeight(140)
        self.form.addRow('領域', self.region_list)
        self.boundary_toggle = QtWidgets.QCheckBox('ボディ断面を境界に含める')
        self.boundary_toggle.setChecked(self.session.previous is not None)
        self.form.addRow(self.boundary_toggle)
        self.field('distance', '距離', '10 mm')
        options = [('結合', 'join'), ('切り取り', 'cut'), ('新規ボディ', 'new')]
        if self.session.previous is None:
            options = [('新規ボディ内の最初の形状', 'new')]
        self.combo('operation', '操作', options)
        self.combo('direction', '方向', [('片側', 'one'), ('反転', 'reverse'), ('対称（全長）', 'symmetric')])
        self.combo('extent', '範囲', [('距離', 'distance'), ('貫通（切り取り）', 'through')])
        self.preview_button = self.button('プレビュー', self.update_preview, 'preview')
        self.accept_button = self.button('OK', self.accept_extrusion, 'accept')
        self.accept_button.setEnabled(False)
        self.button('キャンセル Esc', self.cancel, 'cancel')
        for widget in self.fields.values():
            signal = widget.textChanged if isinstance(widget, QtWidgets.QLineEdit) else widget.currentIndexChanged
            signal.connect(self.schedule_preview)
        self.region_list.itemChanged.connect(self.regions_changed)
        self.boundary_toggle.toggled.connect(lambda *_: self.safe(self.load_regions))
        self.load_regions()

    def load_regions(self):
        from cad_profiles import regions
        from cad_selection import RegionPicker
        if self.region_picker:
            self.region_picker.close()
            self.region_picker = None
        old_keys = list(self.session.region_keys or [])
        self.preview_timer.stop()
        self.preview_ok = False
        self.accept_button.setEnabled(False)
        self.session.region_keys = []
        self.session.region_candidates = []
        if self.session.preview:
            self.session.preview.ViewObject.Visibility = False
        self.session.boundaries = [self.session.previous] if self.boundary_toggle.isChecked() and self.session.previous else []
        candidates = regions(self.session.sketch, self.session.boundaries)
        self.session.region_candidates = candidates
        self.session.region_keys = []
        self.region_list.blockSignals(True)
        self.region_list.clear()
        for i, (key, face) in enumerate(candidates):
            item = QtWidgets.QListWidgetItem("領域 %d：%.3f mm²" % (i + 1, face.Area))
            item.setData(QtCore.Qt.UserRole, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.region_list.addItem(item)
        self.region_list.blockSignals(False)
        self.region_picker = RegionPicker(self.session.sketch, candidates, self.toggle_region)
        # Preserve the usual single closed-sketch workflow; other cells stay explicit.
        selected = []
        try:
            import Part
            wires = self.session.sketch.Shape.Wires
            if wires and all(w.isClosed() for w in wires):
                original = Part.makeFace(wires, "Part::FaceMakerBullseye")
                original.transformShape(self.session.sketch.Placement.inverse().toMatrix(), True)
                selected = [key for key, face in candidates if abs(face.common(original).Area - face.Area) < 1e-5]
        except Exception:
            pass
        if getattr(self.session, 'editing_profile', False):
            selected = [key for key, _ in candidates if key in old_keys]
        if not selected and len(candidates) == 1 and not getattr(self.session, 'editing_profile', False):
            selected = [candidates[0][0]]
        self.region_list.blockSignals(True)
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            item.setCheckState(QtCore.Qt.Checked if item.data(QtCore.Qt.UserRole) in selected else QtCore.Qt.Unchecked)
        self.region_list.blockSignals(False)
        self.regions_changed()

    def toggle_region(self, key):
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            if item.data(QtCore.Qt.UserRole) == key:
                item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)
                return

    def regions_changed(self, *_):
        if not self.session:
            return
        self.session.region_keys = [self.region_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.region_list.count()) if self.region_list.item(i).checkState() == QtCore.Qt.Checked]
        self.session.use_source_sketch = False
        try:
            import Part
            wires = self.session.sketch.Shape.Wires
            if wires and all(w.isClosed() for w in wires) and self.session.region_keys:
                original = Part.makeFace(wires, 'Part::FaceMakerBullseye')
                original.transformShape(self.session.sketch.Placement.inverse().toMatrix(), True)
                faces = [dict(self.session.region_candidates)[key] for key in self.session.region_keys]
                selected = faces[0].multiFuse(faces[1:]) if len(faces) > 1 else faces[0]
                self.session.use_source_sketch = abs(original.Area - selected.Area) < 1e-6 and abs(original.common(selected).Area - original.Area) < 1e-6
        except Exception:
            pass
        if self.region_picker:
            self.region_picker.highlight(self.session.region_keys)
        if getattr(self.session, 'editing_profile', False):
            self.accept_button.setEnabled(bool(self.session.region_keys))
            return
        self.schedule_preview()

    def close_region_picker(self):
        if self.region_picker:
            self.region_picker.close()
            self.region_picker = None

    def extrusion_values(self):
        direction = self.fields['direction'].currentData()
        return (self.value('distance'), self.fields['operation'].currentData(),
                direction == 'reverse', direction == 'symmetric', self.fields['extent'].currentData() == 'through')

    def schedule_preview(self, *_):
        self.preview_ok = False
        self.accept_button.setEnabled(False)
        self.preview_timer.start()

    def update_preview(self):
        if not self.session:
            return
        try:
            self.session.update(*self.extrusion_values())
            self.preview_ok = True
            self.accept_button.setEnabled(True)
            self.status('プレビューを確認してOKを押してください。Escで元に戻します。')
        except Exception as error:
            self.preview_ok = False
            self.accept_button.setEnabled(False)
            if self.session.preview:
                self.session.preview.ViewObject.Visibility = False
            for name, visible in self.session.visibility.items():
                obj = self.session.doc.getObject(name)
                if obj:
                    obj.ViewObject.Visibility = visible
            self.status(str(error), True)

    def accept_extrusion(self):
        if not self.session:
            return
        self.preview_timer.stop()
        try:
            first_solid = self.session.previous is None
            feature = self.session.accept(*self.extrusion_values())
        except Exception:
            if self.session.closed:
                self.close_region_picker()
                self.session = None
                self.home()
            raise
        self.session = None
        self.close_region_picker()
        Gui.Selection.clearSelection()
        if first_solid:
            QtCore.QTimer.singleShot(300, lambda: self.fit_view() if Gui.activeDocument() else None)
        self.home()
        self.status('押し出しを作成しました。履歴のダブルクリックで距離を変更できます。')

    def cancel(self):
        self.close_region_picker()
        self.close_plane_picker()
        self.preview_timer.stop()
        if self.session:
            self.session.cancel()
            self.session = None
            self.home()
            self.status('押し出しを取り消しました。')
        elif sketch_in_edit(Gui):
            # Let a native drawing tool consume Esc first. The toolbar's
            # explicit Finish command is the only way to close the sketch.
            self.sketch_home()
        else:
            self.home()

    def edit_item(self, item):
        if self.session:
            raise CadError('押し出しを完了してください。')
        name = item.data(0, QtCore.Qt.UserRole) if isinstance(item, QtWidgets.QTreeWidgetItem) else item.data(QtCore.Qt.UserRole)
        doc = App.ActiveDocument
        obj = doc.getObject(name) if doc and name else None
        if not obj:
            return
        if obj.TypeId == 'PartDesign::FeaturePython' and 'RegionKeys' in obj.PropertiesList:
            self.edit_region_panel(obj)
        elif obj.TypeId == 'Sketcher::SketchObject':
            if Gui.activeDocument().getInEdit():
                self.release_native_tasks()
                Gui.activeDocument().resetEdit()
            Gui.activeDocument().setEdit(obj.Name)
            self.sketch_home(obj)
        elif obj.TypeId in ('PartDesign::Pad', 'PartDesign::Pocket'):
            if Gui.activeDocument().getInEdit():
                raise CadError('スケッチ編集を終了してください。')
            self.edit_feature_panel(obj)
        elif obj.TypeId != 'PartDesign::Body':
            self.show_native_tasks()
            Gui.activeDocument().setEdit(obj.Name)

    def edit_region_panel(self, profile):
        from cad_profiles import ProfileEditSession
        if self.session or Gui.activeDocument().getInEdit():
            raise CadError('現在の編集を終了してください。')
        self.session = ProfileEditSession(profile)
        self.current_command = 'region_edit'
        self.clear_panel('押し出し領域を再選択')
        self.region_list = QtWidgets.QListWidget()
        self.region_list.setObjectName('CAD_Regions')
        self.form.addRow(self.region_list)
        self.boundary_toggle = QtWidgets.QCheckBox('ボディ断面を境界に含める')
        self.boundary_toggle.setChecked(bool(self.session.boundaries))
        self.form.addRow(self.boundary_toggle)
        self.accept_button = self.button('適用', self.accept_region_edit, 'apply_regions')
        self.button('キャンセル', self.cancel, 'cancel')
        self.region_list.itemChanged.connect(self.regions_changed)
        self.boundary_toggle.toggled.connect(lambda *_: self.safe(self.load_regions))
        self.load_regions()
        self.dirty = True

    def accept_region_edit(self):
        self.session.accept()
        self.session = None
        self.close_region_picker()
        self.home()
        self.status('押し出す領域を変更し、後続フィーチャを再計算しました。')

    def edit_feature_panel(self, obj):
        self.clear_panel(obj.Label + 'を編集')
        self.field('length', '距離', str(obj.Length))
        if obj.TypeId == 'PartDesign::Pocket':
            extent = self.combo('extent', '範囲', [('距離', 'distance'), ('貫通', 'through')])
            types = obj.getEnumerationsOfProperty('Type')
            extent.setCurrentIndex(1 if str(obj.Type) == types[1] else 0)
        def apply():
            with transaction(obj.Document, '押し出し距離を編集'):
                obj.Length = self.value('length')
                if obj.TypeId == 'PartDesign::Pocket':
                    obj.Type = 1 if self.fields['extent'].currentData() == 'through' else 0
                obj.Document.recompute()
                valid_shape(obj.Shape)
                for child in obj.InListRecursive:
                    if getattr(child, 'State', None) and 'Invalid' in child.State:
                        raise CadError('後続フィーチャの再計算に失敗しました。')
            self.home()
            self.status('距離を変更し、後続フィーチャを再計算しました。')
        self.button('適用', apply, 'apply_length')
        profile = getattr(obj, 'Profile', None)
        if isinstance(profile, (tuple, list)):
            profile = profile[0] if profile else None
        if profile and 'RegionKeys' in profile.PropertiesList:
            self.button('押し出す領域を再選択', lambda target=profile: self.edit_region_panel(target), 'edit_regions')
        self.button('キャンセル', self.home, 'cancel')

    def tree_selection(self):
        if self.syncing or self.session or not self.tree.hasFocus():
            return
        Gui.Selection.clearSelection()
        doc = App.ActiveDocument
        if not doc:
            return
        for item in self.tree.selectedItems():
            name = item.data(0, QtCore.Qt.UserRole)
            obj = doc.getObject(name) if name else None
            if obj:
                Gui.Selection.addSelection(obj)
                if obj.TypeId == 'PartDesign::Body':
                    Gui.activeDocument().activeView().setActiveObject('pdbody', obj)

    def tree_changed(self, item, column):
        if self.syncing or self.session:
            return
        doc = App.ActiveDocument
        name = item.data(0, QtCore.Qt.UserRole)
        obj = doc.getObject(name) if doc and name else None
        if obj:
            obj.ViewObject.Visibility = item.checkState(0) == QtCore.Qt.Checked

    def history_click(self, item):
        # Qt/WASM may deliver two press/release pairs without a DblClick event.
        # Use the original input timestamp so a slow repaint cannot split them.
        name = (App.ActiveDocument.Name if App.ActiveDocument else None, item.data(QtCore.Qt.UserRole))
        stamp = self.history_event_time or time.monotonic() * 1000
        previous = self.last_history_click
        self.last_history_click = (name, stamp)
        if previous and previous[0] == name and 0 <= stamp - previous[1] <= max(700, QtWidgets.QApplication.doubleClickInterval()):
            self.last_history_click = None
            self.safe(self.edit_item, item)
        else:
            self.history_selection(item)

    def history_selection(self, item):
        if self.session:
            return
        doc = App.ActiveDocument
        obj = doc.getObject(item.data(QtCore.Qt.UserRole)) if doc else None
        if obj:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)

    def tree_menu(self, pos):
        if self.session:
            return
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self.tree)
        menu.addAction('編集', lambda: self.safe(self.edit_item, item))
        def rename():
            doc = App.ActiveDocument
            obj = doc.getObject(item.data(0, QtCore.Qt.UserRole)) if doc else None
            if obj:
                title, ok = QtWidgets.QInputDialog.getText(self.main, '名前を変更', '名前', text=obj.Label)
                if ok and title.strip():
                    with transaction(doc, '名前を変更'):
                        obj.Label = title.strip()
        menu.addAction('名前を変更', lambda: self.safe(rename))
        # Non-modal popup avoids a nested exec loop across JSPI.
        self.context_menu = menu
        menu.popup(self.tree.viewport().mapToGlobal(pos))

    def search_panel(self):
        self.clear_panel('コマンド検索')
        query = self.field('search', '検索', '')
        results = QtWidgets.QListWidget()
        results.setObjectName('CAD_SearchResults')
        self.form.addRow(results)
        def filter_actions(text):
            results.clear()
            for name, action in self.actions.items():
                if name not in ('search', 'cancel') and (text.lower() in action.text().lower() or text.lower() in name.lower()):
                    item = QtWidgets.QListWidgetItem(action.text())
                    item.setData(QtCore.Qt.UserRole, name)
                    results.addItem(item)
            if results.count():
                results.setCurrentRow(0)
        def run_result():
            item = results.currentItem()
            if item:
                name = item.data(QtCore.Qt.UserRole)
                if not self.actions[name].isEnabled():
                    self.status('現在の文書・編集中の状態では利用できない機能です。', True)
                    return
                self.route(name)
        results.itemActivated.connect(lambda *_: run_result())
        query.returnPressed.connect(run_result)
        self.button('実行', run_result, 'search_run')
        query.textChanged.connect(filter_actions)
        filter_actions('')
        query.setFocus()

    def release_native_tasks(self):
        if self.native_task_widget is not None:
            self.native_task_dock.setWidget(self.native_task_widget)
            self.native_task_widget = self.native_task_dock = None
        self.native_task_active = False
        self.native_task_sketch = False
        self.native_task_pending = False
        if hasattr(self, 'native_host'):
            self.native_host.hide()
        if hasattr(self, 'body'):
            self.body.show()

    def show_native_tasks(self, sketch=False):
        self.clear_panel('作図パラメータ' if sketch else '操作')
        self.current_command = 'sketch_native' if sketch else 'native_task'
        self.native_task_sketch = sketch
        self.native_task_active = True
        self.native_task_pending = True
        self.body.hide()
        if not hasattr(self, 'native_host'):
            self.native_host = QtWidgets.QWidget()
            QtWidgets.QVBoxLayout(self.native_host).setContentsMargins(0, 0, 0, 0)
            self.panel_dock.widget().layout().insertWidget(1, self.native_host, 1)
        QtCore.QTimer.singleShot(100, self.embed_native_tasks)

    def embed_native_tasks(self):
        if not self.native_task_active:
            return
        self.native_task_pending = False
        for dock in self.main.findChildren(QtWidgets.QDockWidget):
            if dock.objectName() == 'Tasks' and dock.widget():
                self.native_task_dock = dock
                self.native_task_widget = dock.widget()
                self.native_task_widget.setParent(self.native_host)
                self.native_host.layout().addWidget(self.native_task_widget)
                self.native_task_widget.show()
                self.native_host.show()
                dock.hide()
                return
        raise CadError('操作パネルの組み込みに失敗しました。')

    def update_theme(self):
        palette = self.main.palette()
        colors = tuple(palette.color(role).name() for role in
                       (QtGui.QPalette.Window, QtGui.QPalette.WindowText,
                        QtGui.QPalette.ButtonText, QtGui.QPalette.Mid))
        if colors != self.theme_signature:
            self.theme_signature = colors
            background, foreground, button, disabled = colors
            self.bar.setStyleSheet(
                'QToolBar {background:%s;color:%s;spacing:5px;padding:6px;}'
                'QToolButton {padding:7px;color:%s;}'
                'QToolButton:disabled {color:%s;}'
                'QToolButton:hover {background:%s;color:%s;}'
                'QToolButton:pressed {background:%s;color:%s;}' %
                (*colors, palette.color(QtGui.QPalette.Window).lighter(130).name(), foreground,
                 palette.color(QtGui.QPalette.Window).darker(115).name(), foreground))

    def detach_references(self):
        if self.reference_scene is not None and self.reference_root is not None:
            try:
                self.reference_scene.removeChild(self.reference_root)
            except RuntimeError:
                pass  # The document/view may already have been destroyed.
        self.reference_scene = self.reference_root = None

    def update_references(self):
        # Scene-only references never enter the document, STEP or FCStd files.
        from pivy import coin
        view = Gui.activeDocument().activeView() if Gui.activeDocument() else None
        scene = view.getSceneGraph() if view and hasattr(view, 'getSceneGraph') else None
        if scene != self.reference_scene:
            self.detach_references()
            if scene is not None:
                root = coin.SoSwitch()
                pick = coin.SoPickStyle()
                pick.style = coin.SoPickStyle.UNPICKABLE
                root.addChild(pick)
                light = coin.SoLightModel()
                light.model = coin.SoLightModel.BASE_COLOR
                root.addChild(light)
                def lines(points, color, width):
                    group = coin.SoSeparator()
                    material = coin.SoBaseColor()
                    material.rgb = color
                    style = coin.SoDrawStyle()
                    style.lineWidth = width
                    coords = coin.SoCoordinate3()
                    coords.point.setValues(0, len(points), points)
                    edges = coin.SoLineSet()
                    edges.numVertices.setValues(0, len(points) // 2, [2] * (len(points) // 2))
                    for node in (material, style, coords, edges):
                        group.addChild(node)
                    root.addChild(group)
                points = []
                for n in range(-10, 11):
                    if n:
                        k = n * 10.0
                        points.extend([(k, -100, 0), (k, 100, 0), (-100, k, 0), (100, k, 0)])
                lines(points, (0.48, 0.52, 0.57), 1)
                lines([(-100, 0, 0), (100, 0, 0)], (0.9, 0.25, 0.25), 2)
                lines([(0, -100, 0), (0, 100, 0)], (0.2, 0.7, 0.35), 2)
                lines([(0, 0, -30), (0, 0, 30)], (0.25, 0.5, 1.0), 2)
                root.whichChild = coin.SO_SWITCH_ALL
                scene.addChild(root)
                self.reference_scene, self.reference_root = scene, root
                if not sketch_in_edit(Gui) and not any(not o.Shape.isNull() for o in App.ActiveDocument.Objects if hasattr(o, 'Shape')):
                    view.viewAxonometric()
                    view.fitAll()
        if self.reference_root is not None:
            # Native Sketcher owns its grid while editing, including non-XY planes.
            self.reference_root.whichChild = coin.SO_SWITCH_ALL if self.grid_visible and not sketch_in_edit(Gui) else coin.SO_SWITCH_NONE

    def fit_view(self):
        # Keep reference geometry out of the model's fit-to-view bounds.
        from pivy import coin
        view = Gui.activeDocument().activeView() if Gui.activeDocument() else None
        if view is None or not hasattr(view, 'fitAll'):
            return
        self.update_references()
        root = self.reference_root
        previous = root.whichChild.getValue() if root is not None else None
        try:
            if root is not None and App.ActiveDocument and any(not o.Shape.isNull() for o in App.ActiveDocument.Objects if hasattr(o, 'Shape')):
                root.whichChild = coin.SO_SWITCH_NONE
            view.fitAll()
        finally:
            if root is not None:
                root.whichChild = previous

    def hide_native_chrome(self):
        for bar in self.main.findChildren(QtWidgets.QToolBar):
            if not bar.objectName().startswith('CAD_'):
                bar.hide()
        for dock in self.main.findChildren(QtWidgets.QDockWidget):
            if not dock.objectName().startswith('CAD_'):
                dock.hide()
        for widget in self.main.findChildren(QtWidgets.QWidget):
            if 'OverlayTabWidget' in widget.metaObject().className():
                widget.hide()

    def tick(self):
        try:
            doc = App.ActiveDocument
            edit = sketch_in_edit(Gui)
            if self.plane_picker and (not Gui.activeDocument() or self.plane_picker.view != Gui.activeDocument().activeView()):
                self.close_plane_picker()
                self.current_command = None
            editing_native = bool(Gui.activeDocument() and Gui.activeDocument().getInEdit())
            task_buttons = self.native_task_widget and any(box.isVisible() for box in self.native_task_widget.findChildren(QtWidgets.QDialogButtonBox))
            if self.native_task_active and not self.native_task_pending and not Gui.Control.activeDialog() and not editing_native and not task_buttons:
                self.current_command = None
                self.sketch_home(edit) if edit else self.home()
            self.update_theme()
            self.update_references()
            signature = (doc.Name if doc else None, edit.Name if edit else None,
                         bool(Gui.activeDocument() and Gui.activeDocument().getInEdit()),
                         bool(Gui.activeDocument() and hasattr(Gui.activeDocument().activeView(), 'getSceneGraph')))
            if signature != self.signature:
                self.signature = signature
                self.dirty = True
                if Gui.activeDocument() and hasattr(Gui.activeDocument().activeView(), 'setNavigationType'):
                    Gui.activeDocument().activeView().setNavigationType('Gui::RevitNavigationStyle')
                self.hide_native_chrome()
                if not self.session and not self.current_command:
                    self.sketch_home(edit) if edit else self.home()
            if self.session and doc != self.session.doc:
                self.cancel()
                self.status('文書が切り替わったため、未確定の押し出しを取り消しました。')
            if self.dirty:
                self.sync()
        except Exception as error:
            App.Console.PrintError('[cad-workspace] sync: ' + repr(error) + '\n')

    def sync(self):
        self.dirty = False
        doc = App.ActiveDocument
        # Browser close/reload must not silently discard an open design now
        # that CAD autosave is disabled. The marker is session-only MEMFS.
        try:
            if App.listDocuments():
                with open('/tmp/cad-open-documents', 'w') as marker:
                    marker.write('1')
            else:
                import os
                if os.path.exists('/tmp/cad-open-documents'):
                    os.remove('/tmp/cad-open-documents')
        except OSError:
            pass
        edit = sketch_in_edit(Gui)
        locked = self.session is not None or (self.native_task_active and not self.native_task_sketch)
        is_3d = bool(Gui.activeDocument() and hasattr(Gui.activeDocument().activeView(), 'getSceneGraph'))
        for name, action in self.actions.items():
            action.setEnabled(not locked or name == 'cancel')
        # Native Sketcher must receive Esc while drawing; only the extrusion
        # session owns it globally. Avoid consuming native tool cancellation.
        for name in ('line', 'rectangle', 'circle', 'dimension', 'trim', 'construction', 'finish'):
            self.actions[name].setEnabled(bool(edit) and not locked)
        for name, (_, sketch_only) in self.native_actions.items():
            self.actions[name].setEnabled(not locked and bool(edit if sketch_only else doc))
        for name in ('rectangle_center_exact', 'rectangle_three_points', 'circle_two_points', 'sketch_settings'):
            self.actions[name].setEnabled(bool(edit) and not locked)
        for name in ('save', 'save_as', 'export'):
            self.actions[name].setEnabled(bool(doc) and not locked)
        for name in ('extrude', 'fillet', 'chamfer', 'fit', 'grid'):
            self.actions[name].setEnabled(is_3d and not locked)
        self.actions['sketch'].setEnabled((not doc or is_3d) and not locked)
        self.actions['new_3d_view'].setEnabled(bool(doc) and not locked)
        self.syncing = True
        previous_block = self.tree.blockSignals(True)
        try:
            self.render_document(doc)
        finally:
            self.tree.blockSignals(previous_block)
            self.syncing = False

    def render_document(self, doc):
        objects = [o for o in doc.Objects if not o.Name.startswith('CADPreview')] if doc else []
        self.render_history(doc, objects)
        structure = (doc.Name if doc else None, tuple((o.Name, o.TypeId, o.Label) for o in objects))
        selected = {o.Name for o in Gui.Selection.getSelection()} if doc else set()
        if structure == self.tree_signature:
            # Keep Qt item identity across selection/visibility changes. Clearing
            # here can delete the target between the clicks of a double-click.
            for obj in objects:
                item = self.tree_items.get(obj.Name)
                if item:
                    item.setSelected(obj.Name in selected)
                    item.setCheckState(0, QtCore.Qt.Checked if obj.ViewObject.Visibility else QtCore.Qt.Unchecked)
            return
        self.tree_signature = structure
        expanded = set()
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.isExpanded():
                expanded.add(item.data(0, QtCore.Qt.UserRole))
            iterator += 1
        self.tree.clear()
        self.tree_items = {}
        if not doc:
            return
        root = QtWidgets.QTreeWidgetItem(self.tree, [doc.Label])
        root.setData(0, QtCore.Qt.UserRole, '__document__')
        root.setExpanded(True)
        items = {}
        for obj in objects:
            if obj.TypeId.endswith('Origin') or obj.TypeId.startswith('App::Plane') or obj.TypeId.startswith('App::Line'):
                continue
            parent_body = body_of(obj)
            parent = items.get(parent_body.Name, root) if parent_body and parent_body != obj else root
            item = QtWidgets.QTreeWidgetItem(parent, [obj.Label])
            item.setData(0, QtCore.Qt.UserRole, obj.Name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked if obj.ViewObject.Visibility else QtCore.Qt.Unchecked)
            item.setSelected(obj.Name in selected)
            item.setExpanded(obj.Name in expanded or (not expanded and obj.TypeId == 'PartDesign::Body'))
            items[obj.Name] = item
            self.tree_items[obj.Name] = item
    def render_history(self, doc, objects):
        features = [obj for obj in objects if obj.TypeId == 'Sketcher::SketchObject' or
                    obj.TypeId.startswith('PartDesign::') and obj.TypeId not in
                    ('PartDesign::Body', 'PartDesign::FeaturePython')]
        signature = (doc.Name if doc else None, tuple((obj.Name, obj.Label) for obj in features))
        if signature == self.history_signature:
            return
        self.history_signature = signature
        self.history.clear()
        for obj in features:
            item = QtWidgets.QListWidgetItem(obj.Label)
            item.setData(QtCore.Qt.UserRole, obj.Name)
            item.setToolTip(obj.TypeId + '\nダブルクリックで編集')
            self.history.addItem(item)

    def diagnostics(self):
        doc = App.ActiveDocument
        widgets = {}
        for widget in self.main.findChildren(QtWidgets.QWidget):
            name = widget.objectName()
            if name.startswith('CAD_') and widget.isVisible():
                center = widget.mapToGlobal(widget.rect().center())
                widgets[name] = {'x': center.x(), 'y': center.y(),
                                 'width': widget.width(), 'height': widget.height()}
        # QActions aren't widgets; expose their rendered toolbar geometry.
        for name, action in self.actions.items():
            widget = self.bar.widgetForAction(action)
            if widget and widget.isVisible():
                p = widget.mapToGlobal(widget.rect().center())
                widgets['CAD_Action_' + name] = {'x': p.x(), 'y': p.y(), 'enabled': action.isEnabled()}
        def volume(obj):
            try:
                return obj.Shape.Volume if not obj.Shape.isNull() else None
            except Exception:
                return None
        return {'is3DView': bool(Gui.activeDocument() and hasattr(Gui.activeDocument().activeView(), 'getSceneGraph')), 'nativeCommandCount': len(self.native_actions), 'version': VERSION, 'document': doc.Name if doc else None,
                'sketch': getattr(sketch_in_edit(Gui), 'Name', None),
                'geometryCount': getattr(sketch_in_edit(Gui), 'GeometryCount', None),
                'message': self.message.text(),
                'session': self.current_command, 'widgets': widgets,
                'features': [{'name': o.Name, 'type': o.TypeId,
                              'volume': volume(o)}
                             for o in doc.Objects if hasattr(o, 'Shape') and not o.Name.startswith('CADPreview')] if doc else []}

    def stop(self):
        self.cancel()
        self.timer.stop()
        self.release_native_tasks()
        self.detach_references()
        Gui.Selection.removeObserver(self.observer)
        App.removeDocumentObserver(self.observer)
        for name, shortcut in self.saved_shortcuts.items():
            command = Gui.Command.get(name)
            command.resetShortcut() if shortcut is None else command.setShortcut(shortcut)
        for action, shortcut in self.shortcuts:
            action.setShortcut(shortcut)
        for action in self.actions.values():
            self.main.removeAction(action)
            action.deleteLater()
        for widget in (self.bar, self.tree_dock, self.panel_dock, self.history_dock):
            widget.hide()
            widget.deleteLater()
        for widget, visible in self.saved_visibility:
            widget.setVisible(visible)
        for params, present, value in self.overlay_state:
            params.SetString('Widgets', value) if present else params.RemString('Widgets')
        self.main.menuBar().setVisible(self.menu_visible)
        QtWidgets.QApplication.instance().removeEventFilter(self)
        preferences = App.ParamGet('User parameter:BaseApp/Preferences/View')
        preferences.SetString('NavigationStyle', self.previous_navigation)
        preferences.SetBool('ZoomAtCursor', self.previous_zoom)
        if Gui.activeDocument() and hasattr(Gui.activeDocument().activeView(), 'setNavigationType'):
            Gui.activeDocument().activeView().setNavigationType(self.previous_navigation)
        self.deleteLater()
        global WORKSPACE
        WORKSPACE = None

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonRelease and hasattr(self, 'history') and watched == self.history.viewport():
            self.history_event_time = event.timestamp() or None
        if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and event.button() == QtCore.Qt.LeftButton:
            picker = self.plane_picker or self.region_picker
            if picker and isinstance(watched, QtWidgets.QWidget):
                mdi = self.main.findChild(QtWidgets.QMdiArea)
                active = mdi.activeSubWindow() if mdi else None
                viewer = next((w for w in active.findChildren(QtWidgets.QWidget) if w.metaObject().className() == 'Gui::View3DInventorViewer'), None) if active else None
                if viewer and (watched == viewer or viewer.isAncestorOf(watched)):
                    point = viewer.mapFromGlobal(event.globalPosition().toPoint())
                    if viewer.rect().contains(point):
                        if event.type() == QtCore.QEvent.MouseButtonPress:
                            key = self.safe(picker.pick_at, point.x(), point.y())
                            if key is not None:
                                QtCore.QTimer.singleShot(0, lambda k=key, p=picker: self.safe(p.choose, k))
                                return True
                        elif self.region_picker:
                            return True
        if event.type() == QtCore.QEvent.MouseButtonDblClick and hasattr(self, 'history') and watched == self.history.viewport():
            item = self.history.itemAt(event.position().toPoint())
            if item:
                self.last_history_click = None
                QtCore.QTimer.singleShot(0, lambda target=item: self.safe(self.edit_item, target))
                return True
        if event.type() not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        text_input = isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox))
        mdi = self.main.findChild(QtWidgets.QMdiArea)
        if focus and mdi and mdi.isAncestorOf(focus) and Gui.activeDocument() and not hasattr(Gui.activeDocument().activeView(), 'getSceneGraph'):
            text_input = True
        blocked_modifiers = QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier
        name = None
        if not text_input and not event.modifiers() & blocked_modifiers:
            name = self.key_actions.get(event.text().upper())
            if event.key() == QtCore.Qt.Key_Escape:
                name = 'cancel' if self.session or self.plane_picker else None
        if event.type() == QtCore.QEvent.ShortcutOverride:
            if event.key() == QtCore.Qt.Key_Escape and self.session:
                name = 'cancel'
            protected_text_key = text_input and not event.modifiers() & blocked_modifiers and event.text().upper() in self.key_actions
            if name or protected_text_key:
                event.accept()
                return True
        if event.type() == QtCore.QEvent.KeyPress and name:
            if not event.isAutoRepeat():
                QtCore.QTimer.singleShot(0, partial(self.route, name))
            return True
        if self.session and event.type() == QtCore.QEvent.KeyPress:
            if event.modifiers() & QtCore.Qt.ControlModifier and event.key() in (QtCore.Qt.Key_Z, QtCore.Qt.Key_Y, QtCore.Qt.Key_S, QtCore.Qt.Key_N, QtCore.Qt.Key_O):
                focus = QtWidgets.QApplication.focusWidget()
                if not isinstance(focus, QtWidgets.QLineEdit):
                    self.status('押し出しを確定するか、キャンセルしてください。', True)
                    return True
        return super().eventFilter(watched, event)


def install():
    global WORKSPACE
    if WORKSPACE is not None:
        return WORKSPACE
    for module in ('SketcherGui', 'PartDesignGui'):
        __import__(module)
    main = Gui.getMainWindow()
    original = [(w, w.isVisible()) for w in main.findChildren(QtWidgets.QDockWidget) + main.findChildren(QtWidgets.QToolBar)]
    menu_visible = main.menuBar().isVisible()
    shortcuts = [(a, a.shortcut()) for a in main.findChildren(QtGui.QAction)]
    try:
        WORKSPACE = Workspace()
    except Exception:
        for widget in main.findChildren(QtWidgets.QWidget):
            if widget.objectName().startswith('CAD_'):
                widget.hide()
                widget.deleteLater()
        for action in main.findChildren(QtGui.QAction):
            if action.objectName().startswith('CAD_Action_'):
                main.removeAction(action)
                action.deleteLater()
        for action, shortcut in shortcuts:
            action.setShortcut(shortcut)
        for widget, visible in original:
            widget.setVisible(visible)
        main.menuBar().setVisible(menu_visible)
        raise
    return WORKSPACE
