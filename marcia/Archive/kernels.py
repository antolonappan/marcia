import sys
import cmath
import numpy as np
import scipy as sp
import scipy.constants as const
import time
import configparser
from scipy.interpolate import interp1d
from scipy.integrate import quad
from scipy.interpolate import RegularGridInterpolator
from multiprocessing import Pool
import itertools

from marcia import Data
from marcia import GPconfig
from marcia.backend import kernel  as kernel


class Kernels(object):
    """
        General Gaussian process modelling that all the specific kernels must be inherited from.
        Inputs would be the appropriate amplitude and scaling parameters needed for the particular model. 
        This initialisation retuns the final covarinace matrices as functions of kernal paramters. 
        """

    def __init__(self, data, filename = None):
        """
        Initialisation simply takes the data and the filename for the config file, which declares all the GP 
        configurations.
        """    
        self.clight = 299792458. / 1000.  # km/s

        # read the config file
        if filename is None:
            MTGP = GPconfig.GPConfig('GPconfig.ini').__dict__
        else:
            MTGP = GPconfig.GPConfig(filename).__dict__
        
        # read the models and the number of tasks
        self.models = MTGP['models']
        self.nTasks = MTGP['n_Tasks']
        self.nmodel = self.nTasks
        self.self_scale = MTGP['self_scale']

        # read the nus from the config file
        self.nus = MTGP['nus']

        # The data must contain the list/lists of x-axes
        self.data = data
        self.ndata = len(data)
        
        # To check if the  number of datasets is equal to the number of models
        if len(self.data) != self.nmodel:
            raise ValueError(f'Error: data length is {len(self.data)} and does not match the number of kernels {self.nmodel}')
        
        # Here we initialise the interpolated covarince matrix function that can be called with the parameters
        # We interpolate between the min and max values of scale lengths and the number of points is set to be 100
        # This is done to speed up the calculation of the covariance matrix

        self.CovMat = {}
        self.CovMat_all = []
        self.data_tau = {}

        for i in range(self.nmodel):
            for j in range(self.nmodel):
                self.nu1 = self.nus[i]
                self.nu2 = self.nus[j]
                # To create the symmetric matrix
                if i <= j:
                    # Set l1 and l2 values from the config file taskwise 
                    l1_values = np.linspace(MTGP[f'Task_{i+1}']['l_min'], MTGP[f'Task_{i+1}']['l_max'], MTGP['n_points'])
                    l2_values = np.linspace(MTGP[f'Task_{j+1}']['l_min'], MTGP[f'Task_{j+1}']['l_max'], MTGP['n_points'])
                    tau_values = np.linspace(-10, 10, MTGP['n_points'])
                    self.CovMat[f't_{i}{j}'] = self.KcMM(l1_values, l2_values, tau_values)
                    # To create the dictionary of tau values from the for each cross and auto combination of task
                    self.data_tau[f't_{i}{j}'] = self.data[i][:, None] - self.data[j][None, :]
                else:
                    self.data_tau[f't_{j}{i}'] = self.data_tau[f't_{i}{j}']
                    self.CovMat[f't_{j}{i}'] = np.transpose(self.CovMat[f't_{i}{j}'])
            
        
        
    def __call__(self, pars):
        """
            It returns the covariance matrix for the GP model for the given paramters 
        """
        # We set the self-scaling in the likelihood function and here simply create the dictionary of parameters

        self.CovMat_all = np.block([[ pars[i,0]* pars[j,0]*self.CovMat[f't_{i}{j}']([pars[i,1]* pars[j,1], self.data_tau[f't_{i}{j}']]) for i in range(self.nTasks)] for j in range(self.nTasks)])
        return self.CovMat_all
        
    # Define the special fucntions needed for the generalised matern kernel
    def _spkv_(self, tau, l1):
        return sp.special.kv(2., 3. * np.abs(tau) / l1)
    
    def _spgamma_(self, x):
        return sp.special.gamma(x)

    def gMdef(self, tau, nu, l1):
        """ 
            Defines the basis function for the GP model and returns a vector
            Finally I define only ine single function for the basis function
            This is independent of the amplitude paramter sigma_f
            """
        x = np.abs(tau)
        if nu == '0.0': # Squared Exponential kernel
            return np.exp(- (x**2.)/(2. * l1**2.))
        elif nu == 5/2: # Matern 5/2 kernel
            return  kernel.gMdef(tau, l1, nu) * _spkv_(tau,l1) / np.pi
        elif nu == 7/2: # Matern 7/2 kernel
            return kernel.gMdef(tau,l1, nu)
        else: # Generalised Matern kernel
            A, B, C = kernel.gMdef(tau,l1,nu)
            A = A * (_spgamma_(nu/2. - 1./4.)/_spgamma_(nu/2. + 1./4.))**(1./2.) * (_spgamma_(nu + 1./2.)/_spgamma_(nu))**(1./4.)
            B = B / _spgamma_(nu/2. - 1./4.)
            return A**2. * B * C**(nu/2. - 1./4.) * _spkv_(tau,l1) / np.pi

        
    def gdMdef(self, tau, nu, l1):
        """
            Defines the derivative of the basis function for the GP model and returns a vector
            Finally I define only ine single function for the basis function"""
        B = sp.special.kv(1./4. * (5. - 2. * nu), np.sqrt(2.) * np.sqrt(nu) * np.sqrt(tau**2.) / l1)
        C = np.sqrt(_spgamma_(1./2. + nu) / _spgamma_(nu))
        A, D = kernel.gdMdef(tau, l1, nu)
        D = D * _spgamma_(1./4. + nu/2.) 
        return A * B * C / D
    
    def gMMdef_integrand(self, params):
        tau, l1, l2 = params
        gMMdef_integrand = lambda u: self.gMdef(u, self.nu1, l1) * self.gMdef(tau - u, self.nu2, l2)
        integral, _ = quad(gMMdef_integrand, -np.inf, np.inf, epsabs=1e-8, epsrel=1e-8, limit=100)
        return integral
    

    def KcMM(self, l1_values, l2_values, tau_values):
        integrals = np.zeros((len(tau_values), len(l2_values), len(l1_values)))
        params = list(itertools.product(tau_values, l2_values, l1_values))
        with Pool() as pool:
            integrals = pool.map(self.gMMdef_integrand, params)
        integrals = np.array(integrals).reshape((len(tau_values), len(l2_values), len(l1_values)))   
        return RegularGridInterpolator((tau_values, l2_values, l1_values), integrals, bounds_error=False, fill_value=None)



    #     self.kernels = ['SE', 'M92', 'M72', 'Mnu', 'dMnu', 'dSE']  # Possible kernel choices
    #     # Here 'Mnu' is a generalised matern kernel with nu as a parameter
    #     # 'dMnu' is the derivative of the generalised matern kernel with nu as a parameter

    #     if filename is None:
    #         MTGP = GPconfig.GPConfig('GPconfig.ini').__dict__
    #     else:
    #         MTGP = GPconfig.GPConfig(filename).__dict__
    #     self.models = MTGP['models']
    #     self.nus = MTGP['nus']
    #     self.n_Tasks = MTGP['n_Tasks']
    #     self.nmodel = self.n_Tasks
    #     self.self_scale = MTGP['self_scale']

    #     # The data must contain the list/lists of x-axes
    #     self.data = data
    #     self.ndata = len(data)
    #     self.params = parameters
    #     self.nparams = len(parameters)

    #     # To do: the self-scaled GP case should be handled outside the class and the parameters should be passed as a list of lists -- rewrite the code to handle this case
    #     if self.self_scale is True and (self.nparams == self.nmodel):
    #         self.ntasks = self.nmodel - 1
    #         self.model = self.model[:-1]
    #         # Implying that the scale length for all the datasets is set to be the same, we need sigma_f equal to the number of GPs and one l_s
    #         for i in range(self.ntasks-1):
    #             self.params = np.append(self.params, parameters[-1])

    #     elif self.self_scale is not True and (self.nparams != 2*self.nmodel):
    #         # We need atleast two paramters per GP task: {sigma_f, l_s}
    #         print('Error: Number of parameters does not match the model specifications')
    #         sys.exit(0)

    #     # Reshaping the parameters to be a 2D array of shape (2, ntasks)
    #     self.params = np.transpose(np.reshape(self.params, (2, self.ntasks)))

    #     # To create a dictionary of paramters and datasets
    #     self.data_f = {}
    #     self.sig_f = {}
    #     self.l_s = {}
    #     self.kernel_f = {}
    #     self.CovMat = {}
    #     self.CovMat_all = []

    #     if len(self.data) != self.ntasks:
    #         print('Error: data length does not match the number of kernels')
    #         sys.exit(0)
    #     else:
    #         for i in range(self.ntasks):
    #             if self.model[i] in self.kernels and len(self.params[i]) == 2:
    #                 self.kernel_f[f't_{i}'] = self.model[i]
    #                 self.sig_f[f't_{i}'] = self.params[i, 0]
    #                 self.l_s[f't_{i}'] = self.params[i, 1]
    #                 self.data_f[f't_{i}'] = self.data[i]

    #             else:
    #                 print(self.model[i], self.params[i])
    #                 print('Error: model or parameters not specified correctly')
    #                 sys.exit(0)
    
    # def __call__(self, parameters):
    #     """
    #         This function is called when the class is called. It returns the covariance matrix for the GP model
    #         """
    #     self.params = parameters
    #     self.CovMat = self.Cov_Mat()
    #     return self.CovMat

    # # To define the special fucntions needed for the generalised matern kernel
    # def _spkv_(self, tau, l1):
    #     return sp.special.kv(2., 3. * np.abs(tau) / l1)
    # def _spgamma_(self, x):
    #     return sp.special.gamma(x)


        
    # def gdMdef(self, model, x, l_s, nu = None): 
    #     """
    #         Defines the derivative of the basis function for the GP model and returns a vector
    #         Finally I define only ine single function for the basis function
    #         This is independent of the amplitude paramter sigma_f
    #         """
    #     if model == 'SE':
    #         return - x / l_s**2. * np.exp(- (x**2.)/(2. * l_s**2.))
    #     if model == 'Mnu':
    #         A = 2**(11./8. - nu/4.) * (nu / l_s**2.)**(1./4.) * (np.sqrt(nu) * np.sqrt(x**2.) / l_s)**(3./4. + nu/2.)
    #         B = sp.special.kv(1./4. * (5. - 2. * nu), np.sqrt(2.) * np.sqrt(nu) * np.sqrt(x**2.) / l_s)
    #         C = np.sqrt(sp.special.gamma(1./2. + nu) / sp.special.gamma(nu))
    #         D = np.pi**(1./4.) * x * sp.special.gamma(1./4. + nu/2.)
    #         return A * B * C / D 

    # def gddMdef(self, model, x, l_s, nu = None):
    #     """
    #         Defines the second derivative of the basis function for the GP model and returns a vector
    #         Finally I define only ine single function for the basis function"""
    #     if model == 'SE':
    #         return (x**2. - l_s**2.) / l_s**4. * np.exp(- (x**2.)/(2. * l_s**2.))
    #     if model == 'Mnu':
    #         A = l_s**2. * np.pi**(1./4.) * sp.special.gamma(1./4. + nu/2.) *2**(+25./8. + nu/4.)
    #         B = (nu / l_s**2.)**(1./4.) * (np.sqrt(nu) * np.sqrt(x**2.) / l_s)**(nu/2.- 1./4.)
    #         C = sp.special.kv(1./4. * (3. + 2. * nu), np.sqrt(2.) * np.sqrt(nu) * np.sqrt(x**2.) / l_s)
    #         D = np.sqrt(sp.special.gamma(1./2. + nu) / sp.special.gamma(nu))
    #         E = 4. * (l_s**2. * (3. + 4. * (-2. + nu) * nu) + 8. * nu**2. * x**2.)
    #         F = sp.special.kv(1./4. * (7. + 2. * nu), np.sqrt(2.) * np.sqrt(nu) * np.sqrt(x**2.) / l_s)
    #         G = np.sqrt(2. / nu / x**2.) * l_s * (l_s**2. * (- 9. + 2. * nu * (9. + 2. * nu - 4. * nu**2.)) - 32. * nu**2. * x**2.) 
            
    #         return A * B * D * ( G * C + E * F) / (E * D**2.) 

    # def gMMdef(self, tau, u, nu1, sigma1, l1, nu2, sigma2, l2):
    #     gM1 = self.gMdef(u, nu1, sigma1, l1)
    #     gM2 = self.gMdef(tau - u, nu2, sigma2, l2)
    #     return gM1 * gM2

    # def KcMM(self, l1_values, l2_values, tau_values):
    
    #     integrals = np.zeros((len(tau_values), len(l2_values), len(l1_values)))

    #     for i, tau in enumerate(tau_values):
    #         for j, l2 in enumerate(l2_values):
    #             for k, l1 in enumerate(l1_values):
    #                 integrand = lambda u: self.gMMdef(tau, u, nu1, 1.0, l1, nu2, 1.0, l2)
    #                 integral, _ = quad(integrand, -np.inf, np.inf, epsabs=1e-8, epsrel=1e-8, limit=100)
    #                 integrals[i, j, k] = integral
        
    #     return RegularGridInterpolator((tau_values, l2_values, l1_values), integrals, bounds_error=False, fill_value=None)

    # def matern(self, nu, x1, x2, l_s):
    #     """ 
    #         Defines the generalised matern kernel https://en.wikipedia.org/wiki/Mat%C3%A9rn_covariance_function
    #         nu is a positive half-integer that determines the differentiability of the function and the smoothness of the resulting Gaussian process sample paths.
    #         nu = 1/2, 3/2, 5/2, ... tend to be used most often in practice.
    #         nu tends to infinity, the matern kernel tends to the squared exponential kernel
    #         nu tends to 0, the matern kernel tends to the absolute exponential kernel
    #         The input x1 and x2 are the x-axes of the data points and l_s is the scale length
    #         """
        
    #     # This fucntion returns nan when x1 = x2, so we need to replace nan with zero 
    #     return np.nan_to_num((2.**(1.-nu)/sp.special.gamma(nu)) * ((np.sqrt(2.*nu) * np.abs(x1-x2))/l_s)**nu * sp.special.kv(nu, (np.sqrt(2.*nu) * np.abs(x1-x2))/l_s)) + np.eye(len(x1)) 

    
    # def kernel(self, model, params, x1, x2=None):
    #     """ 
    #         Defines the kernel function for the GP model and returns the covariance matrix 
    #         """
    #     if x2 is None:
    #         x2 = x1
    #     if model == 'SE': # Squared Exponential kernel
    #         return params[0]**2. * np.exp(- ((x1[:, None]-x2[None, :])**2.)/(2. * params[1]**2.))
    #     if model == 'M92': # Matern 9/2 kernel
    #         mat_nu = 9./2.
    #         return params[0]**2. * self.matern(mat_nu, x1[:, None], x2[None, :], params[1])
    #     if model == 'M72': # Matern 7/2 kernel
    #         mat_nu = 7./2.
    #         return params[0]**2. * self.matern(mat_nu, x1[:, None], x2[None, :], params[1]) 

    # def derivative_kernel(self, model1, model2, params1, params2, x1, x2=None):
    #     """ 
    #         Defines the derivatives of cross kernel function for the GP model and returns a matrix 
    #         """
    #     dK = {}
    #     if x2 is None:
    #         x2 = x1
    #     if model1 == 'SE' and model2 == 'SE':
    #         # product of the sigmas
    #         sig1sig2 = params1[0] * params2[0]
    #         # product of the scale lengths
    #         l1l2 = params1[1] * params2[1]
    #         # quadrature of length scales
    #         l1l2_quad = params1[1]**2. + params2[1]**2.
    #         # difference between x1 and x2
    #         x1x2 = x1[:, None]-x2[None, :]

    #         # derivativve wrt x1 and derivative wrt x2
    #         dK['dK_dx1'] = - 2 * sig1sig2 * x1x2 * np.exp(- (x1x2**2.)/(l1l2_quad)) * np.sqrt(2. * l1l2) / np.sqrt(l1l2_quad**3.) 
    #         dK['dK_dx2'] = - dK['dK_dx1']
    #         # derivative wrt x1 and x2, double derivative wrt x1 and double derivative wrt x2
    #         dK['d2K_dx1dx2'] = 2 * sig1sig2 * (1. - 2 * (x1x2**2.)/(l1l2_quad)) * np.exp(- (x1x2**2.)/(l1l2_quad)) * np.sqrt(2. * l1l2) / np.sqrt(l1l2_quad**3.)
    #         dK['d2K_dx1dx1'] = dK['d2K_dx2dx2'] = - dK['d2K_dx1dx2'] 
    #         # double derivative wrt x1 and derivative wrt x2, derivative wrt x1 and double derivative wrt x2
    #         dK['d3K_dx1dx1dx2'] = - 4 * sig1sig2 * x1x2 * (3. - 2 * (x1x2**2.)/(l1l2_quad)) * np.exp(- (x1x2**2.)/(l1l2_quad)) * np.sqrt(2. * l1l2) / np.sqrt(l1l2_quad**5.)
    #         dK['d3K_dx1dx2dx2'] = - dK['d3K_dx1dx1dx2']
    #         # double derivate wrt x1 and double derivative wrt x2
    #         dK['d4K_dx1dx1dx2dx2'] = 4 * sig1sig2 * (3. - 12 * (x1x2**2.)/(l1l2_quad) + 4 * (x1x2**4.)/(l1l2_quad**2.)) * np.exp(- (x1x2**2.)/(l1l2_quad)) * np.sqrt(2. * l1l2) / np.sqrt(l1l2_quad**5.)

    #     else:
    #         # We need to define the general case for the derivatives of the cross kernel function using the basis functions 
    #         print('Error: Derivative for generalised cross kernel not defined')
    #         sys.exit(0)
            
    #     return dK

    # def cross_kernel(self, model1, model2, params1, params2, x1, x2):
    #     """ 
    #         Defines the cross kernel function for the GP model and returns the covariance matrix 
    #         """
    #     # product of the sigmas
    #     sig1sig2 = params1[0] * params2[0]
    #     # product of the scale lengths
    #     l1l2 = params1[1] * params2[1]
    #     # quadrature of length scales
    #     l1l2_quad = params1[1]**2. + params2[1]**2.
    #     # difference between x1 and x2
    #     x1x2 = x1[:, None]-x2[None, :]

    #     if model1 == 'SE' and model2 == 'SE': # Squared Exponential kernel
    #         # This fucntion boils down to the SE kernel function when the scale lengths are equal for both the datasets
    #         return sig1sig2 * np.exp(- (x1x2**2.)/(l1l2_quad)) * np.sqrt(2. * l1l2 / l1l2_quad)
    #     else:
    #         print('Error: Cross kernel not defined')
    #         sys.exit(0)

    # def Cov_Mat(self):
    #     """ 
    #         Defines the covariance matrix for the GP model and returns the covariance matrix 
    #         """
    #     # To create a dictionary of covariance matrices for each task
        
    #     for i in range(self.ntasks):
    #         for j in range(self.ntasks):
    #             if i == j:
    #                 self.CovMat[f't_{i}{j}'] = self.kernel(self.kernel_f[f't_{i}'], self.params[i], self.data_f[f't_{i}'])
    #             elif i < j:
    #                 self.CovMat[f't_{i}{j}'] = np.transpose(self.cross_kernel(self.kernel_f[f't_{i}'], self.kernel_f[f't_{j}'], self.params[i], self.params[j], self.data_f[f't_{i}'], self.data_f[f't_{j}']))
    #             else:
    #                 self.CovMat[f't_{i}{j}'] = np.transpose(self.CovMat[f't_{j}{i}'])
        
    #     # To join all the covariance matrices defined above in the dictionaries into one big covariance matrix taking into account the cross correlations between the datasets 
    #     self.CovMat_all = np.block([[ self.CovMat[f't_{i}{j}'] for i in range(self.ntasks)] for j in range(self.ntasks)])  
        
    #     return self.CovMat_all
    