import os
import json
from os.path import join, normpath, dirname, exists
from typing import Tuple, Optional
import sys
from multiprocessing import Value, Process
from ctypes import c_wchar_p
import importlib
from types import ModuleType

from fbs._state import SETTINGS
from functools import lru_cache
from fbs.error import FbsError
from fbs._settings import expand_placeholders


@lru_cache
def _get_paths() -> dict:
    """Get the user configurable paths mapping."""
    paths_file = project_path("paths.json")
    if os.path.isfile(paths_file):
        try:
            with open(paths_file) as f:
                _paths = json.load(f)
            if not isinstance(_paths, dict):
                raise TypeError("paths.json file must contain a dictionary if defined.")
        except Exception as e:
            raise FbsError(e) from e
        return _paths
    else:
        return {}


BuildSystemDefault = "build_system"
IconsDefault = "icons"


@lru_cache
def get_build_system_dir() -> str:
    """
    Get path to the build system directory in the project.
    Defaults to "build_system"
    """
    return _get_paths().get("build_path", BuildSystemDefault)


@lru_cache
def get_icon_dir() -> str:
    """
    Get the path to the icon directory in the project.
    Defaults to "icons"
    """
    return SETTINGS["icon_dir"]


def _get_module(module_name: str, python_path: Optional[str] = None) -> Tuple[ModuleType, bool]:
    """Try and import the module name. Modify sys.path if required."""
    try:
        return importlib.import_module(module_name), False
    except ImportError as e:
        if python_path and python_path not in sys.path:
            sys.path.append(python_path)
            return importlib.import_module(module_name), True
        raise e


def _find_script_path(module_name: str, python_path: str, script_path: Value, python_path_needed: Value):
    """
    Find the path to the script. This must be run in a new process because it may modify sys.path.
    Get the loader for the main module.
    This tries to find it without modifying sys.path. If that fails python_path is added before trying again.
    """
    mod, python_path_needed.value = _get_module(module_name, python_path)
    if hasattr(mod, "__path__"):
        # It is a package
        try:
            mod, _ = _get_module(f"{module_name}.__main__")
        except ImportError:
            raise FbsError(f"{module_name} is a package which needs a __main__.py to be executable.")
        else:
            if hasattr(mod, "__path__"):
                raise FbsError(f"{module_name} is a package which needs a __main__.py to be executable.")
    script_path.value = mod.__file__


@lru_cache
def get_script_path() -> Tuple[str, bool]:
    """
    Get the path of the python main script.
    This is the path that is executed in `fbs run` and passed to pyinstaller in `fbs freeze`
    Returns the path to the script and a bool. True if sys.path needs to be modified.
    """
    script_path = Value(c_wchar_p)
    python_path_needed = Value("b")
    p = Process(target=_find_script_path, args=(SETTINGS["main_module"], project_path(get_python_path()), script_path, python_path_needed))
    p.start()
    p.join()
    # module_path.value is the path to the
    return script_path.value, python_path_needed.value


@lru_cache
def get_python_path() -> str:
    """Get the path that python should run from."""
    return SETTINGS["python_path"]


@lru_cache
def get_configurable_settings() -> dict:
    return {
        "build_system_dir": get_build_system_dir(),
    }


def fix_path(base_dir, path_str):
    return normpath(join(base_dir, *path_str.split("/")))


def default_path(path_str: str) -> str:
    """
    Get the full path to a default file.
    Does not apply substitutions.
    >>> path = default_path("${build_system_dir}/build/settings/base.json")
    """
    defaults_dir = join(dirname(__file__), "_defaults")
    return fix_path(defaults_dir, path_str)


def get_project_root() -> str:
    """Get the root project path"""
    try:
        return SETTINGS["project_dir"]
    except KeyError:
        error_message = (
            "Cannot call project_path(...) until fbs.init(...) has been " "called."
        )
        raise FbsError(error_message) from None


def project_path(path_str):
    """
    Return the absolute path of the given file in the project directory. For
    instance: path('src/my_app'). The `path_str` argument should always use
    forward slashes `/`, even on Windows. You can use placeholders to refer to
    settings. For example: path('${freeze_dir}/foo').
    """
    project_dir = get_project_root()
    path_str = expand_placeholders(path_str, SETTINGS)
    return fix_path(project_dir, path_str)


def get_settings_paths(profiles):
    return list(
        filter(
            exists,
            (
                path_fn("${build_system_dir}/build/settings/%s.json" % profile)
                for path_fn in (default_path, project_path)
                for profile in profiles
            ),
        )
    )