"""Lightweight tests; ordinary discovery never launches an OpenFOAM run."""
from pathlib import Path
import json,tempfile,unittest,sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from pipeline.forward_step.spec import ForwardStep3DSpec as Spec
from pipeline.forward_step.build import build,mesh_dictionary,TEMPLATE
from pipeline.forward_step.diagnostics import field,relative_errors,transient_balance,Layout
from pipeline.forward_step.initialize import initial_state

class Specifications(unittest.TestCase):
    def test_defaults(self):
        s=Spec();self.assertEqual(s.cells,129024);self.assertEqual(s.splits,(48,16));self.assertEqual(s.velocity,3)
    def test_json_roundtrip(self):self.assertEqual(Spec.from_dict(json.loads(json.dumps(Spec().to_dict()))),Spec())
    def test_yaml_config(self):
        root=Path(__file__).resolve().parents[2]
        self.assertEqual(Spec.load(root/'configs/forward_step/case_A_reference.yaml'),Spec())
    def test_geometry_variation(self):self.assertEqual(Spec(step_height=.15).cells,135168)
    def test_mach_temperature(self):self.assertEqual(initial_state(Spec(mach=2.5,temperature=4))['U'],(5,0,0))
    def test_geometry_bounds(self):
        for kwargs in [dict(step_height=1),dict(step_x=3),dict(length=0),dict(span=-1)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):Spec(**kwargs)
    def test_nonfinite(self):
        for v in [float('nan'),float('inf'),True,'3']:
            with self.subTest(v=v),self.assertRaises(ValueError):Spec(mach=v)
    def test_true_3d(self):
        for v in [1,0,8.0,True]:
            with self.subTest(v=v),self.assertRaises(ValueError):Spec(nz=v)
    def test_scope_rejections(self):
        for kw in [dict(physics='rans'),dict(span_bc='empty'),dict(family='nozzle'),dict(mach=.8),dict(max_co=.3)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):Spec(**kw)
    def test_unknown_parameters(self):
        with self.assertRaises(ValueError):Spec.from_dict({'fvSchemes':'invented'})
    def test_unresolved_block(self):
        with self.assertRaises(ValueError):Spec(step_height=.00001)

class Construction(unittest.TestCase):
    def test_all_supported_geometry_and_run_controls(self):
        s=Spec(length=4,height=1.2,step_x=.8,step_height=.15,span=.2,nx=200,ny=96,nz=16,end_time=3,max_co=.1)
        with tempfile.TemporaryDirectory() as tmp:
            p=build(s,Path(tmp)/'case');m=(p/'system/blockMeshDict').read_text();c=(p/'system/controlDict').read_text()
            for text in ['(0.8 0 -0.1)','(4 1.2 0.1)','(40 12 16)','(160 84 16)']:
                self.assertIn(text,m)
            self.assertIn('endTime 3;',c);self.assertIn('maxCo 0.1;',c)
    def test_block_connectivity_and_patches(self):
        t=mesh_dictionary(Spec())
        self.assertEqual(t.count('hex ('),3);self.assertEqual(t.count('neighbourPatch'),2)
        self.assertNotIn('empty',t);self.assertIn('(48 16 8)',t);self.assertIn('(192 64 8)',t)
        self.assertIn('faces ((0 2 3 1) (2 5 6 3) (3 6 7 4))',t)
    def test_build_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=build(Spec(mach=2.5,pressure=2,temperature=4,step_height=.15),Path(tmp)/'case')
            self.assertIn('uniform (5 0 0)',(p/'0/U').read_text())
            self.assertIn('uniform 2;', (p/'0/p').read_text())
            self.assertIn('uniform 4;', (p/'0/T').read_text())
            self.assertIn('(48 12 8)',(p/'system/blockMeshDict').read_text())
            self.assertIn('writePrecision 16;', (p/'system/controlDict').read_text())
            for f in ['system/fvSchemes','system/fvSolution','constant/physicalProperties','constant/momentumTransport']:
                self.assertEqual((p/f).read_bytes(),(TEMPLATE/f).read_bytes())
    def test_existing_case_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case';p.mkdir();(p/'evidence').write_text('keep')
            with self.assertRaises(FileExistsError):build(Spec(),p)
            self.assertEqual((p/'evidence').read_text(),'keep')

class Measurements(unittest.TestCase):
    def test_z_uniform_does_not_imply_zero_span_velocity(self):
        l=Layout(np.array([[1,1,-.1],[1,1,.1]]));u=np.array([[3.,0,.3],[3.,0,.3]])
        self.assertEqual(np.max(abs(l.grid(u)-l.mean_plane(u))),0)
        self.assertEqual(np.max(abs(u[:,2])),.3)

class Validation(unittest.TestCase):
    def test_blocked_review_survives_and_json_serializes(self):
        from pipeline.forward_step.validate import validate
        d={k:True for k in ['solver_completed','mesh_ok','three_solution_directions','finite_all_saved','positive_all_saved','courant_finite_positive','fixed_recipe_unchanged']}
        d.update(fatal_error=False,minima_every_step={'p':1,'rho':1,'T':1},boundary={'no_empty_patches':True,'cyclic_patch_count':2,'translational_patch_count':2,'coupled_matching_ok':True},cells=129024,spec=Spec().to_dict(),shock={'jumps':{'p':2,'rho':2,'T':2}},actual_inlet_Mach=np.float64(3),Co={},mass={},spanwise={'max_abs_Uz':.3},recent_change={},scientific_review={'status':'BLOCKED'})
        v=validate(d);json.dumps(v);self.assertEqual(v['status'],'BLOCKED_PLANAR_INVARIANCE')
    def test_uniform_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'U';p.write_text('internalField uniform (3 0 0);')
            np.testing.assert_equal(field(p,2,True),[[3,0,0],[3,0,0]])
    def test_nonuniform_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'U';p.write_text('internalField nonuniform List<vector> 2 ((1 2 3)(4 5 6));')
            np.testing.assert_equal(field(p,vector=True),[[1,2,3],[4,5,6]])
    def test_bad_field_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'p';p.write_text('internalField nonuniform List<scalar> 2 (1);')
            with self.assertRaises(ValueError):field(p)
    def test_transient_storage_closes(self):
        t=np.array([0,.2,.5]);m=np.array([2,2.2,2.5]);zero=np.zeros(3)
        flux={'inlet':np.full(3,-2.),'outlet':np.ones(3),'top':zero,'bottom':zero,'obstacle':zero}
        d,_=transient_balance(t,m,flux)
        self.assertAlmostEqual(d['relative_residual_max'],0,places=14)
        self.assertAlmostEqual(d['cumulative_defect_fraction_initial_mass'],0)
        self.assertEqual(d['instantaneous_mismatch_fraction'],-.5)
    def test_continuity_detects_error(self):
        z=np.zeros(2);f={'inlet':-np.ones(2),'outlet':z,'top':z,'bottom':z,'obstacle':z}
        d,_=transient_balance([0,1],[2,2],f);self.assertEqual(d['relative_residual_max'],1)
    def test_bad_time(self):
        with self.assertRaises(ValueError):transient_balance([0,0],[1,1],{})
    def test_error_norms(self):
        self.assertEqual(relative_errors([2,2],[1,1]),{'relative_L2':1.,'relative_Linf':1.})
    def test_midplane_interpolation(self):
        xyz=np.array([[1,2,-.1],[1,2,.1]]);l=Layout(xyz)
        np.testing.assert_equal(l.mid_plane(np.array([1.,3.])),[[2.]])
    def test_layout_preserves_unordered_cells(self):
        l=Layout(np.array([[2,1,.1],[1,1,-.1],[1,1,.1],[2,1,-.1]]))
        np.testing.assert_equal(l.mean_plane(np.array([4,1,3,2])),[[2,3]])

if __name__=='__main__':unittest.main()
