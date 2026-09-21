"""Small regression checks for evidence parsing and known false-accept traps."""
import unittest
import numpy as np
from foamio import value
from build import state
class EvidenceTests(unittest.TestCase):
 def test_count_mismatch_is_rejected(self):
  with self.assertRaises(ValueError):value('internalField nonuniform List<scalar> 3 (1 2);')
 def test_scalar_and_vector_fields(self):
  np.testing.assert_equal(value('value nonuniform List<vector> 2 ((1 2 3) (4 5 6));','value'),[[1,2,3],[4,5,6]])
  np.testing.assert_equal(value('value uniform 17;','value',2),[17,17])
 def test_initializer_branches(self):
  p,t,u=state(.0326,True);self.assertAlmostEqual(u/(1.4*287*t)**.5,1,places=6)
  for r,sup in [(.05,False),(.0354,True)]:
   p,t,u=state(r,sup);m=u/(1.4*287*t)**.5
   self.assertEqual(m>1,sup);self.assertAlmostEqual(p*(1+.2*m*m)**3.5,200000,places=6)
 def test_storage_is_not_steady_mismatch(self):
  dt=np.array([1e-4,2e-4]);mass=np.array([.003,.00301,.00303]);outward=np.array([-.1,-.1])
  np.testing.assert_allclose(np.diff(mass)/dt+outward,0,atol=1e-14)
  self.assertGreater(abs(outward[0]),0)
if __name__=='__main__':unittest.main()
