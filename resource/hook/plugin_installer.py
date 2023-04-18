# :coding: utf-8
# :copyright: Copyright (c) 2014 ftrack

import os
import sys
import logging

cwd = os.path.dirname(__file__)
sources = os.path.abspath(os.path.join(cwd, '..', 'dependencies'))
sys.path.append(sources)

import platform
import ftrack_api
from ftrack_connect.qt import QtWidgets, QtCore, QtGui
import qtawesome as qta

from ftrack_connect.ui.widget.overlay import BlockingOverlay, BusyOverlay
import ftrack_connect.ui.application
from ftrack_connect.asynchronous import asynchronous

from ftrack_connect_plugin_manager import (
    InstallerBlockingOverlay,
    PluginProcessor,
    DndPluginList,
    ROLES,
)

logger = logging.getLogger('ftrack_connect.plugin.plugin_installer')


class PluginInstaller(ftrack_connect.ui.application.ConnectWidget):
    '''Show and manage plugin installations.'''

    name = 'Plugins'

    installation_done = QtCore.Signal()
    installation_started = QtCore.Signal()
    installation_in_progress = QtCore.Signal(object)

    refresh_started = QtCore.Signal()
    refresh_done = QtCore.Signal()

    # default methods
    def __init__(self, session, parent=None):
        '''Instantiate the actions widget.'''
        super(PluginInstaller, self).__init__(session, parent=parent)
        self.reset_plugin_list()

        self.plugin_processor = PluginProcessor()

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self.notification_widget = NotificationWidget()
        self.notification_widget.setLayout(QtWidgets.QHBoxLayout())
        self.notification_widget.layout().setSpacing(5)
        self.notification_widget.setAutoFillBackground(True)
        self.notification_widget.setStyleSheet(
            '''background-color: #bfffbf;'''
        )
        self.notification_widget.setVisible(False)

        icon = QtWidgets.QLabel()
        icon.setPixmap(
            QtGui.QIcon(qta.icon('mdi6.update')).pixmap(QtCore.QSize(20, 20))
        )
        self.notification_widget.layout().addWidget(icon)

        self.notification_label = QtWidgets.QLabel()
        self.notification_label.setStyleSheet('''color: #000;''')
        self.notification_widget.layout().addWidget(
            self.notification_label, 100
        )

        self.layout().addWidget(self.notification_widget)

        self.content_widget = QtWidgets.QWidget()
        self.content_widget.setLayout(QtWidgets.QVBoxLayout())

        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText('Search plugin...')

        self.content_widget.layout().addWidget(self.search_bar)
        label = QtWidgets.QLabel(
            'Check the plugins you want to install or add your'
            ' local plugins by dropping them on the list below'
        )
        label.setWordWrap(True)
        label.setMargin(5)
        self.content_widget.layout().addWidget(label)

        # plugin list
        self.plugin_list_widget = DndPluginList(self.session)
        self.content_widget.layout().addWidget(self.plugin_list_widget)

        # apply and reset button.
        button_layout = QtWidgets.QHBoxLayout()

        self.apply_button = QtWidgets.QPushButton('Install Plugins')
        self.apply_button.setIcon(QtGui.QIcon(qta.icon('mdi6.check')))
        self.apply_button.setDisabled(True)

        self.reset_button = QtWidgets.QPushButton('Clear selection')
        self.reset_button.setIcon(QtGui.QIcon(qta.icon('mdi6.lock-reset')))
        self.reset_button.setMaximumWidth(120)

        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.reset_button)

        self.content_widget.layout().addLayout(button_layout)

        self.layout().addWidget(self.content_widget, 100)

        # overlays
        self.blockingOverlay = InstallerBlockingOverlay(self)
        self.blockingOverlay.hide()
        self.blockingOverlay.confirmButton.clicked.connect(self.refresh)
        self.blockingOverlay.restartButton.clicked.connect(
            self.requestConnectRestart.emit
        )

        self.busyOverlay = BusyOverlay(self, 'Updating....')
        self.busyOverlay.hide()

        # wire connections
        self.notification_widget.clicked.connect(self._on_apply_changes)
        self.apply_button.clicked.connect(self._on_apply_changes)
        self.reset_button.clicked.connect(self.refresh)
        self.search_bar.textChanged.connect(
            self.plugin_list_widget.proxy_model.setFilterFixedString
        )

        self.installation_started.connect(self.busyOverlay.show)
        self.installation_done.connect(self.busyOverlay.hide)
        self.installation_done.connect(self._show_user_message)

        self.installation_done.connect(self._reset_overlay)
        self.installation_in_progress.connect(self._update_overlay)

        self.refresh_started.connect(self.busyOverlay.show)
        self.refresh_done.connect(self.busyOverlay.hide)

        self.plugin_list_widget.plugin_model.itemChanged.connect(
            self.enable_apply_button
        )

        # refresh
        self.refresh()

    def reset_plugin_list(self):
        self.counter = 0
        self._plugins_to_install = []

    def emit_downloaded_plugins(self, plugins):
        metadata = []

        for plugin in plugins:
            name = str(plugin.data(ROLES.PLUGIN_NAME))
            version = str(plugin.data(ROLES.PLUGIN_VERSION))
            os = str(platform.platform())

            plugin_data = {'name': name, 'version': version, 'os': os}
            metadata.append(plugin_data)

        ftrack_connect.usage.send_event(
            self.session,
            'INSTALLED-CONNECT-PLUGINS',
            metadata,
            asynchronous=True,
        )

    def enable_apply_button(self, item):
        '''Check the plugins state.'''
        self.apply_button.setDisabled(True)
        items = []
        for index in range(self.plugin_list_widget.plugin_model.rowCount()):
            if (
                self.plugin_list_widget.plugin_model.item(index).checkState()
                == QtCore.Qt.Checked
            ):
                items.append(self.plugin_list_widget.plugin_model.item(index))

        self._plugins_to_install = items

        if items:
            self.apply_button.setEnabled(True)

        self.apply_button.setText(
            'Install {} Plugins'.format(len(self._plugins_to_install))
        )

    @asynchronous
    def refresh(self):
        '''Force refresh of the model, fetching all the available plugins.'''
        self.refresh_started.emit()
        self.plugin_list_widget.populate_installed_plugins()
        self.plugin_list_widget.populate_download_plugins()
        self.reset_plugin_list()
        self.enable_apply_button(None)
        self.notification_widget.setVisible(
            0 < len(self._plugins_to_install)
        )
        self.notification_label.setText(
            '{} plugin{} update{} available, click to install...'.format(
                len(self._plugins_to_install),
                's' if len(self._plugins_to_install) > 1 else '',
                's' if len(self._plugins_to_install) > 1 else '',
            )
        )
        self.refresh_done.emit()

    def _show_user_message(self):
        '''Show final message to the user.'''
        self.blockingOverlay.setMessage('<h2>Installation finished!</h2>')
        self.blockingOverlay.confirmButton.show()
        self.blockingOverlay.show()

    def _reset_overlay(self):
        self.reset_plugin_list()
        self.busyOverlay.setMessage('<h2>Updating....</h2>')

    def _update_overlay(self, item):
        '''Update the overlay with the current item *information*.'''
        self.counter += 1

        self.busyOverlay.setMessage(
            '<h2>Installing {} of {} plugins...</h2></br>'
            '{}, Version {}'.format(
                self.counter,
                len(self._plugins_to_install),
                item.data(ROLES.PLUGIN_NAME),
                str(item.data(ROLES.PLUGIN_VERSION)),
            )
        )

    @asynchronous
    def _on_apply_changes(self, event=None):
        '''Will process all the selected plugins.'''
        self.installation_started.emit()
        num_items = self.plugin_list_widget.plugin_model.rowCount()
        for i in range(num_items):
            item = self.plugin_list_widget.plugin_model.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                self.installation_in_progress.emit(item)
                self.plugin_processor.process(item)
        self.installation_done.emit()
        self.emit_downloaded_plugins(self._plugins_to_install)
        self.reset_plugin_list()


class NotificationWidget(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super(NotificationWidget, self).__init__(parent=None)

    def mousePressEvent(self, event):
        '''(Override)'''
        self.clicked.emit()
        return super(NotificationWidget, self).mousePressEvent(event)


def register(session, **kw):
    '''Register plugin. Called when used as an plugin.'''
    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an old or incompatible API and
    # return without doing anything.
    if not isinstance(session, ftrack_api.session.Session):
        logger.debug(
            'Not subscribing plugin as passed argument {0!r} is not an '
            'ftrack_api.Session instance.'.format(session)
        )
        return

    #  Uncomment to register plugin
    plugin = ftrack_connect.ui.application.ConnectWidgetPlugin(PluginInstaller)
    plugin.register(session, priority=30)
