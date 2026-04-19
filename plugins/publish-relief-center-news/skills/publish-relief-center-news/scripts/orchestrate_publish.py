#!/usr/bin/env python3
"""
Orchestrate article publishing safely across Windows/Linux/macOS.

This helper script handles OS-aware temp file creation and JSON piping,
avoiding shell quoting issues that break on apostrophes in article text.

Usage:
    python orchestrate_publish.py <skill_dir> <article_json_string> [article_index]

Example:
    python orchestrate_publish.py /path/to/skill '{"title_en": "...", ...}' 2
"""

import sys
import os
import json
import tempfile
import subprocess
from pathlib import Path


def detect_os():
    """Return 'windows', 'linux', or 'darwin' (macOS)."""
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'darwin'
    else:
        return 'linux'


def publish_article(skill_dir, article_json_str, article_index=None):
    """
    Safely publish one article via temp file + redirection.

    Args:
        skill_dir: Path to skill directory containing scripts/
        article_json_str: JSON string (field dict without article_index)
        article_index: Optional index for temp file naming

    Returns:
        dict: Parsed JSON response from publish_blog_post.py
              or {"error": "...", "stderr": "..."} on failure
    """

    os_type = detect_os()
    skill_path = Path(skill_dir)
    publish_script = skill_path / 'scripts' / 'publish_blog_post.py'

    if not publish_script.is_file():
        return {
            "error": "publish_blog_post.py not found",
            "path": str(publish_script)
        }

    # Parse the input JSON to validate it
    try:
        article_dict = json.loads(article_json_str)
    except json.JSONDecodeError as e:
        return {
            "error": "Invalid JSON in article payload",
            "details": str(e)
        }

    # Get OS-appropriate temp directory
    temp_dir = Path(tempfile.gettempdir())

    # Create temp file with appropriate naming
    if article_index is not None:
        temp_filename = f'rc_article_{article_index}.json'
    else:
        temp_filename = f'rc_article_{os.getpid()}.json'

    temp_file = temp_dir / temp_filename

    try:
        # Write JSON to temp file (handles UTF-8 + Arabic properly)
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(article_dict, f, ensure_ascii=False)

        # Pipe from temp file to publish script
        with open(temp_file, 'r', encoding='utf-8') as stdin_file:
            result = subprocess.run(
                [sys.executable, str(publish_script)],
                stdin=stdin_file,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )

        # Parse result
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {
                    "error": "publish_blog_post.py returned non-JSON",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
        else:
            return {
                "error": "publish_blog_post.py failed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

    finally:
        # Clean up temp file
        try:
            temp_file.unlink()
        except FileNotFoundError:
            pass


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        print(
            "Usage: python orchestrate_publish.py <skill_dir> <article_json> [article_index]",
            file=sys.stderr
        )
        sys.exit(1)

    skill_dir = sys.argv[1]
    article_json = sys.argv[2]
    article_index = sys.argv[3] if len(sys.argv) > 3 else None

    # Ensure UTF-8 output on Windows
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    result = publish_article(skill_dir, article_json, article_index)
    print(json.dumps(result, ensure_ascii=False))

    # Exit with status based on result
    if 'error' in result:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
