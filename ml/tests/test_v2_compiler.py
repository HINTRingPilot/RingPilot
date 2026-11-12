"""Compiler command parsing and real argv round trips, without model training."""
import os
import errno
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_export_c as ex


class CompilerCommandTests(unittest.TestCase):
    def test_quoted_existing_executable_runs(self):
        with patch.dict(os.environ, {"RINGPILOT_CC": '"' + sys.executable + '"'}):
            command = ex.find_cc()
            self.assertEqual(command, [sys.executable])
            result = subprocess.run([*command, "--version"], check=True, capture_output=True, text=True)
            self.assertIn("Python", result.stdout)

    def test_embedded_quotes_and_backslashes(self):
        arguments = ["gcc", "-DMSG=hello world", "C:\\include path\\", 'say"hello']
        command = subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
        with patch.dict(os.environ, {"RINGPILOT_CC": command}):
            self.assertEqual(ex.find_cc(), arguments)

    def test_invalid_or_empty_command_rejected(self):
        for command in ("", "   ", '""', "''", '"" -O2', '"unterminated compiler'):
            with self.subTest(command=command), patch.dict(os.environ, {"RINGPILOT_CC": command}):
                with self.assertRaises(ValueError):
                    ex.find_cc()

    def test_default_compiler_order(self):
        with patch.dict(os.environ):
            os.environ.pop("RINGPILOT_CC", None)
            with patch.object(ex.shutil, "which", side_effect=lambda name: "gcc-path" if name == "gcc" else None):
                self.assertEqual(ex.find_cc(), ["gcc-path"])

    def test_optional_path_probe_error_still_parses_command(self):
        command = "gcc -DMSG=" + "a" * 300
        with patch.dict(os.environ, {"RINGPILOT_CC": command}), \
                patch.object(ex.Path, "is_file", side_effect=OSError(errno.ENAMETOOLONG, "name too long")):
            self.assertEqual(ex.find_cc(), ["gcc", "-DMSG=" + "a" * 300])

    @unittest.skipUnless(shutil.which("gcc"), "gcc needed for the real executable argv probe")
    def test_executable_in_space_directory_with_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "compiler tools"
            directory.mkdir()
            source = directory / "argv.c"
            source.write_text('#include <stdio.h>\nint main(int n,char **v){for(int i=1;i<n;i++)puts(v[i]);return 0;}\n', encoding="utf-8")
            executable = directory / ("argv.exe" if os.name == "nt" else "argv")
            subprocess.run([shutil.which("gcc"), str(source), "-o", str(executable)], check=True, capture_output=True)
            for env_command in (str(executable), '"' + str(executable) + '"'):
                with patch.dict(os.environ, {"RINGPILOT_CC": env_command}):
                    self.assertEqual(ex.find_cc(), [str(executable)])
                    subprocess.run(ex.find_cc(), check=True, capture_output=True)
            args = [str(executable), "-DMSG=hello world", "C:\\include path\\", 'say"hello']
            env_command = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
            with patch.dict(os.environ, {"RINGPILOT_CC": env_command}):
                result = subprocess.run(ex.find_cc(), check=True, capture_output=True, text=True)
                self.assertEqual(result.stdout.splitlines(), args[1:])


if __name__ == "__main__":
    unittest.main()
