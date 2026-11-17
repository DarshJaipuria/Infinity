import fnmatch
import glob
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any
from classes import config


coding_instructions = """**START BY SETTING A BASE_DIR USING `set_base_dir` first**

## Objective
- Understand, search, validate, and make precise changes to source code or notebook cells inside the active base directory set by `set_base_dir`.
- Do not use these tools for unrelated file or directory housekeeping.
- Treat relative paths as workspace-relative paths and reject anything that attempts to escape the configured base directory.
- Prefer precise, minimal edits and reads over broad rewrites.

## Safety Rules
- Validate every path before reading, creating, writing, or patching files.
- Reject traversal attempts such as `..` or other path escapes before execution.
- Ensure parent directories exist before creating files or notebooks.
- For notebook cell edits, target the cell by `cell_id` and keep updates narrow and explicit.
- Use `check_syntax` to check a file with the parser/compiler for its language before running it.

## Reliability and Performance
- For full file / cell replacements, delete the file / cell  first and  then recreate the file / cell with new data.
- Keep outputs concise but informative: describe the action, target path, and final result.
- Prefer targeted reads and replacements over full-file rewrites unless required.
- Surface the real error clearly when a tool fails.

## Execution Pattern
1. Validate the base directory is set.
2. Resolve the requested path relative to the base directory.
3. Perform the file or notebook action.
4. Use `check_syntax` for syntax diagnostics and `run_script` when execution or tests are needed; report their results.
5. Confirm the result clearly and briefly.

`run_script` launches scripts under the configured base directory using their native runtime when available (.py, .js, .ps1, .bat/.cmd, or .sh). Supply an interpreter executable for other script formats. Scripts are not sandboxed and may modify files or use network resources, so run only relevant project scripts."""

BASE_DIR = None


#HELPER FUNCTIONS

def _resolve_path(path):
    if path is None:
        return None
    if not BASE_DIR:
        return None
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(BASE_DIR, path))


def _load_notebook(notebook_path):
    with open(notebook_path, "r", encoding="utf-8") as f:
        notebook = json.load(f)

    if not isinstance(notebook, dict):
        raise ValueError(f"Notebook file is not a valid JSON object: {notebook_path}")

    cells = notebook.setdefault("cells", [])
    if not isinstance(cells, list):
        raise ValueError(f"Notebook cells must be a list: {notebook_path}")

    return notebook, cells


def _save_notebook(notebook_path, notebook):
    with open(notebook_path, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _get_cell(cells, cell_id):
    for cell in cells:
        if cell.get("id") == cell_id:
            return cell
    raise KeyError(f"Cell ID not found: {cell_id}")


def _truncate_notebook_line(line, limit=None):
    limit = int(config.max_chrs if limit is None else limit)
    marker = "[truncated]..."
    line = str(line).rstrip("\r\n")
    if len(line) <= limit:
        return line
    return line[: max(0, limit - len(marker))] + marker


def _notebook_lines(source, start_line=1, end_line=None, line_limit=None, max_lines=None):
    if start_line < 1:
        raise ValueError("start_line must be greater than or equal to 1")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must be greater than or equal to start_line")

    source_lines = source if isinstance(source, list) else str(source).splitlines()
    remaining_lines = source_lines[start_line - 1 :]
    selected_lines = remaining_lines[: end_line - start_line + 1 if end_line is not None else None]
    was_line_limited = max_lines is not None and len(remaining_lines) > max_lines
    if max_lines is not None:
        selected_lines = selected_lines[:max_lines]

    truncated_lines = [_truncate_notebook_line(line, line_limit) for line in selected_lines]
    if was_line_limited:
        truncated_lines.append("[truncated]...")
    return truncated_lines


def _format_notebook_result(value):
    formatted = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return "\n".join(_truncate_notebook_line(line) for line in formatted.splitlines())


#MAIN FUNCTIONS

def set_base_dir(path):
    global BASE_DIR
    BASE_DIR = os.path.abspath(path)
    os.makedirs(BASE_DIR, exist_ok=True)
    return {"role": "tool", "name": "set_base_dir", "content": str(BASE_DIR)}


def create_directory(dirPath):
    resolved = _resolve_path(dirPath)
    if not resolved:
        return {"role": "tool", "name": "create_directory", "content": "BASE_DIR not set! set_base_dir first."}
    result = os.makedirs(resolved, exist_ok=True)
    return {"role": "tool", "name": "create_directory", "content": str(result)}


def create_file(filePath, content):
    resolved_path = _resolve_path(filePath)
    if not resolved_path:
        return {"role": "tool", "name": "create_file", "content": "BASE_DIR not set! set_base_dir first."}
    directory = os.path.dirname(resolved_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"role": "tool", "name": "create_file", "content": str(resolved_path)}


def list_dir(path):
    resolved = _resolve_path(path)
    if not resolved:
        return {"role": "tool", "name": "list_dir", "content": "BASE_DIR not set! set_base_dir first."}
    result = os.listdir(resolved)
    return {"role": "tool", "name": "list_dir", "content": str(result)}


def read_file(filePath, startLine, endLine):
    resolved_path = _resolve_path(filePath)
    if not resolved_path:
        return {"role": "tool", "name": "read_file", "content": "BASE_DIR not set! set_base_dir first."}
    with open(resolved_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if endLine is None:
        endLine = len(lines)
    result = "".join(lines[startLine - 1 : endLine])
    return {"role": "tool", "name": "read_file", "content": str(result)}


def file_search(query, maxResults=None):
    resolved_query = _resolve_path(query)
    if not resolved_query:
        return {"role": "tool", "name": "file_search", "content": "BASE_DIR not set! set_base_dir first."}
    matches = glob.glob(resolved_query, recursive=True)
    if maxResults is not None:
        matches = matches[:maxResults]
    return {"role": "tool", "name": "file_search", "content": str(matches)}


def grep_search(query, isRegexp, includePattern=None, maxResults=None, includeIgnoredFiles=False):
    if includePattern is None:
        includePattern = "**/*"

    resolved_pattern = _resolve_path(includePattern)
    if not resolved_pattern:
        return {"role": "tool", "name": "grep_search", "content": "BASE_DIR not set! set_base_dir first."}
    pattern = pathlib.Path(resolved_pattern)
    if pattern.is_absolute():
        search_root = pattern.parent
        pattern_name = pattern.name
    else:
        search_root = pathlib.Path(BASE_DIR)
        pattern_name = str(pattern)

    files = []
    if "*" in pattern_name or "?" in pattern_name or "[" in pattern_name:
        files = glob.glob(str(pathlib.Path(search_root) / pattern_name), recursive=True)
    else:
        if os.path.isdir(resolved_pattern):
            files = [str(p) for p in pathlib.Path(resolved_pattern).rglob("*") if p.is_file()]
        else:
            files = [resolved_pattern] if os.path.isfile(resolved_pattern) else []

    matches = []
    regex = re.compile(query) if isRegexp else None

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        if isRegexp:
            if regex.search(text):
                matches.append(file_path)
        else:
            if query in text:
                matches.append(file_path)

    if maxResults is not None:
        matches = matches[:maxResults]

    return {"role": "tool", "name": "grep_search", "content": str(matches)}


def replace_string_in_file(filePath, oldString, newString):
    resolved_path = _resolve_path(filePath)
    if not resolved_path:
        return {"role": "tool", "name": "replace_string_in_file", "content": "BASE_DIR not set! set_base_dir first."}
    with open(resolved_path, "r", encoding="utf-8") as f:
        original = f.read()
    if oldString not in original:
        raise ValueError(f"oldString not found in file: {resolved_path}")
    updated = original.replace(oldString, newString)
    with open(resolved_path, "w", encoding="utf-8") as f:
        f.write(updated)
    return {"role": "tool", "name": "replace_string_in_file", "content": str(resolved_path)}


def multi_replace_string_in_file(explanation, replacements):
    resolved = _resolve_path(".")
    if not resolved:
        return {"role": "tool", "name": "multi_replace_string_in_file", "content": "BASE_DIR not set! set_base_dir first."}
    results = []
    for replacement in replacements:
        file_path = _resolve_path(replacement["filePath"])
        old_string = replacement["oldString"]
        new_string = replacement["newString"]
        results.append(replace_string_in_file(file_path, old_string, new_string))
    return {"role": "tool", "name": "multi_replace_string_in_file", "content": str(results)}


def create_new_jupyter_notebook(path):
    resolved_path = _resolve_path(path)
    if not resolved_path:
        return {"role": "tool", "name": "create_new_jupyter_notebook", "content": "BASE_DIR not set! set_base_dir first."}
    directory = os.path.dirname(resolved_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(resolved_path, "w") as f:
        f.write("")
    return {"role": "tool", "name": "create_new_jupyter_notebook", "content": str(resolved_path)}


def check_syntax(filePath, language):
    if not BASE_DIR:
        return {"role": "tool", "name": "check_syntax", "content": "BASE_DIR not set! set_base_dir first."}
    if not isinstance(filePath, str) or not filePath:
        raise ValueError("filePath must be a non-empty relative path.")
    if os.path.isabs(filePath):
        raise ValueError("filePath must be relative to the configured base directory.")
    if not isinstance(language, str) or not language.strip():
        raise ValueError("language must be a non-empty string.")

    base_dir = os.path.realpath(BASE_DIR)
    resolved_path = os.path.realpath(os.path.join(base_dir, filePath))
    try:
        is_within_base = os.path.commonpath([base_dir, resolved_path]) == base_dir
    except ValueError:
        is_within_base = False
    if not is_within_base:
        raise ValueError(f"File path escapes the configured base directory: {filePath}")
    if not os.path.isfile(resolved_path):
        raise FileNotFoundError(f"File not found: {filePath}")

    language_name = language.strip().lower()
    language_aliases = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "ps1": "powershell",
        "sh": "bash",
        "shell": "bash",
    }
    language_name = language_aliases.get(language_name, language_name)
    output = ""
    exit_code = 0
    timed_out = False

    if language_name == "python":
        try:
            with open(resolved_path, "r", encoding="utf-8") as source_file:
                compile(source_file.read(), resolved_path, "exec")
        except (SyntaxError, ValueError) as exc:
            exit_code = 1
            output = str(exc)
    elif language_name == "json":
        try:
            with open(resolved_path, "r", encoding="utf-8") as source_file:
                json.load(source_file)
        except json.JSONDecodeError as exc:
            exit_code = 1
            output = f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
    else:
        if language_name == "javascript":
            runtime = shutil.which("node")
            command = [runtime, "--check", resolved_path] if runtime else None
            missing_runtime = "Node.js is required for JavaScript syntax checking but was not found on PATH."
        elif language_name == "typescript":
            runtime = shutil.which("tsc")
            command = [
                runtime, "--noEmit", "--pretty", "false", "--skipLibCheck",
                "--noResolve", "--target", "ESNext", resolved_path,
            ] if runtime else None
            missing_runtime = "TypeScript compiler (tsc) is required but was not found on PATH."
        elif language_name == "powershell":
            runtime = shutil.which("pwsh") or shutil.which("powershell")
            if runtime:
                encoded_path = base64.b64encode(resolved_path.encode("utf-8")).decode("ascii")
                parser_script = (
                    "$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
                    + encoded_path
                    + "')); $tokens=$null; $parseErrors=$null; "
                    "[void][System.Management.Automation.Language.Parser]::ParseFile("
                    "$path,[ref]$tokens,[ref]$parseErrors); "
                    "$parseErrors | ForEach-Object { Write-Output $_.Message }; "
                    "if ($parseErrors.Count -gt 0) { exit 1 }"
                )
                command = [runtime, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"]
            else:
                command = None
            missing_runtime = "PowerShell is required for PowerShell syntax checking but was not found on PATH."
        elif language_name == "bash":
            runtime = shutil.which("bash") or shutil.which("sh")
            command = [runtime, "-n", resolved_path] if runtime else None
            missing_runtime = "Bash or sh is required for shell syntax checking but was not found on PATH."
        else:
            raise ValueError(
                "Unsupported language. Supported languages: Python, JavaScript, TypeScript, "
                "PowerShell, Bash, and JSON."
            )

        if command is None:
            raise FileNotFoundError(missing_runtime)
        try:
            process = subprocess.run(
                command,
                input=parser_script if language_name == "powershell" else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            exit_code = process.returncode
            output = (process.stdout + process.stderr).strip()
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            output = (stdout + stderr).strip()

    output_limit = max(0, int(config.max_chrs))
    result = {
        "file": os.path.relpath(resolved_path, base_dir),
        "language": language_name,
        "valid": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "output": output[:output_limit],
        "output_truncated": len(output) > output_limit,
    }
    return {"role": "tool", "name": "check_syntax", "content": json.dumps(result, ensure_ascii=False)}


def run_script(scriptPath, arguments=None, timeout=30, interpreter=None):
    if not BASE_DIR:
        return {"role": "tool", "name": "run_script", "content": "BASE_DIR not set! set_base_dir first."}
    if not isinstance(scriptPath, str) or not scriptPath:
        raise ValueError("scriptPath must be a non-empty relative path.")
    if os.path.isabs(scriptPath):
        raise ValueError("scriptPath must be relative to the configured base directory.")
    if arguments is None:
        arguments = []
    if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
        raise ValueError("arguments must be a list of strings.")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("timeout must be an integer between 1 and 300 seconds.")

    base_dir = os.path.realpath(BASE_DIR)
    script_path = os.path.realpath(os.path.join(base_dir, scriptPath))
    try:
        is_within_base = os.path.commonpath([base_dir, script_path]) == base_dir
    except ValueError:
        is_within_base = False
    if not is_within_base:
        raise ValueError(f"Script path escapes the configured base directory: {scriptPath}")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Script not found: {scriptPath}")

    extension = os.path.splitext(script_path)[1].lower()
    runtime_args = []
    batch_command = None
    if interpreter is not None:
        if not isinstance(interpreter, str) or not interpreter:
            raise ValueError("interpreter must be a non-empty executable name or path.")
        runtime = shutil.which(interpreter)
        if runtime is None:
            raise FileNotFoundError(f"Script interpreter not found: {interpreter}")
        runtime_name = os.path.basename(runtime).lower()
        if extension in (".bat", ".cmd") and runtime_name in ("cmd", "cmd.exe"):
            batch_command = _batch_command(runtime, script_path, arguments)
        elif extension == ".ps1" and runtime_name in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
            runtime_args = ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", script_path, *arguments]
        else:
            runtime_args = [script_path, *arguments]
    elif extension == ".py":
        runtime = sys.executable
        runtime_args = [script_path, *arguments]
    elif extension in (".js", ".cjs", ".mjs"):
        runtime = shutil.which("node")
        if runtime is None:
            raise FileNotFoundError("Node.js is required to run this script but was not found on PATH.")
        runtime_args = [script_path, *arguments]
    elif extension == ".ps1":
        runtime = shutil.which("pwsh") or shutil.which("powershell")
        if runtime is None:
            raise FileNotFoundError("PowerShell is required to run this script but was not found on PATH.")
        runtime_args = ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", script_path, *arguments]
    elif extension in (".bat", ".cmd"):
        runtime = shutil.which("cmd.exe") or shutil.which("cmd")
        if runtime is None:
            raise FileNotFoundError("Command Prompt is required to run this script but was not found on PATH.")
        batch_command = _batch_command(runtime, script_path, arguments)
    elif extension == ".sh":
        runtime = shutil.which("bash") or shutil.which("sh")
        if runtime is None:
            raise FileNotFoundError("Bash or sh is required to run this script but was not found on PATH.")
        runtime_args = [script_path, *arguments]
    else:
        raise ValueError(
            f"Cannot determine an interpreter for {extension or 'this file'}; provide interpreter explicitly."
        )

    try:
        process = subprocess.run(
            batch_command if batch_command is not None else [runtime, *runtime_args],
            cwd=base_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        exit_code = process.returncode
        timed_out = False
        stdout = process.stdout
        stderr = process.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

    output_limit = max(0, int(config.max_chrs))
    stdout_truncated = len(stdout) > output_limit
    stderr_truncated = len(stderr) > output_limit
    result = {
        "script": os.path.relpath(script_path, base_dir),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout[:output_limit],
        "stderr": stderr[:output_limit],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    return {"role": "tool", "name": "run_script", "content": json.dumps(result, ensure_ascii=False)}


def _batch_command(runtime, script_path, arguments):
    cmd_metacharacters = '&|<>^()%!"'
    if any(character in cmd_metacharacters for character in script_path):
        raise ValueError("Batch script paths cannot contain Command Prompt metacharacters.")
    if any(any(character in cmd_metacharacters for character in arg) for arg in arguments):
        raise ValueError("Batch script arguments cannot contain Command Prompt metacharacters.")
    return (
        f"{subprocess.list2cmdline([runtime])} /d /c "
        f"{subprocess.list2cmdline([script_path, *arguments])}"
    )


def create_cell(notebook_path, cell_id=None, cell_type="code", source="", metadata=None, execution_count=None, outputs=None):
    resolved_path = _resolve_path(notebook_path)
    if not resolved_path:
        return {"role": "tool", "name": "add_cell", "content": "BASE_DIR not set! set_base_dir first."}
    notebook, cells = _load_notebook(resolved_path)

    if cell_id is None:
        cell_id = uuid.uuid4().hex

    new_cell = {
        "cell_type": cell_type,
        "id": cell_id,
        "metadata": metadata.copy() if isinstance(metadata, dict) else {},
        "source": source.splitlines(keepends=True) if isinstance(source, str) else (source or []),
    }

    if cell_type == "code":
        new_cell["execution_count"] = execution_count
        new_cell["outputs"] = outputs if outputs is not None else []

    cells.append(new_cell)
    _save_notebook(resolved_path, notebook)
    return {"role": "tool", "name": "add_cell", "content": str(cell_id)}


def list_cells(notebook_path, limit=50):
    resolved_path = _resolve_path(notebook_path)
    if not resolved_path:
        return {"role": "tool", "name": "list_cells", "content": "BASE_DIR not set! set_base_dir first."}

    _, cells = _load_notebook(resolved_path)
    cell_summaries = []
    for index, cell in enumerate(cells):
        source_lines = _notebook_lines(
            cell.get("source", []),
            1,
            None,
            line_limit=500,
            max_lines=limit,
        )
        cell_summaries.append({
            "index": index,
            "id": str(cell.get("id", "")),
            "cell_type": str(cell.get("cell_type", "")),
            "source": source_lines,
        })

    return {"role": "tool", "name": "list_cells", "content": _format_notebook_result(cell_summaries)}


def read_cell(notebook_path, cell_id, start_line=1, end_line=None):
    resolved_path = _resolve_path(notebook_path)
    if not resolved_path:
        return {"role": "tool", "name": "read_cell", "content": "BASE_DIR not set! set_base_dir first."}
    _, cells = _load_notebook(resolved_path)
    result = _get_cell(cells, cell_id).copy()
    result["source"] = _notebook_lines(result.get("source", []), start_line, end_line)
    return {"role": "tool", "name": "read_cell", "content": _format_notebook_result(result)}


def delete_cell(notebook_path, cell_id):
    resolved_path = _resolve_path(notebook_path)
    if not resolved_path:
        return {"role": "tool", "name": "delete_cell", "content": "BASE_DIR not set! set_base_dir first."}
    notebook, cells = _load_notebook(resolved_path)
    for index, cell in enumerate(cells):
        if cell.get("id") == cell_id:
            del cells[index]
            _save_notebook(resolved_path, notebook)
            return {"role": "tool", "name": "delete_cell", "content": "Cell deleted successfully."}
    return {"role": "tool", "name": "delete_cell", "content": "Cell could not be deleted: cell not found."}


def patch_cell(notebook_path, cell_id, old_line, new_line):
    resolved_path = _resolve_path(notebook_path)
    if not resolved_path:
        return {"role": "tool", "name": "patch_cell", "content": "BASE_DIR not set! set_base_dir first."}
    notebook, cells = _load_notebook(resolved_path)
    cell = _get_cell(cells, cell_id)

    if "source" not in cell:
        raise KeyError(f"Cell does not have a source field: {cell_id}")

    source = cell["source"]
    if isinstance(source, list):
        source_text = "".join(source)
    else:
        source_text = str(source)

    updated_text = source_text.replace(old_line, new_line)
    cell["source"] = updated_text.splitlines(keepends=True)

    _save_notebook(resolved_path, notebook)
    return {"role": "tool", "name": "patch_cell", "content": str(cell)}


coding_tool_map = {
    "set_base_dir": set_base_dir,
    "create_directory": create_directory,
    "create_file": create_file,
    "list_dir": list_dir,
    "read_file": read_file,
    "file_search": file_search,
    "grep_search": grep_search,
    "replace_string_in_file": replace_string_in_file,
    "multi_replace_string_in_file": multi_replace_string_in_file,
    "create_new_jupyter_notebook": create_new_jupyter_notebook,
    "check_syntax": check_syntax,
    "run_script": run_script,
    "create_cell": create_cell,
    "list_cells": list_cells,
    "read_cell": read_cell,
    "delete_cell": delete_cell,
    "patch_cell": patch_cell,
}