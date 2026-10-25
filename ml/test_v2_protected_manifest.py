"""보호 대상 manifest 도구 점검(임시 폴더만 사용, 실제 데이터는 읽지 않는다)."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import v2_protected_manifest as pm

PATTERNS = ("data/**/*", "code.py")


def make_tree(root):
    root = Path(root)
    (root / "data/sub").mkdir(parents=True)
    (root / "data/a.csv").write_bytes(b"t,x\r\n0,1\r\n10,2\r\n")
    (root / "data/sub/b.json").write_bytes(b'{"k": 1}\n')
    (root / "data/arr.npz").write_bytes(b"PK\x03\x04\x00\x01\r\n\x02raw")
    (root / "data/SESSION_DONE").write_bytes(b"")
    (root / "code.py").write_bytes(b"print(1)\n")
    (root / "outside.txt").write_bytes(b"not protected\n")
    return root


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pm.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class HashRuleTests(unittest.TestCase):
    def test_crlf_and_lf_text_hash_equal_and_binary_uses_raw_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "x.csv").write_bytes(b"a,b\r\n1,2\r\n")
            (d / "y.csv").write_bytes(b"a,b\n1,2\n")
            (d / "z.csv").write_bytes(b"a,b\n1,3\n")
            hx = pm.hash_file(d / "x.csv", pm.RULE_TEXT)
            self.assertEqual(hx, pm.hash_file(d / "y.csv", pm.RULE_TEXT))
            self.assertNotEqual(hx, pm.hash_file(d / "z.csv", pm.RULE_TEXT))
            self.assertEqual(hx, hashlib.sha256(b"a,b\n1,2\n").hexdigest())
            # 바이너리는 줄바꿈을 건드리지 않는다: CRLF가 든 같은 바이트의 해시는 원시 바이트 해시다
            raw = b"\x00\x01\r\n\x02"
            (d / "a.npz").write_bytes(raw)
            (d / "b.npz").write_bytes(raw.replace(b"\r\n", b"\n"))
            ha = pm.hash_file(d / "a.npz", pm.RULE_BINARY)
            self.assertEqual(ha, hashlib.sha256(raw).hexdigest())
            self.assertNotEqual(ha, pm.hash_file(d / "b.npz", pm.RULE_BINARY))

    def test_rule_selection(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, body, rule in [("a.csv", b"1\n", pm.RULE_TEXT), ("a.NPZ", b"x", pm.RULE_BINARY),
                                     ("a.mp4", b"x", pm.RULE_BINARY), ("a.ps1", b"x", pm.RULE_TEXT),
                                     ("NOEXT", b"", pm.RULE_TEXT), ("NOEXT2", b"ab\0cd", pm.RULE_BINARY),
                                     ("NOEXT3", b"plain text\n", pm.RULE_TEXT)]:
                (d / name).write_bytes(body)
                self.assertEqual(pm.choose_rule(d / name), rule, name)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_tree(self._tmp.name)

    def manifest(self):
        return pm.build_manifest(self.root, PATTERNS, with_git=False)

    def test_manifest_lists_only_protected_files_with_rules(self):
        m = self.manifest()
        paths = {f["path"]: f for f in m["files"]}
        self.assertEqual(set(paths), {"data/a.csv", "data/sub/b.json", "data/arr.npz", "data/SESSION_DONE", "code.py"})
        self.assertEqual(m["file_count"], 5)
        self.assertEqual(paths["data/a.csv"]["rule"], pm.RULE_TEXT)
        self.assertEqual(paths["data/arr.npz"]["rule"], pm.RULE_BINARY)
        self.assertEqual(paths["data/a.csv"]["sha256"], hashlib.sha256(b"t,x\n0,1\n10,2\n").hexdigest())
        self.assertEqual(paths["data/arr.npz"]["sha256"], hashlib.sha256((self.root / "data/arr.npz").read_bytes()).hexdigest())
        self.assertEqual([f["path"] for f in m["files"]], sorted(paths))

    def test_no_difference_and_line_ending_change_is_not_a_difference_for_text(self):
        m = self.manifest()
        self.assertEqual(pm.compare(self.root, m), {"added": [], "removed": [], "changed": []})
        (self.root / "data/a.csv").write_bytes(b"t,x\n0,1\n10,2\n")  # CRLF -> LF
        self.assertEqual(pm.compare(self.root, m)["changed"], [])

    def test_binary_line_ending_change_is_detected(self):
        m = self.manifest()
        (self.root / "data/arr.npz").write_bytes(b"PK\x03\x04\x00\x01\n\x02raw")
        self.assertEqual(pm.compare(self.root, m)["changed"], ["data/arr.npz"])

    def test_added_removed_changed(self):
        m = self.manifest()
        (self.root / "data/new.csv").write_bytes(b"1\n")
        (self.root / "data/sub/b.json").unlink()
        (self.root / "code.py").write_bytes(b"print(2)\n")
        (self.root / "outside.txt").write_bytes(b"changed but unprotected\n")
        diff = pm.compare(self.root, m)
        self.assertEqual(diff, {"added": ["data/new.csv"], "removed": ["data/sub/b.json"], "changed": ["code.py"]})

    def test_creating_manifest_does_not_modify_protected_files(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        out = self.root / "out/manifest.json"
        code, _, _ = run_main("--root", str(self.root), "create", "--out", str(out),
                              "--pattern", "data/**/*", "--pattern", "code.py")
        self.assertEqual(code, 0)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and p != out}
        self.assertEqual(before, after)
        self.assertNotIn(b"\r", out.read_bytes())  # LF로 저장


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_tree(self._tmp.name)
        self.out = self.root / "out/manifest.json"
        self.create_args = ("--root", str(self.root), "create", "--out", str(self.out),
                            "--pattern", "data/**/*", "--pattern", "code.py")

    def test_refuse_to_overwrite(self):
        self.assertEqual(run_main(*self.create_args)[0], 0)
        first = self.out.read_bytes()
        (self.root / "code.py").write_bytes(b"print(3)\n")
        code, _, err = run_main(*self.create_args)
        self.assertEqual(code, 2)
        self.assertIn("덮어쓰지", err)
        self.assertEqual(self.out.read_bytes(), first)

    def test_check_exit_code(self):
        run_main(*self.create_args)
        check = ("--root", str(self.root), "check", "--manifest", str(self.out))
        code, text, _ = run_main(*check)
        self.assertEqual(code, 0)
        self.assertIn("차이 없음", text)
        (self.root / "data/a.csv").write_bytes(b"t,x\n0,9\n")
        (self.root / "data/extra.csv").write_bytes(b"1\n")
        (self.root / "data/arr.npz").unlink()
        code, text, _ = run_main(*check)
        self.assertEqual(code, 1)
        self.assertIn("changed: data/a.csv", text)
        self.assertIn("added: data/extra.csv", text)
        self.assertIn("removed: data/arr.npz", text)

    def test_manifest_json_roundtrip_has_hash_note(self):
        run_main(*self.create_args)
        m = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertIn("CRLF", m["hash_note"])
        self.assertEqual(m["file_count"], len(m["files"]))


if __name__ == "__main__":
    unittest.main()
