# SPDX-License-Identifier: LGPL-2.1-or-later
"""Opt-in Qt-native modeling workspace for FreeCAD Web.

Install once after the application and translations are ready. Widgets, native
selection and shortcuts share Qt's own event loop; no DOM pointer injection.
"""
import json
from functools import partial
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets
from cad_core import (CadError, ExtrusionSession, add_circle, add_rectangle,
                      body_of, create_sketch, length, selected_sketch,
                      sketch_in_edit, transaction, valid_shape)

VERSION = '0.1.1'
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
    slotCreatedDocument = changed
    slotDeletedDocument = changed
    slotActivateDocument = changed
    slotCreatedObject = changed
    slotDeletedObject = changed
    slotChangedObject = changed
    slotRecomputedDocument = changed
    slotUndoDocument = changed
    slotRedoDocument = changed


class Workspace(QtCore.QObject):
    def __init__(self):
        self.main = Gui.getMainWindow()
        super().__init__(self.main)
        self.dirty = True
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
        self.tree_signature = None
        self.tree_items = {}
        self.editing = False
        self.current_command = None
        self.syncing = False
        self.last_sketch = None
        self.preview_ok = False
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
        elif name in ('rectangle_exact', 'circle_exact'):
            self.geometry_panel(name)
        elif name == 'search':
            self.search_panel()
        elif name == 'grid':
            sketch = sketch_in_edit(Gui)
            if sketch and hasattr(sketch.ViewObject, 'ShowGrid'):
                sketch.ViewObject.ShowGrid = not sketch.ViewObject.ShowGrid
            else:
                self.grid_visible = not self.grid_visible
                self.update_references()
        elif name == 'cancel':
            self.cancel()
        elif name in ('undo', 'redo'):
            doc = App.ActiveDocument
            if doc:
                getattr(doc, name)()
                self.home()
        elif name == 'fit':
            self.fit_view()
        elif name == 'classic':
            self.stop()
        else:
            commands = {'line': 'Sketcher_CreateLine', 'rectangle': 'Sketcher_CreateRectangle',
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
            [('search', '検索 S', 'S'), ('grid', '原点・グリッド', None), ('fit', '全体表示', None), ('classic', '標準GUI', None)]
        ]
        for group in groups:
            if bar.actions():
                bar.addSeparator()
            for name, title, key in group:
                bar.addAction(self.action(name, title, key))
        self.action('cancel', 'キャンセル', 'Esc')
        self.bar = bar

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
        self.history.itemDoubleClicked.connect(lambda item: self.safe(self.edit_item, item))
        self.history.itemClicked.connect(self.history_selection)
        self.history_dock.setWidget(self.history)

    def clear_panel(self, title):
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

    def home(self):
        self.current_command = None
        self.native_task_active = False
        self.clear_panel('デザイン')
        label = QtWidgets.QLabel('面または平面にスケッチを作成し、Eで押し出します。\nこの試用版の押し出し対象は閉じたスケッチ全体です。')
        label.setWordWrap(True)
        self.form.addRow(label)
        self.button('スケッチを作成', self.sketch_panel, 'create_sketch')
        self.button('ブラウザを表示', self.tree_dock.show, 'show_browser')
        self.button('履歴を表示', self.history_dock.show, 'show_history')
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
        self.clear_panel('スケッチを作成')
        self.combo('plane', '基準平面', [('XY（上面）', 'XY'), ('YZ（右側面）', 'YZ'), ('XZ（正面）', 'XZ')])
        self.button('この平面で開始', lambda: self.start_sketch(self.fields['plane'].currentData()), 'start_sketch')
        self.button('選択した面で開始', lambda: self.start_sketch(face=self.face_selection(), require_face=True), 'start_face')

    def start_sketch(self, plane='XY', face=None, require_face=False):
        if require_face and not face:
            raise CadError('3Dビューで平面の面を一つ選択してください。')
        sketch = create_sketch(App, Gui, plane, face)
        self.sketch_home(sketch)
        self.dirty = True

    def sketch_home(self, sketch=None):
        self.current_command = None
        self.clear_panel('スケッチ')
        self.button('幅・高さを指定して長方形', lambda: self.geometry_panel('rectangle_exact'), 'rectangle_exact')
        self.button('直径を指定して円', lambda: self.geometry_panel('circle_exact'), 'circle_exact')
        self.button('寸法を追加 D', lambda: self.route('dimension'), 'dimension')
        self.button('押し出しへ E', self.extrude_panel, 'extrude')
        self.button('スケッチを終了', self.finish_sketch, 'finish')

    def finish_sketch(self):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中ではありません。')
        Gui.activeDocument().resetEdit()
        sketch.Document.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sketch)
        self.last_sketch = sketch
        self.home()

    def geometry_panel(self, mode):
        sketch = sketch_in_edit(Gui)
        if not sketch:
            raise CadError('スケッチ編集中に実行してください。')
        self.current_command = mode
        self.clear_panel('寸法付き長方形' if mode == 'rectangle_exact' else '直径指定の円')
        self.field('x', 'X位置', '0 mm')
        self.field('y', 'Y位置', '0 mm')
        if mode == 'rectangle_exact':
            self.field('width', '幅', '50 mm')
            self.field('height', '高さ', '30 mm')
        else:
            self.field('diameter', '直径', '10 mm')
        def create():
            x, y = self.value('x', False), self.value('y', False)
            if mode == 'rectangle_exact':
                add_rectangle(App, sketch, self.value('width'), self.value('height'), x, y)
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
        label = QtWidgets.QLabel(sketch.Label + '（閉じたスケッチ全体）')
        label.setWordWrap(True)
        self.form.addRow('プロファイル', label)
        self.field('distance', '距離', '10 mm')
        options = [('結合', 'join'), ('切り取り', 'cut')]
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
        self.schedule_preview()

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
                self.session = None
                self.home()
            raise
        self.session = None
        Gui.Selection.clearSelection()
        if first_solid:
            QtCore.QTimer.singleShot(300, lambda: self.fit_view() if Gui.activeDocument() else None)
        self.home()
        self.status('押し出しを作成しました。履歴のダブルクリックで距離を変更できます。')

    def cancel(self):
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
        if obj.TypeId == 'Sketcher::SketchObject':
            if Gui.activeDocument().getInEdit():
                Gui.activeDocument().resetEdit()
            Gui.activeDocument().setEdit(obj.Name)
            self.sketch_home(obj)
        elif obj.TypeId in ('PartDesign::Pad', 'PartDesign::Pocket'):
            if Gui.activeDocument().getInEdit():
                raise CadError('スケッチ編集を終了してください。')
            self.edit_feature_panel(obj)

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
        self.form.addRow(results)
        def filter_actions(text):
            results.clear()
            for name, action in self.actions.items():
                if name not in ('search', 'cancel') and text.lower() in action.text().lower():
                    item = QtWidgets.QListWidgetItem(action.text())
                    item.setData(QtCore.Qt.UserRole, name)
                    results.addItem(item)
        results.itemDoubleClicked.connect(lambda item: self.route(item.data(QtCore.Qt.UserRole)))
        query.textChanged.connect(filter_actions)
        filter_actions('')
        query.setFocus()

    def show_native_tasks(self):
        self.native_task_active = True
        for widget in self.native_widgets:
            if isinstance(widget, QtWidgets.QDockWidget) and widget.objectName() in ('Tasks', 'Combo View'):
                widget.show()

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
        scene = view.getSceneGraph() if view else None
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
        if view is None:
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

    def tick(self):
        try:
            doc = App.ActiveDocument
            edit = sketch_in_edit(Gui)
            self.update_theme()
            self.update_references()
            signature = (doc.Name if doc else None, edit.Name if edit else None,
                         bool(Gui.activeDocument() and Gui.activeDocument().getInEdit()))
            if signature != self.signature:
                self.signature = signature
                self.dirty = True
                if Gui.activeDocument():
                    Gui.activeDocument().activeView().setNavigationType('Gui::RevitNavigationStyle')
                # Workbench activation and setEdit can show native bars/docks
                # again. Reconcile on state changes, not on every paint event.
                for bar in self.main.findChildren(QtWidgets.QToolBar):
                    if not bar.objectName().startswith('CAD_'):
                        bar.hide()
                if not self.native_task_active:
                    for dock in self.main.findChildren(QtWidgets.QDockWidget):
                        if not dock.objectName().startswith('CAD_'):
                            dock.hide()
                for widget in self.main.findChildren(QtWidgets.QWidget):
                    if 'OverlayTabWidget' in widget.metaObject().className():
                        widget.hide()
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
        edit = sketch_in_edit(Gui)
        locked = self.session is not None
        for name, action in self.actions.items():
            action.setEnabled(not locked or name == 'cancel')
        # Native Sketcher must receive Esc while drawing; only the extrusion
        # session owns it globally. Avoid consuming native tool cancellation.
        for name in ('line', 'rectangle', 'circle', 'dimension', 'trim', 'construction', 'finish'):
            self.actions[name].setEnabled(bool(edit) and not locked)
        for name in ('extrude', 'fillet', 'chamfer', 'fit', 'save', 'export', 'grid'):
            self.actions[name].setEnabled(bool(doc) and not locked)
        self.syncing = True
        previous_block = self.tree.blockSignals(True)
        try:
            self.render_document(doc)
        finally:
            self.tree.blockSignals(previous_block)
            self.syncing = False

    def render_document(self, doc):
        objects = [o for o in doc.Objects if not o.Name.startswith('CADPreview')] if doc else []
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
        self.history.clear()
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
            if obj.TypeId == 'Sketcher::SketchObject' or obj.TypeId.startswith('PartDesign::') and obj.TypeId != 'PartDesign::Body':
                history = QtWidgets.QListWidgetItem(obj.Label)
                history.setData(QtCore.Qt.UserRole, obj.Name)
                history.setToolTip(obj.TypeId + '\nダブルクリックで編集')
                self.history.addItem(history)

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
        return {'version': VERSION, 'document': doc.Name if doc else None,
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
        if Gui.activeDocument():
            Gui.activeDocument().activeView().setNavigationType(self.previous_navigation)
        self.deleteLater()
        global WORKSPACE
        WORKSPACE = None

    def eventFilter(self, watched, event):
        if event.type() not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        text_input = isinstance(focus, QtWidgets.QLineEdit)
        blocked_modifiers = QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier
        name = None
        if not text_input and not event.modifiers() & blocked_modifiers:
            name = self.key_actions.get(event.text().upper())
            if event.key() == QtCore.Qt.Key_Escape:
                name = 'cancel' if self.session else None
        if event.type() == QtCore.QEvent.ShortcutOverride:
            if event.key() == QtCore.Qt.Key_Escape and self.session:
                name = 'cancel'
            if name or text_input and event.key() != QtCore.Qt.Key_Escape:
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
