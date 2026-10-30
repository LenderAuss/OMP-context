import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("kit_installer",ROOT/"install.py")
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
uspec=importlib.util.spec_from_file_location("kit_uninstall",ROOT/"uninstall.py")
uninstaller=importlib.util.module_from_spec(uspec);uspec.loader.exec_module(uninstaller)


class InstallerTest(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(prefix="kit-installer-test-");self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_platform_selection(self):
        for system,machine,musl,target in [
            ("Darwin","arm64",False,"darwin-arm64"),("Darwin","x86_64",False,"darwin-x64"),
            ("Linux","x86_64",False,"linux-x64"),("Linux","aarch64",False,"linux-arm64"),
            ("Linux","aarch64",True,"linux-musl-arm64"),("Linux","x86_64",True,"linux-musl-x64"),
            ("Windows","AMD64",False,"windows-x64"),("Windows","ARM64",False,"windows-x64")]:
            self.assertEqual(installer.target_platform(system,machine,musl),target)
        with self.assertRaises(ValueError):installer.target_platform("Linux","armv7",False)

    def test_checksum_failure_keeps_previous_binary(self):
        target=self.root/"omp";target.write_bytes(b"working-version")
        bad=self.root/"download";bad.write_bytes(b"unexpected")
        asset={"url":"https://github.com/example/release","sha256":"0"*64}
        with self.assertRaises(ValueError):installer.verified_asset(asset,target,bad)
        self.assertEqual(target.read_bytes(),b"working-version")
        self.assertFalse(list(self.root.glob('.download-*')))

    def test_verified_cached_binary_needs_no_network(self):
        target=self.root/"omp";target.write_bytes(b"pinned")
        asset={"url":"https://github.com/example/release","sha256":installer.sha(target)}
        with patch('urllib.request.urlopen',side_effect=AssertionError("network must not run")):
            self.assertEqual(installer.verified_asset(asset,target),target)

    def test_verified_local_binary_is_installed(self):
        source=self.root/"source";source.write_bytes(b"verified")
        target=self.root/"bin/omp"
        installer.verified_asset({"url":"https://github.com/example/release","sha256":installer.sha(source)},target,source)
        self.assertEqual(target.read_bytes(),b"verified")

    def test_unmanaged_prefix_is_rejected_before_chmod(self):
        prefix=self.root/"important";prefix.mkdir();(prefix/"user-file").write_text("keep")
        args=argparse.Namespace(prefix=prefix,bin_dir=self.root/"bin",permissions="yolo",dry_run=False)
        with patch.object(installer,'private_directory',side_effect=AssertionError("must not touch directory")):
            with self.assertRaisesRegex(ValueError,"not empty"):installer.install(args)
        self.assertEqual((prefix/"user-file").read_text(),"keep")

    def test_shell_path_edit_is_additive_and_idempotent(self):
        (self.root/".bashrc").write_text("# existing settings\n")
        bin_dir=self.root/"path with spaces"
        installer.update_path(bin_dir,home=self.root,windows=False,shell="bash")
        installer.update_path(bin_dir,home=self.root,windows=False,shell="bash")
        text=(self.root/".bashrc").read_text()
        self.assertTrue(text.startswith("# existing settings\n"));self.assertEqual(text.count("omp-context-kit PATH"),1)

    @unittest.skipIf(os.name=='nt',"POSIX launcher executed on POSIX hosts; Windows runner tests cmd separately")
    def test_posix_launcher_preserves_quoted_arguments(self):
        app=self.root/"app with spaces";app.mkdir()
        (app/"launcher.py").write_text("import json,sys;print(json.dumps(sys.argv[1:]))\n")
        script=self.root/"launcher"
        script.write_text(installer.launcher_text(Path(sys.executable),app,self.root))
        result=subprocess.run(['sh',str(script),'a b','$(not-executed);`no`'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),[str(self.root),'a b','$(not-executed);`no`'])

    def test_windows_launcher_handles_spaces_and_rejects_expanding_paths(self):
        text=installer.launcher_text(Path('C:/Apps With Spaces/python.exe'),Path('C:/Apps With Spaces'),Path('C:/Kit'),windows=True)
        self.assertIn('"C:/Apps With Spaces/python.exe"',text.replace('\\','/'))
        self.assertIn('%*',text)
        with self.assertRaises(ValueError):installer.launcher_text(Path('C:/bad%PATH%/python.exe'),Path('C:/app'),Path('C:/Kit'),windows=True)

    @unittest.skipUnless(os.name=='nt',"Native Windows test")
    def test_native_windows_cmd_launcher(self):
        app=self.root/"app with spaces";app.mkdir()
        (app/"launcher.py").write_text("import json,sys;print(json.dumps(sys.argv[1:]))\n")
        script=self.root/"kit.cmd";script.write_text(installer.launcher_text(Path(sys.executable),app,self.root,windows=True))
        result=subprocess.run([str(script),'hello world'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),[str(self.root),'hello world'])

    def test_bootstrap_hashes_match_public_lock(self):
        lock=json.loads((ROOT/'versions.lock.json').read_text())
        shell=(ROOT/'scripts/bootstrap-assets.sh').read_text()
        for name,asset in lock['uv']['assets'].items():
            if name.endswith('.tar.gz'):
                self.assertIn(asset['url'],shell);self.assertIn(asset['sha256'],shell)
        for platform in ['darwin-arm64','darwin-x64','linux-x64','linux-arm64','linux-musl-x64','linux-musl-arm64','windows-x64']:
            name='omp-'+platform+('.exe' if platform.startswith('windows') else '')
            self.assertEqual(len(lock['omp']['assets'][name]['sha256']),64)

    def test_runtime_copy_does_not_include_local_config_or_bytecode(self):
        names=[x.relative_to(ROOT).as_posix() for x in installer.source_files()]
        self.assertFalse(any('__pycache__' in x or '.local.json' in x for x in names))
        self.assertTrue('runtime/python/memory.py' in names)

    def test_uninstall_keeps_accounts_and_memory(self):
        launcher=self.root/'omp-kit';launcher.write_text('# omp-context-kit managed launcher\n')
        memory=self.root/'memory.sqlite3';memory.write_bytes(b'private-memory')
        auth=self.root/'agent.db';auth.write_bytes(b'private-account')
        (self.root/'installation.json').write_text(json.dumps({'launchers':{str(launcher):installer.sha(launcher)}}))
        self.assertEqual(uninstaller.remove_launchers(self.root),1)
        self.assertEqual(memory.read_bytes(),b'private-memory');self.assertEqual(auth.read_bytes(),b'private-account')

    def test_uninstall_rejects_arbitrary_manifest_targets(self):
        file=self.root/'important-document';file.write_text('keep')
        (self.root/'installation.json').write_text(json.dumps({'launchers':{str(file):installer.sha(file)}}))
        with self.assertRaises(SystemExit):uninstaller.remove_launchers(self.root)
        self.assertEqual(file.read_text(),'keep')


if __name__=='__main__':unittest.main()
