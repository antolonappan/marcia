import sys
import os 
import numpy as np
real_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(f'{real_path}/../')
from marcia import Likelihood,Sampler
import unittest

class TestLikelihood(unittest.TestCase):
    def setUp(self):
        self.lk = Likelihood('LCDM',['H0','Omega_m','r_d'],['CC','BAO-alam'])
    
    def test_chisq(self):
        chisq = self.lk.chisq([70,0.3,147.78])
        assert np.allclose(round(chisq,2), 20.170)
    
    def test_logLike(self):
        loglike = self.lk.logLike([70,0.3,147.78])
        assert np.allclose(round(loglike,4), -10.0853)

class TestSampler(unittest.TestCase):
    def setUp(self):
        self.sampler = Sampler('LCDM',['H0','Omega_m','r_d'],['CC','BAO-alam'],[70,0.3,147])
    
    def TestMLE(self):
        mle = self.sampler.MLE()
        assert np.allclose(mle, [ 68.14005706,0.31956576,147.24436055])

    

