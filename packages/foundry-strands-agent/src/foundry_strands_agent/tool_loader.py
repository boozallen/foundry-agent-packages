# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tool loading utilities for dynamic module and file-based tools.

This module provides functionality to load tools from environment variables.
It supports loading tools from:
1. Python module paths (e.g., 'tools.strands_tools.calculator') via STRANDS_TOOLS_MODULES
2. File paths (e.g., './tools/weather.py') via STRANDS_TOOLS_FILES

It automatically detects and validates two tool formats:
1. @tool decorated functions (from strands-agents-tools package)
2. TOOL_SPEC modules (custom tools with explicit specifications)
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from foundry_agent_core import ToolLoadingError

DANGEROUS_MODULES = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "glob",
    "tempfile",
    "socket",
    "urllib",
    "requests",
    "http",
    "ftplib",
    "smtplib",
    "eval",
    "exec",
    "compile",
    "__builtins__",
    "importlib",
    "ctypes",
    "mmap",
    "signal",
    "threading",
    "multiprocessing",
    "pickle",
    "marshal",
    "shelve",
    "dbm",
}

SAFE_MODULES_WHITELIST = {
    "json",
    "datetime",
    "math",
    "random",
    "string",
    "collections",
    "itertools",
    "functools",
    "operator",
    "typing",
    "re",
    "uuid",
    "strands",
}


def _assert_module_in_tools_dir(module_path: str) -> None:
    spec = importlib.util.find_spec(module_path)
    if spec is None:
        raise ToolLoadingError("Tool module not found", context={"module": module_path})

    # Regular module: spec.origin points to a .py/.pyc file
    if spec.origin and spec.origin not in ("built-in", "frozen"):
        origin = Path(spec.origin).resolve()
        if TOOLS_DIR not in origin.parents:
            raise ToolLoadingError(
                "Tool module outside allowed tools directory",
                context={"module": module_path, "origin": str(origin), "tools_dir": str(TOOLS_DIR)},
            )
        return

    # Package: spec.submodule_search_locations points to package dirs
    if spec.submodule_search_locations:
        dirs = [Path(p).resolve() for p in spec.submodule_search_locations]
        if not any(TOOLS_DIR in d.parents or d == TOOLS_DIR for d in dirs):
            raise ToolLoadingError(
                "Tool package outside allowed tools directory",
                context={"module": module_path, "package_dirs": [str(d) for d in dirs], "tools_dir": str(TOOLS_DIR)},
            )
        return

    # built-in/frozen/namespace packages -> reject
    raise ToolLoadingError(
        "Tool module has no filesystem location (not allowed)",
        context={"module": module_path, "origin": spec.origin},
    )


def analyze_imports(source_code: str) -> list[str]:
    """Extract all imports from source code"""
    tree = ast.parse(source_code)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])  # Get root module
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])

    return imports


def validate_imports(source_code: str) -> bool:
    """Check if imports are safe"""
    imports = analyze_imports(source_code)

    for imp in imports:
        if imp in DANGEROUS_MODULES:
            raise ToolLoadingError(f"Dangerous import detected: {imp}")

        # Optional: Only allow whitelisted modules
        if imp not in SAFE_MODULES_WHITELIST:
            raise ToolLoadingError(f"Non-whitelisted import: {imp}")

    return True


def analyze_dangerous_calls(source_code: str):
    """Detect dangerous function calls in AST"""
    tree = ast.parse(source_code)

    DANGEROUS_FUNCTIONS = {
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "globals",
        "locals",
        "vars",
        "dir",
    }

    DANGEROUS_ATTRIBUTES = {"system", "popen", "spawn", "call", "run", "Popen", "check_output", "getstatusoutput"}

    for node in ast.walk(tree):
        # Check function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in DANGEROUS_FUNCTIONS:
                    raise ToolLoadingError(f"Dangerous function call: {node.func.id}")

            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in DANGEROUS_ATTRIBUTES:
                    raise ToolLoadingError(f"Dangerous method call: {node.func.attr}")


class ModuleSecurityAnalyzer:
    """Module security analyzer for importing tools"""

    def __init__(self):
        self.dangerous_imports = DANGEROUS_MODULES
        self.allowed_imports = SAFE_MODULES_WHITELIST
        self.max_complexity = 100  # Cyclomatic complexity limit

    def analyze_module_file(self, file_path: Path) -> bool:
        """Comprehensive security analysis"""
        try:
            with open(file_path, encoding="utf-8") as f:
                source_code = f.read()
        except Exception as e:
            raise ToolLoadingError(f"Cannot read module file: {e}")

        # 1. Basic syntax check
        try:
            ast.parse(source_code)
        except SyntaxError as e:
            raise ToolLoadingError(f"Syntax error in module: {e}")

        # 2. Size limits
        if len(source_code) > 50000:  # 50KB limit
            raise ToolLoadingError("Module too large")

        if len(source_code.splitlines()) > 1000:  # Line limit
            raise ToolLoadingError("Too many lines in module")

        # 3. Import analysis
        validate_imports(source_code)

        # 4. Function call analysis
        analyze_dangerous_calls(source_code)

        # 6. Check for obfuscation
        if self.detect_obfuscation(source_code):
            raise ToolLoadingError("Obfuscated code detected")

        return True

    def detect_obfuscation(self, source_code: str) -> bool:
        """Detect code obfuscation attempts"""
        # Check for excessive use of exec/eval strings
        exec_count = source_code.count("exec(") + source_code.count("eval(")
        if exec_count > 0:
            return True

        # Check for base64 encoded strings (potential payload)
        import re

        b64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
        if len(b64_pattern.findall(source_code)) > 3:
            return True

        # Check for hex encoded strings
        hex_pattern = re.compile(r"\\x[0-9a-fA-F]{2}")
        if len(hex_pattern.findall(source_code)) > 10:
            return True

        return False


# Tools directory for loading tools from the file system within the docker container
TOOLS_DIR = Path("/app/strands_base_agent/tools").resolve()
SECURITY_ANALYZER = ModuleSecurityAnalyzer()


async def load_tool_from_module(module_path: str) -> Any:
    """Import a tool by its Python import path.

    Uses Python's importlib to import a module by its dotted path.
    The imported module is then validated to ensure it matches one of
    the supported tool formats.

    Supports both:
    - @tool decorated functions (returns function)
    - TOOL_SPEC modules (returns module)

    Args:
        module_path: Python import path (e.g., 'tools.strands_tools.calculator')

    Returns:
        The imported tool (module or function)

    Raises:
        ToolLoadingError: If module cannot be imported or validated

    Examples:
        >>> tool = await load_tool_from_module("tools.strands_tools.calculator")
        >>> tool = await load_tool_from_module("my_company.tools.weather")
    """
    try:
        module_path = module_path.strip()
        _assert_module_in_tools_dir(module_path)

        spec = importlib.util.find_spec(module_path)
        if spec is None or not spec.origin:
            raise ToolLoadingError("Tool module not found", context={"module": module_path})

        origin = Path(spec.origin).resolve()
        SECURITY_ANALYZER.analyze_module_file(origin)

        # Run blocking import operation in thread pool
        module = await asyncio.to_thread(importlib.import_module, module_path)
        # Validation is fast, can happen in main thread
        tool = detect_and_validate_tool(module, module_path)
        return tool

    except ImportError as e:
        raise ToolLoadingError(
            f"Failed to import tool module: {module_path}",
            context={"module": module_path, "error": str(e)},
        ) from e
    except ToolLoadingError:
        raise
    except Exception as e:
        raise ToolLoadingError(
            f"Unexpected error loading tool: {e}",
            context={"module": module_path, "error": str(e)},
        ) from e


async def load_tool_from_file(file_path: str) -> Any:
    """Load a tool from a file path.

    Loads a Python module from a file system path and validates it matches
    one of the supported tool formats. The module is loaded using importlib.util
    and added to sys.modules.

    Supports both:
    - @tool decorated functions
    - TOOL_SPEC modules

    Args:
        file_path: Path to Python file containing tool (relative or absolute)

    Returns:
        The loaded tool (module or function)

    Raises:
        ToolLoadingError: If file cannot be loaded or validated

    Examples:
        >>> tool = await load_tool_from_file("./tools/weather.py")
        >>> tool = await load_tool_from_file("/absolute/path/to/custom.py")
    """
    path = Path(file_path).resolve()

    if TOOLS_DIR not in path.parents:
        raise ToolLoadingError("Tool file outside allowed tools directory", context={"path": str(path)})

    if not path.exists():
        raise ToolLoadingError(f"Tool file not found: {file_path}", context={"path": str(path)})

    if not path.is_file():
        raise ToolLoadingError(f"Tool path is not a file: {file_path}", context={"path": str(path)})

    # File extension validation
    if path.suffix != ".py":
        raise ToolLoadingError(f"Invalid file extension: {path.suffix}", context={"path": str(path)})

    SECURITY_ANALYZER.analyze_module_file(path)

    try:
        # Load module spec (fast, no I/O)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ToolLoadingError(
                f"Failed to create module spec from file: {file_path}",
                context={"path": str(path)},
            )

        # Create module (fast, no I/O)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem + "_local_file_module"] = module

        # Execute module code - this is the blocking operation
        await asyncio.to_thread(spec.loader.exec_module, module)

        # Validation is fast, can happen in main thread
        tool = detect_and_validate_tool(module, str(path))
        return tool

    except ToolLoadingError:
        raise
    except Exception as e:
        raise ToolLoadingError(
            f"Failed to load tool from file: {e}",
            context={"path": str(path), "error": str(e)},
        ) from e


def detect_and_validate_tool(module: Any, source: str) -> Any:
    """Detect tool format and validate structure.

    This function determines which tool format the module uses and validates
    it accordingly. It checks for TOOL_SPEC format first, then @tool format.

    Checks for:
    1. TOOL_SPEC module format (returns module)
    2. @tool decorated function format (returns function)

    Args:
        module: The loaded module to inspect
        source: Source identifier (module path or file path) for error messages

    Returns:
        The tool in the appropriate format:
        - For TOOL_SPEC: returns the module itself
        - For @tool: returns the decorated function

    Raises:
        ToolLoadingError: If module doesn't match either supported format

    Examples:
        >>> module = importlib.import_module("tools.strands_tools.calculator")
        >>> tool = detect_and_validate_tool(module, "tools.strands_tools.calculator")
    """
    # Check for TOOL_SPEC module format
    if hasattr(module, "TOOL_SPEC"):
        validate_tool_spec_module(module, source)
        return module

    # Check for @tool decorated function format
    tool_function = detect_tool_decorated_function(module, source)
    if tool_function:
        return tool_function

    # Neither format detected
    raise ToolLoadingError(
        f"Tool does not match any supported format: {source}",
        context={
            "source": source,
            "hint": ("Tool must either have TOOL_SPEC dictionary or @tool decorated function"),
        },
    )


def detect_tool_decorated_function(module: Any, source: str) -> Any | None:
    """Detect and return @tool decorated function from module.

    This function uses multiple strategies to find a tool function:
    1. Look for functions with __tool__ attribute (set by @tool decorator)
    2. Look for function matching module name
       (e.g., 'calculator' in tools.strands_tools.calculator)

    Args:
        module: The imported module to inspect
        source: Source identifier for logging
                (not currently used but kept for consistency)

    Returns:
        The tool function if found, None otherwise

    Examples:
        >>> module = importlib.import_module("tools.strands_tools.calculator")
        >>> func = detect_tool_decorated_function(module, "tools.strands_tools.calculator")
        >>> func.__name__
        'calculator'
    """
    # Strategy 1: Check for __tool__ attribute (added by @tool decorator)
    attrs = []
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name, None)
        if not callable(attr):
            continue
        if (
            hasattr(attr, "__tool__")
            or hasattr(attr, "_tool_metadata")
            or hasattr(attr, "TOOL_SPEC")
            or hasattr(attr, "tool_spec")  # Strands DecoratedFunctionTool / AgentTool
        ):
            # return attr
            attrs.append(attr)
    if len(attrs) > 0:
        return attrs

    # Strategy 2: Look for function matching module name
    # e.g., tools.strands_tools.calculator -> look for 'calculator' function
    module_name = source.split(".")[-1].replace(".py", "")
    if hasattr(module, module_name):
        attr = getattr(module, module_name)
        if callable(attr):
            return attr

    return None


def validate_tool_spec_module(module: Any, source: str) -> None:
    """Validate that a module contains required TOOL_SPEC components.

    A valid TOOL_SPEC module must have:
    1. A TOOL_SPEC dictionary with 'name', 'description', 'inputSchema'
    2. A function with the same name as specified in TOOL_SPEC['name']
    3. The function must be callable

    Args:
        module: The loaded module to validate
        source: Source identifier (module path or file path) for error messages

    Raises:
        ToolLoadingError: If module doesn't meet TOOL_SPEC requirements

    Examples:
        >>> module = importlib.import_module("my_tools.weather")
        >>> validate_tool_spec_module(module, "my_tools.weather")
    """
    tool_spec = module.TOOL_SPEC

    if not isinstance(tool_spec, dict):
        raise ToolLoadingError(
            f"TOOL_SPEC must be a dictionary: {source}",
            context={"source": source, "type": type(tool_spec).__name__},
        )

    # Check for required TOOL_SPEC fields
    required_fields = ["name", "description", "inputSchema"]
    missing_fields = [field for field in required_fields if field not in tool_spec]

    if missing_fields:
        raise ToolLoadingError(
            f"TOOL_SPEC missing required fields: {', '.join(missing_fields)}",
            context={"source": source, "missing_fields": missing_fields},
        )

    # Check for function matching tool name
    tool_name = tool_spec["name"]
    if not hasattr(module, tool_name):
        raise ToolLoadingError(
            f"Tool module missing function '{tool_name}': {source}",
            context={
                "source": source,
                "tool_name": tool_name,
                "hint": f"Add function named '{tool_name}' to module",
            },
        )

    # Verify the function is callable
    tool_function = getattr(module, tool_name)
    if not callable(tool_function):
        raise ToolLoadingError(
            f"Tool '{tool_name}' is not callable: {source}",
            context={"source": source, "tool_name": tool_name},
        )
