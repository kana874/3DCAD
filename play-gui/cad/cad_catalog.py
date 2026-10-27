# SPDX-License-Identifier: LGPL-2.1-or-later
"""Load installed workbenches without leaving the dedicated GUI shell."""
import FreeCADGui as Gui
from PySide6 import QtCore, QtWidgets


class CommandCatalog:
    def __init__(self, workspace):
        self.workspace = workspace
        self.workbenches = {}
        self.menu = QtWidgets.QMenu('機能', workspace.bar)
        workbenches = self.menu.addMenu('機能セットを読み込む')
        for name, workbench in sorted(Gui.listWorkbenches().items()):
            if name == 'NoneWorkbench':
                continue
            key = 'workbench_' + name
            titles = {'PartDesignWorkbench': 'ソリッド設計', 'SketcherWorkbench': 'スケッチ', 'PartWorkbench': '形状', 'DraftWorkbench': 'ドラフト', 'SpreadsheetWorkbench': '表計算', 'TechDrawWorkbench': '図面', 'MeshWorkbench': 'メッシュ', 'AssemblyWorkbench': 'アセンブリ', 'SurfaceWorkbench': 'サーフェス', 'FemWorkbench': 'FEM'}
            title = titles.get(name, str(getattr(workbench, 'MenuText', name)).replace('&', ''))
            self.workbenches[key] = name
            workbenches.addAction(workspace.action(key, title + 'を読み込む'))
        self.commands = self.menu.addMenu('読み込み済みの機能')
        self.menu.addAction(workspace.action('new_3d_view', '新しい3Dビュー'))
        button = QtWidgets.QToolButton(workspace.bar)
        button.setObjectName('CAD_CatalogMenu')
        button.setText('機能')
        button.setMenu(self.menu)
        button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        workspace.bar.addWidget(button)
        self.refresh()

    def refresh(self):
        self.commands.clear()
        groups = {}
        workspace = self.workspace
        for command in sorted(Gui.listCommands()):
            if '_' not in command or command.startswith('Std_'):
                continue
            group = command.split('_', 1)[0]
            if command.startswith(group + '_Comp'):
                continue
            menu = groups.setdefault(group, None)
            if menu is None:
                menu = self.commands.addMenu(group)
                groups[group] = menu
            key = 'native_' + command
            if key not in workspace.actions:
                try:
                    title = Gui.Command.get(command).getInfo().get('menuText', command).replace('&', '')
                    title = QtCore.QCoreApplication.translate(command, title)
                except Exception:
                    title = command
                workspace.native_actions[key] = (command, command.startswith('Sketcher_'))
                workspace.action(key, title)
            menu.addAction(workspace.actions[key])
        workspace.dirty = True

    def activate(self, key):
        Gui.activateWorkbench(self.workbenches[key])
        self.workspace.hide_native_chrome()
        QtCore.QTimer.singleShot(0, self.workspace.hide_native_chrome)
        self.refresh()
        self.workspace.home()
        self.workspace.status('機能を読み込みました。「機能」メニューまたはS検索から実行できます。')
