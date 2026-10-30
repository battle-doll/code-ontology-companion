"""Neutral actual CLI defaults and truthful post-commit view failure reports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'skills/manage-code-ontology/scripts'
sys.path.insert(0,str(SCRIPTS))
import privacy_guard
from windows_fixture import protect_private_path


class PipelineStageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();protect_private_path(self.root)
        self.repo=self.root/'source';self.repo.mkdir(mode=0o700);self.workspace=self.root/'knowledge'
        (self.repo/'policy.py').write_text('def allowed(active: bool) -> bool:\n    return active\n');(self.repo/'policy.py').chmod(0o600)
        profile=self.root/'profile.json';profile.write_text(json.dumps(privacy_guard.build_profile(['Synthetic Stage Custodian'],[],key=b's'*32)));protect_private_path(profile)
        self.env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','CODE_ONTOLOGY'))}
        self.env.update({privacy_guard.PROFILE_ENV:str(profile),'CODE_ONTOLOGY_PRINCIPAL':'local-owner','CODE_ONTOLOGY_HOME':str(self.root/'registry')})
    def cli(self,args,fail_render=False):
        cache=Path(tempfile.mkdtemp(prefix='stage-cache-',dir=self.root))
        if fail_render:
            runner='import sys;sys.path.insert(0,sys.argv.pop(1));import companion,pipeline_access;pipeline_access._render=lambda *a,**k:(_ for _ in ()).throw(ValueError("Synthetic sensitive detail never serialize"));raise SystemExit(companion.main(sys.argv[1:]))'
            command=['-c',runner,str(SCRIPTS)]
        else:command=[str(SCRIPTS/'companion.py')]
        result=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),*command,*map(str,args)],env=self.env,cwd=self.root,text=True,capture_output=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Synthetic sensitive detail',result.stdout+result.stderr)
        return json.loads(result.stdout)
    def analyze(self,**extra):
        args=['analyze','--repo',self.repo,'--workspace',self.workspace,'--authorized']
        if extra.pop('no_html',False):args.append('--no-html')
        return self.cli(args,**extra)
    def current(self):return json.loads((self.workspace/'state.json').read_text())['currentSnapshot']
    def test_default_analyze_and_refresh_html_are_external_and_pinned(self):
        first=self.analyze();sid=first['snapshotId']
        self.assertEqual(self.current(),sid);self.assertEqual(first['stages']['source']['status'],'COMMITTED')
        self.assertEqual(first['stages']['html']['status'],'READY')
        self.assertTrue((Path(first['html']['outputDirectory'])/'index.html').is_file());self.assertFalse((self.workspace/'html').exists())
        (self.repo/'policy.py').write_text('def allowed(active: bool) -> bool:\n    return not active\n')
        second=self.cli(['refresh','--workspace',self.workspace]);new=second['snapshotId']
        self.assertNotEqual(new,sid);self.assertEqual(self.current(),new)
        self.assertEqual(second['stages']['html']['status'],'READY');self.assertTrue((Path(second['html']['outputDirectory'])/'index.html').is_file())
    def test_no_html_remains_not_requested_and_current_state_matches(self):
        first=self.analyze(no_html=True);self.assertEqual(first['stages']['html']['status'],'NOT_REQUESTED')
        self.assertEqual(self.current(),first['snapshotId']);self.assertFalse((self.root/'knowledge-html').exists())
        second=self.cli(['refresh','--workspace',self.workspace,'--no-html']);self.assertEqual(second['stages']['html']['status'],'NOT_REQUESTED')
        self.assertEqual(self.current(),second['snapshotId'])
    def test_view_failure_after_source_commit_is_partial_with_actual_snapshot(self):
        first=self.analyze(fail_render=True);sid=first['snapshotId']
        self.assertEqual(first['status'],'partial');self.assertEqual(self.current(),sid)
        self.assertEqual(first['stages']['source'],{'status':'COMMITTED','snapshotId':sid})
        self.assertEqual(first['stages']['html']['sourceSnapshotId'],sid);self.assertEqual(first['stages']['html']['status'],'BLOCKED')
        self.assertIn('html',first['remainingScope']);self.assertEqual(first['html']['reason'],'html_generation_failed')
        (self.repo/'policy.py').write_text('def allowed(active: bool) -> bool:\n    return not active\n')
        second=self.cli(['refresh','--workspace',self.workspace],fail_render=True)
        self.assertNotEqual(second['snapshotId'],sid);self.assertEqual(self.current(),second['snapshotId'])
        self.assertEqual(second['stages']['html']['status'],'BLOCKED');self.assertEqual(second['status'],'partial')
    def test_external_parent_symlink_is_rejected_without_waiving_render_boundary(self):
        foreign=self.root/'foreign';foreign.mkdir(mode=0o700)
        (self.root/'knowledge-html').symlink_to(foreign,target_is_directory=True)
        result=self.analyze();self.assertEqual(result['status'],'partial')
        self.assertEqual(result['stages']['html']['status'],'BLOCKED');self.assertEqual(self.current(),result['snapshotId'])
        self.assertEqual(list(foreign.iterdir()),[])


    def test_no_change_refresh_renders_fresh_leaf_without_reusing_previous(self):
        import hashlib
        first=self.analyze();sid=first['snapshotId'];directory=Path(first['html']['outputDirectory'])
        previous={str(path.relative_to(directory)):hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.rglob('*') if path.is_file()}
        second=self.cli(['refresh','--workspace',self.workspace]);self.assertEqual(second['snapshotId'],sid)
        self.assertEqual(second['status'],'no_change');self.assertEqual(second['stages']['source']['status'],'CURRENT')
        self.assertEqual(second['stages']['html']['status'],'READY');self.assertEqual(self.current(),sid)
        following=Path(second['html']['outputDirectory']);self.assertNotEqual(following,directory)
        self.assertEqual(directory.parent,following.parent);self.assertEqual(directory.parent.name,sid)
        self.assertTrue((following/'index.html').is_file())
        self.assertEqual(previous,{str(path.relative_to(directory)):hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.rglob('*') if path.is_file()})
        third=self.cli(['refresh','--workspace',self.workspace,'--no-html'])
        self.assertEqual(third['snapshotId'],sid);self.assertEqual(third['stages']['source']['status'],'CURRENT')
        self.assertEqual(third['stages']['html']['status'],'NOT_REQUESTED');self.assertEqual(self.current(),sid)

if __name__=='__main__':unittest.main()
