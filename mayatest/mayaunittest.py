"""
Contains functions and classes to aid in the unit testing process within Maya.

The main classes are:
TestCase - A derived class of unittest.TestCase which add convenience functionality such as auto plug-in
           loading/unloading, and auto temporary file name generation and cleanup.
TestResult - A derived class of unittest.TextTestResult which customizes the test result so we can do things like do a
            file new between each test and suppress script editor output.

To write tests for this system you need to,
    a) Derive from cmt.test.TestCase
    b) Write one or more tests that use the unittest module's assert methods to validate the results.

Example usage:

# test_sample.py
from cmt.test import TestCase
class SampleTests(TestCase):
    def test_create_sphere(self):
        sphere = cmds.polySphere(n='mySphere')[0]
        self.assertEqual('mySphere', sphere)

# To run just this test case in Maya
import cmt.test
cmt.test.run_tests(test='test_sample.SampleTests')

# To run an individual test in a test case
cmt.test.run_tests(test='test_sample.SampleTests.test_create_sphere')

# To run all tests
cmt.test.run_tests()
"""

import inspect
import logging
import os
import shutil
import sys
import tempfile
import unittest
import uuid

import maya.cmds as cmds

# The environment variable that signifies tests are being run with the custom TestResult class.
CMT_TESTING_VAR = "CMT_UNITTEST"

logger = logging.getLogger(__name__)


def new_scene():
    cmds.file(f=True, new=True)


def reload_modules(user_path: str):
    """Reload all modules that belong to the given path.

    @param user_path: The path to the modules to reload.
    """
    if not user_path:
        return

    user_path = user_path.lower().replace("\\", "/")
    for name, module in list(sys.modules.items()):
        try:
            module_file_path = inspect.getfile(module).lower().replace("\\", "/")
            if module_file_path.startswith(user_path):
                logger.info(f"reload module: {name}")
                del sys.modules[name]
        except:
            pass


def run_tests(directories=None, test=None, test_suite=None):
    """Run all the tests in the given paths.

    @param directories: A generator or list of paths containing tests to run.
    @param test: Optional name of a specific test to run.
    @param test_suite: Optional TestSuite to run.  If omitted, a TestSuite will be generated.
    """
    if test_suite is None:
        test_suite = get_tests(directories, test)

    runner = unittest.TextTestRunner(verbosity=2, resultclass=TestResult)
    runner.failfast = False
    runner.buffer = Settings.buffer_output
    runner.run(test_suite)


def get_module_tests(module_root, pattern="test_*.py"):
    """Search for tests in this single module"""

    test_suite = unittest.TestSuite()
    directories_added_to_path = []

    discovered_suite = unittest.TestLoader().discover(module_root, pattern=pattern)

    if discovered_suite.countTestCases():
        test_suite.addTests(discovered_suite)

    # Remove the added paths.
    for path in directories_added_to_path:
        sys.path.remove(path)

    return test_suite


def get_tests(directories, test=None, test_suite=None, pattern="test_*.py"):
    """Get a unittest.TestSuite containing all the desired tests.

    @param directories: The list of directories with which to search for tests.
    @param test: Optional test path to find a specific test such as 'test_mytest.SomeTestCase.test_function'.
    @param test_suite: Optional unittest.TestSuite to add the discovered tests to.  If omitted a new TestSuite will be
    created.
    @return: The populated TestSuite.
    """
    if directories is None:
        raise ValueError("directories must be specified.")

    # Populate a TestSuite with all the tests
    if test_suite is None:
        test_suite = unittest.TestSuite()

    if test:
        # Find the specified test to run
        directories_added_to_path = [p for p in directories if add_to_path(p)]
        discovered_suite = unittest.TestLoader().loadTestsFromName(test)
        if discovered_suite.countTestCases():
            test_suite.addTests(discovered_suite)
    else:
        # Find all tests to run
        directories_added_to_path = []
        for p in directories:
            discovered_suite = unittest.TestLoader().discover(p, pattern=pattern)
            if discovered_suite.countTestCases():
                test_suite.addTests(discovered_suite)

    # Remove the added paths.
    for path in directories_added_to_path:
        sys.path.remove(path)

    return test_suite


class Settings(object):
    """Contains options for running tests."""

    # Specifies where files generated during tests should be stored
    # Use a uuid subdirectory so tests that are running concurrently such as on a build server
    # do not conflict with each other.
    temp_dir = os.path.join(tempfile.gettempdir(), "mayaunittest", str(uuid.uuid4()))

    # Controls whether temp files should be deleted after running all tests in the test case
    delete_files = True

    # Specifies whether the standard output and standard error streams are buffered during the test run.
    # Output during a passing test is discarded. Output is echoed normally on test fail or error and is
    # added to the failure messages.
    buffer_output = False

    # Controls whether we should do a file new between each test case
    file_new = True


def set_temp_dir(directory):
    """Set where files generated from tests should be stored.

    @param directory: A directory path.
    """
    if os.path.exists(directory):
        Settings.temp_dir = directory
    else:
        raise RuntimeError("{0} does not exist.".format(directory))


def set_delete_files(value):
    """Set whether temp files should be deleted after running all tests in a test case.

    @param value: True to delete files registered with a TestCase.
    """
    Settings.delete_files = value


def set_buffer_output(value):
    """Set whether the standard output and standard error streams are buffered during the test run.

    @param value: True or False
    """
    Settings.buffer_output = value


def set_file_new(value):
    """Set whether a new file should be created after each test.

    @param value: True or False
    """
    Settings.file_new = value


def add_to_path(path):
    """Add the specified path to the system path.

    @param path: Path to add.
    @return True if path was added. Return false if path does not exist or path was already in sys.path
    """
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)
        return True
    return False


class TestCase(unittest.TestCase):
    """Base class for unit test cases run in Maya.

    Tests do not have to inherit from this TestCase but this derived TestCase contains convenience
    functions to load/unload plug-ins and clean up temporary files.
    """

    # Keep track of all temporary files that were created so they can be cleaned up after all tests have been run
    files_created = []

    # Keep track of which plugins were loaded so we can unload them after all tests have been run
    plugins_loaded = set()

    @classmethod
    def tearDownClass(cls):
        super(TestCase, cls).tearDownClass()
        cls.delete_temp_files()
        cls.unload_plugins()

    @classmethod
    def load_plugin(cls, plugin):
        """Load the given plug-in and saves it to be unloaded when the TestCase is finished.

        @param plugin: Plug-in name.
        """
        cmds.loadPlugin(plugin, qt=True)
        cls.plugins_loaded.add(plugin)

    @classmethod
    def unload_plugins(cls):
        # Unload any plugins that this test case loaded
        for plugin in cls.plugins_loaded:
            cmds.unloadPlugin(plugin)
        cls.plugins_loaded = []

    @classmethod
    def delete_temp_files(cls):
        """Delete the temp files in the cache and clear the cache."""
        # If we don't want to keep temp files around for debugging purposes, delete them when
        # all tests in this TestCase have been run
        if Settings.delete_files:
            for f in cls.files_created:
                if os.path.exists(f):
                    os.remove(f)
            cls.files_create = []
            if os.path.exists(Settings.temp_dir):
                shutil.rmtree(Settings.temp_dir)

    @classmethod
    def get_temp_filename(cls, file_name):
        """Get a unique filepath name in the testing directory.

        The file will not be created, that is up to the caller.  This file will be deleted when
        the tests are finished.
        @param file_name: A partial path ex: 'directory/somefile.txt'
        @return The full path to the temporary file.
        """
        temp_dir = Settings.temp_dir
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        base_name, ext = os.path.splitext(file_name)
        path = "{0}/{1}{2}".format(temp_dir, base_name, ext)
        count = 0
        while os.path.exists(path):
            # If the file already exists, add an incrememted number
            count += 1
            path = "{0}/{1}{2}{3}".format(temp_dir, base_name, count, ext)
        cls.files_created.append(path)
        return path

    def assertListAlmostEqual(self, first, second, places=7, msg=None, delta=None):
        """Asserts that a list of floating point values is almost equal.

        unittest has assertAlmostEqual and assertListEqual but no assertListAlmostEqual.
        """
        self.assertEqual(len(first), len(second), msg)
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, places, msg, delta)

    def tearDown(self):
        if Settings.file_new and CMT_TESTING_VAR not in os.environ.keys():
            # If running tests without the custom runner, like with PyCharm, the file new of the TestResult class isn't
            # used so call file new here
            cmds.file(f=True, new=True)


class TestResult(unittest.TextTestResult):
    """Customize the test result so we can do things like do a file new between each test and suppress script
    editor output.
    """

    def __init__(self, stream, descriptions, verbosity):
        super(TestResult, self).__init__(stream, descriptions, verbosity)
        self.successes = []

    def startTestRun(self):
        """Called before any tests are run."""
        super(TestResult, self).startTestRun()
        # Create an environment variable that specifies tests are being run through the custom runner.
        os.environ[CMT_TESTING_VAR] = "1"

        ScriptEditorState.suppress_output()
        if Settings.buffer_output:
            # Disable any logging while running tests. By disabling critical, we are disabling logging
            # at all levels below critical as well
            logging.disable(logging.CRITICAL)

    def stopTestRun(self):
        """Called after all tests are run."""
        if Settings.buffer_output:
            # Restore logging state
            logging.disable(logging.NOTSET)
        ScriptEditorState.restore_output()
        if Settings.delete_files and os.path.exists(Settings.temp_dir):
            shutil.rmtree(Settings.temp_dir)

        del os.environ[CMT_TESTING_VAR]

        super(TestResult, self).stopTestRun()

    def stopTest(self, test):
        """Called after an individual test is run.

        @param test: TestCase that just ran."""
        super(TestResult, self).stopTest(test)
        if Settings.file_new:
            cmds.file(f=True, new=True)

    def addSuccess(self, test):
        """Override the base addSuccess method so we can store a list of the successful tests.

        @param test: TestCase that successfully ran."""
        super(TestResult, self).addSuccess(test)
        self.successes.append(test)


class ScriptEditorState(object):
    """Provides methods to suppress and restore script editor output."""

    # Used to restore logging states in the script editor
    suppress_results = None
    suppress_errors = None
    suppress_warnings = None
    suppress_info = None

    @classmethod
    def suppress_output(cls):
        """Hides all script editor output."""
        if Settings.buffer_output:
            cls.suppress_results = cmds.scriptEditorInfo(q=True, suppressResults=True)
            cls.suppress_errors = cmds.scriptEditorInfo(q=True, suppressErrors=True)
            cls.suppress_warnings = cmds.scriptEditorInfo(q=True, suppressWarnings=True)
            cls.suppress_info = cmds.scriptEditorInfo(q=True, suppressInfo=True)
            cmds.scriptEditorInfo(
                e=True,
                suppressResults=True,
                suppressInfo=True,
                suppressWarnings=True,
                suppressErrors=True,
            )

    @classmethod
    def restore_output(cls):
        """Restores the script editor output settings to their original values."""
        if None not in {
            cls.suppress_results,
            cls.suppress_errors,
            cls.suppress_warnings,
            cls.suppress_info,
        }:
            cmds.scriptEditorInfo(
                e=True,
                suppressResults=cls.suppress_results,
                suppressInfo=cls.suppress_info,
                suppressWarnings=cls.suppress_warnings,
                suppressErrors=cls.suppress_errors,
            )
