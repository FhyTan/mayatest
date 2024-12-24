"""
Contains a user interface for the CMT testing framework.

The dialog will display all tests found in MAYA_MODULE_PATH and allow the user to
selectively run the tests.  The dialog will also automatically get any code updates
without any need to reload if the dialog is opened before any other tools have been
run.

To open the dialog run the menu item: CMT > Utility > Unit Test Runner.
"""

from __future__ import absolute_import, division, print_function

import logging
import os
import sys
import traceback
import unittest

from maya.app.general.mayaMixin import MayaQWidgetBaseMixin
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

import mayatest.mayaunittest as mayaunittest
from mayatest.FileLine import FileLine
from mayatest.mayaunittest import new_scene

logger = logging.getLogger(__name__)

ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")

_win = None


def show():
    """Shows the browser window."""
    global _win
    if _win:
        _win.close()
    _win = MayaTestRunnerDialog()
    _win.show()


def documentation():
    raise NotImplementedError


class BaseTreeNode(object):
    """Base tree node that contains hierarchical functionality for use in a
    QAbstractItemModel"""

    def __init__(self, parent=None):
        self.children = []
        self._parent = parent

        if parent is not None:
            parent.add_child(self)

    def add_child(self, child):
        """Add a child to the node.

        :param child: Child node to add."""
        if child not in self.children:
            self.children.append(child)

    def remove(self):
        """Remove this node and all its children from the tree."""
        if self._parent:
            row = self.row()
            self._parent.children.pop(row)
            self._parent = None
        for child in self.children:
            child.remove()

    def child(self, row):
        """Get the child at the specified index.

        :param row: The child index.
        :return: The tree node at the given index or None if the index was out of
        bounds.
        """
        try:
            return self.children[row]
        except IndexError:
            return None

    def child_count(self):
        """Get the number of children in the node"""
        return len(self.children)

    def parent(self):
        """Get the parent of node"""
        return self._parent

    def row(self):
        """Get the index of the node relative to the parent"""
        if self._parent is not None:
            return self._parent.children.index(self)
        return 0

    def data(self, column):
        """Get the table display data"""
        return ""


class MayaTestRunnerDialog(MayaQWidgetBaseMixin, QMainWindow):
    def __init__(self, *args, **kwargs):
        super(MayaTestRunnerDialog, self).__init__(*args, **kwargs)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Maya Unit Test Runner")
        self.resize(1000, 600)

        toolbar = self.addToolBar("Tools")
        action = toolbar.addAction("Run All Tests")
        action.setIcon(QIcon(QPixmap(os.path.join(ICON_DIR, "cmt_run_all_tests.png"))))
        action.triggered.connect(self.run_all_tests)
        action.setToolTip("Run all tests.")

        action = toolbar.addAction("Run Selected Tests")
        action.setIcon(
            QIcon(QPixmap(os.path.join(ICON_DIR, "cmt_run_selected_tests.png")))
        )
        action.setToolTip("Run all selected tests.")
        action.triggered.connect(self.run_selected_tests)

        action = toolbar.addAction("Run Failed Tests")
        action.setIcon(
            QIcon(QPixmap(os.path.join(ICON_DIR, "cmt_run_failed_tests.png")))
        )
        action.setToolTip("Run all failed tests.")
        action.triggered.connect(self.run_failed_tests)

        action = toolbar.addAction("Refresh Tests")
        action.setIcon(QIcon(QPixmap(":/refresh.png")))
        action.setToolTip("Refresh the test list all failed tests.")
        action.triggered.connect(self.refresh_tests)

        self.module_line = FileLine()
        toolbar.addWidget(QLabel("Module Path:"))
        spacer = QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding)
        toolbar.addWidget(QLabel())
        toolbar.addWidget(self.module_line)

        widget = QWidget()
        self.setCentralWidget(widget)
        vbox = QVBoxLayout(widget)

        # Settings
        self.new_scene_checkbox = QCheckBox("New Scene Between Tests")
        self.new_scene_checkbox.setChecked(mayaunittest.Settings.file_new)
        self.new_scene_checkbox.toggled.connect(mayaunittest.set_file_new)
        self.new_scene_checkbox.setToolTip("Creates a new scene file after each test.")

        self.buffer_checkbox = QCheckBox("Buffer Output")
        self.buffer_checkbox.setChecked(mayaunittest.Settings.buffer_output)
        self.buffer_checkbox.toggled.connect(mayaunittest.set_buffer_output)
        self.buffer_checkbox.setToolTip("Only display output during a failed test.")

        self.new_scene_btn = QPushButton("New Scene")
        self.new_scene_btn.clicked.connect(new_scene)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(self.buffer_checkbox)
        settings_layout.addWidget(self.new_scene_checkbox)
        settings_layout.addWidget(self.new_scene_btn)

        settings_layout.addStretch()

        splitter = QSplitter(orientation=Qt.Horizontal)
        self.test_view = QTreeView()
        self.test_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        splitter.addWidget(self.test_view)
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)
        vbox.addLayout(settings_layout)
        splitter.addWidget(self.output_console)
        vbox.addWidget(splitter)
        splitter.setStretchFactor(1, 4)
        self.stream = TestCaptureStream(self.output_console)

        self.init_gui()

    def refresh_tests(self):
        self._reload_modules()

        test_suite = mayaunittest.get_module_tests(module_root=self.module_line.path)

        root_node = TestNode(test_suite)
        self.model = TestTreeModel(root_node, self)
        self.test_view.setModel(self.model)
        self.expand_tree(root_node)

    def expand_tree(self, root_node):
        """Expands all the collapsed elements in a tree starting at the root_node"""
        parent = root_node.parent()
        parent_idx = (
            self.model.createIndex(parent.row(), 0, parent) if parent else QModelIndex()
        )
        index = self.model.index(root_node.row(), 0, parent_idx)
        self.test_view.setExpanded(index, True)
        for child in root_node.children:
            self.expand_tree(child)

    def run_all_tests(self):
        """Callback method to run all the tests found in MAYA_MODULE_PATH."""
        if not hasattr(self, "model"):
            self.refresh_tests()
        else:
            self._reload_modules()

        # Get all the tests
        test_suite = mayaunittest.get_module_tests(module_root=self.module_line.path)

        self.output_console.clear()
        self.model.run_tests(self.stream, test_suite)

    def run_selected_tests(self):
        """Callback method to run the selected tests in the UI."""
        self._reload_modules()
        test_suite = unittest.TestSuite()

        indices = self.test_view.selectedIndexes()
        if not indices:
            return

        # Remove any child nodes if parent nodes are in the list.  This will prevent duplicate
        # tests from being run.
        paths = [index.internalPointer().path() for index in indices]
        test_paths = []
        for path in paths:
            tokens = path.split(".")
            for i in range(len(tokens) - 1):
                p = ".".join(tokens[0 : i + 1])
                if p in paths:
                    break
            else:
                test_paths.append(path)

        # Now get the tests with the pruned paths
        for path in test_paths:
            mayaunittest.get_tests(
                directories=[self.module_line.path],
                test=path,
                test_suite=test_suite,
            )

        self.output_console.clear()
        self.model.run_tests(self.stream, test_suite)

    def run_failed_tests(self):
        """Callback method to run all the tests with fail or error statuses."""
        self._reload_modules()
        test_suite = unittest.TestSuite()
        for node in self.model.node_lookup.values():
            if isinstance(node.test, unittest.TestCase) and node.get_status() in {
                TestStatus.fail,
                TestStatus.error,
            }:
                mayaunittest.get_tests(
                    directories=[self.module_line.path],
                    test=node.path(),
                    test_suite=test_suite,
                )
        self.output_console.clear()
        self.model.run_tests(self.stream, test_suite)

    def _reload_modules(self):
        """Reloads all the modules in the module path."""
        module_path = self.module_line.path
        if not module_path:
            QMessageBox.warning(
                self,
                "No Module Path",
                "Please set the module path to run tests.",
                QMessageBox.Ok,
            )
        mayaunittest.reload_modules(self.module_line.path)

    def init_gui(self):
        settings = QSettings("AutodeskMaya", "Unit Test Runner")

        try:
            self.restoreGeometry(settings.value("geometry"))
        except AttributeError:
            pass

        try:
            module_path = settings.value("module_path")
            self.module_line.path = module_path
        except Exception as e:
            print(e)

    def closeEvent(self, event):
        """Close event to clean up everything."""
        global _win
        self.deleteLater()
        _win = None

        # Save the module path and widget position
        self.settings = QSettings("AutodeskMaya", "Unit Test Runner")
        self.settings.setValue("module_path", self.module_line.path)
        self.settings.setValue("geometry", self.saveGeometry())
        QWidget.closeEvent(self, event)


class TestCaptureStream(object):
    """Allows the output of the tests to be displayed in a QTextEdit."""

    success_color = QColor(92, 184, 92)
    fail_color = QColor(240, 173, 78)
    error_color = QColor(217, 83, 79)
    skip_color = QColor(88, 165, 204)
    normal_color = QColor(200, 200, 200)

    def __init__(self, text_edit):
        self.text_edit = text_edit

    def write(self, text):
        """Write text into the QTextEdit."""
        # Color the output
        if text.startswith("ok"):
            self.text_edit.setTextColor(TestCaptureStream.success_color)
        elif text.startswith("FAIL"):
            self.text_edit.setTextColor(TestCaptureStream.fail_color)
        elif text.startswith("ERROR"):
            self.text_edit.setTextColor(TestCaptureStream.error_color)
        elif text.startswith("skipped"):
            self.text_edit.setTextColor(TestCaptureStream.skip_color)

        self.text_edit.insertPlainText(text)
        self.text_edit.setTextColor(TestCaptureStream.normal_color)

    def flush(self):
        pass


class TestStatus:
    """The possible status values of a test."""

    not_run = 0
    success = 1
    fail = 2
    error = 3
    skipped = 4


class TestNode(BaseTreeNode):
    """A node representing a Test, TestCase, or TestSuite for display in a QTreeView."""

    success_icon = QPixmap(os.path.join(ICON_DIR, "cmt_test_success.png"))
    fail_icon = QPixmap(os.path.join(ICON_DIR, "cmt_test_fail.png"))
    error_icon = QPixmap(os.path.join(ICON_DIR, "cmt_test_error.png"))
    skip_icon = QPixmap(os.path.join(ICON_DIR, "cmt_test_skip.png"))

    def __init__(self, test, parent=None):
        super(TestNode, self).__init__(parent)
        self.test = test
        self.tool_tip = str(test)
        self.status = TestStatus.not_run
        if isinstance(self.test, unittest.TestSuite):
            for test_ in self.test:
                if isinstance(test_, unittest.TestCase) or test_.countTestCases():
                    self.add_child(TestNode(test_, self))
        if "ModuleImportFailure" == self.test.__class__.__name__:
            try:
                getattr(self.test, self.name())()
            except ImportError:
                self.tool_tip = traceback.format_exc()
                logger.warning(self.tool_tip)

    def name(self):
        """Get the name to print in the view."""
        if isinstance(self.test, unittest.TestCase):
            return self.test._testMethodName
        elif isinstance(self.child(0).test, unittest.TestCase):
            return self.child(0).test.__class__.__name__
        else:
            return self.child(0).child(0).test.__class__.__module__

    def path(self):
        """Gets the import path of the test.  Used for finding the test by name."""
        if self.parent() and self.parent().parent():
            return "{0}.{1}".format(self.parent().path(), self.name())
        else:
            return self.name()

    def get_status(self):
        """Get the status of the TestNode.

        Nodes with children like the TestSuites, will get their status based on the
        status of the leaf nodes (the TestCases).

        :return: A status value from TestStatus.
        """
        if "ModuleImportFailure" in [self.name(), self.test.__class__.__name__]:
            return TestStatus.error
        if not self.children:
            return self.status
        result = TestStatus.not_run
        for child in self.children:
            child_status = child.get_status()
            if child_status == TestStatus.error:
                # Error status has highest priority so propagate that up to the parent
                return child_status
            elif child_status == TestStatus.fail:
                result = child_status
            elif child_status == TestStatus.success and result != TestStatus.fail:
                result = child_status
            elif child_status == TestStatus.skipped and result != TestStatus.fail:
                result = child_status
        return result

    def get_icon(self):
        """Get the status icon to display with the Test."""
        status = self.get_status()
        return [
            None,
            TestNode.success_icon,
            TestNode.fail_icon,
            TestNode.error_icon,
            TestNode.skip_icon,
        ][status]


class TestTreeModel(QAbstractItemModel):
    """The model used to populate the test tree view."""

    def __init__(self, root, parent=None):
        super(TestTreeModel, self).__init__(parent)
        self._root_node = root
        self.node_lookup = {}
        # Create a lookup so we can find the TestNode given a TestCase or TestSuite
        self.create_node_lookup(self._root_node)

    def create_node_lookup(self, node):
        """Create a lookup so we can find the TestNode given a TestCase or TestSuite.  The lookup will be used to set
        test statuses and tool tips after a test run.

        :param node: Node to add to the map.
        """
        self.node_lookup[str(node.test)] = node
        for child in node.children:
            self.create_node_lookup(child)

    def rowCount(self, parent):
        """Return the number of rows with this parent."""
        if not parent.isValid():
            parent_node = self._root_node
        else:
            parent_node = parent.internalPointer()
        return parent_node.child_count()

    def columnCount(self, parent):
        return 1

    def data(self, index, role):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.DisplayRole:
            return node.name()
        elif role == Qt.DecorationRole:
            return node.get_icon()
        elif role == Qt.ToolTipRole:
            return node.tool_tip

    def setData(self, index, value, role=Qt.EditRole):
        node = index.internalPointer()

        data_changed_kwargs = [index, index, []]

        if role == Qt.EditRole:
            self.dataChanged.emit(*data_changed_kwargs)
        if role == Qt.DecorationRole:
            node.status = value
            self.dataChanged.emit(*data_changed_kwargs)
            if node.parent() is not self._root_node:
                self.setData(self.parent(index), value, role)
        elif role == Qt.ToolTipRole:
            node.tool_tip = value
            self.dataChanged.emit(*data_changed_kwargs)

    def headerData(self, section, orientation, role):
        return "Tests"

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def parent(self, index):
        node = index.internalPointer()
        parent_node = node.parent()
        if parent_node == self._root_node:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def index(self, row, column, parent):
        if not parent.isValid():
            parent_node = self._root_node
        else:
            parent_node = parent.internalPointer()

        child_item = parent_node.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        else:
            return QModelIndex()

    def get_index_of_node(self, node):
        if node is self._root_node:
            return QModelIndex()
        return self.index(node.row(), 0, self.get_index_of_node(node.parent()))

    def run_tests(self, stream, test_suite):
        """Runs the given TestSuite.

        :param stream: A stream object with write functionality to capture the test output.
        :param test_suite: The TestSuite to run.
        """
        runner = unittest.TextTestRunner(
            stream=stream, verbosity=2, resultclass=mayaunittest.TestResult
        )
        runner.failfast = False
        runner.buffer = mayaunittest.Settings.buffer_output
        result = runner.run(test_suite)

        self._set_test_result_data(result.failures, TestStatus.fail)
        self._set_test_result_data(result.errors, TestStatus.error)
        self._set_test_result_data(result.skipped, TestStatus.skipped)

        for test in result.successes:
            node = self.node_lookup[str(test)]
            index = self.get_index_of_node(node)
            self.setData(index, "Test Passed", Qt.ToolTipRole)
            self.setData(index, TestStatus.success, Qt.DecorationRole)

    def _set_test_result_data(self, test_list, status):
        """Store the test result data in model.

        :param test_list: A list of tuples of test results.
        :param status: A TestStatus value."""
        for test, reason in test_list:
            node = self.node_lookup[str(test)]
            index = self.get_index_of_node(node)
            self.setData(index, reason, Qt.ToolTipRole)
            self.setData(index, status, Qt.DecorationRole)
