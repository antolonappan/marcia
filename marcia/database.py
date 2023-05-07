from typing import Any
from numpy import loadtxt
import numpy as np
import os


__path__ = os.path.dirname(os.path.realpath(__file__))
__datapath__ = os.path.join(__path__,'../' 'Data')

class Data:

    def __init__(self,data):
        datalist = ['CC','BAO','GR','Lya','GRB','SNE','QSA']
        if type(data) is str:
            assert data in datalist, f'{data} is not in {datalist}'
            self.data = [data]
        elif type(data) is list:
            for d in data:
                assert d in datalist, f'{d} is not in {datalist}'
            self.data = data
        else:
            raise TypeError(f'{data} is not a valid type')
        
       # self.x,self.y,self.covar = self.get_data()
    def __block_matrix__(self,matrices):
        size = sum(matrix.shape[0] for matrix in matrices)
        result = np.zeros((size, size))

        # Fill the resulting matrix with the input matrices in a block diagonal manner
        row_start = 0
        col_start = 0
        for matrix in matrices:
            row_end = row_start + matrix.shape[0]
            col_end = col_start + matrix.shape[1]
            result[row_start:row_end, col_start:col_end] = matrix
            row_start = row_end
            col_start = col_end
        
        return result

    def __call__(self, paramdict):
        """
        return 
        x = concatenated x data
        y = concatenated y data
        covar = big matrix with blocks of covariances
        """
        x = []
        y = []
        covar = []
        for d in self.data:
            x1,y1,covar1 = self.get_data(d,paramdict)
            x.append(x1)
            y.append(y1)
            covar.append(covar1)
        x = np.concatenate(x)
        y = np.concatenate(y)
        covar = self.__block_matrix__(covar)
        return x,y,covar

    def get_data(self,choose,paramdict):
        if choose == 'CC':
            return self.get_cosmic_clocks()
        elif choose == 'BAO':
            return self.get_bao()
        elif choose == 'GR':
            assert 'file' in paramdict.keys(), 'file no must be in paramdict'
            return self.get_growth(paramdict['file'])
        elif choose == 'Lya':
            return self.get_Lya()
        elif choose == 'GRB':
            assert 'Lambda' in paramdict.keys() and 'b' in paramdict.keys() and 'sigma_sys' in paramdict.keys(), 'Lambda, b and sigma_sys must be in paramdict'
            return self.get_GRB(paramdict['Lambda'],paramdict['b'],paramdict['sigma_sys'])
        elif choose == 'SNE':
            return self.get_SNE()
        elif choose == 'QSA':
            return self.get_QSA()
        else:
            raise ValueError(f'{choose} is not a valid data set')
    
    def get_cosmic_clocks(self):
        datafile = loadtxt(os.path.join(__datapath__, 'Cosmic_Clocks','CC.txt'))
        x = datafile[:,0]
        y = datafile[:,1]
        sigma = datafile[:,2]
        covar = np.diag(sigma**2)
        assert len(x) == len(y) == covar.shape[0] == covar.shape[1]
        return x,y,covar
    
    def get_bao(self):
        datafile = loadtxt(os.path.join(__datapath__, 'Alam2016','DmH.txt'))
        datafile2 = loadtxt(os.path.join(__datapath__, 'Alam2016','CovDmh.txt'))
        x = datafile[:,0]
        y = datafile[:,1]
        covar = datafile2
        assert len(x) == len(y) == covar.shape[0] == covar.shape[1]
        return x,y,covar
    
    def get_growth(self,file=0):
        datafile = loadtxt(os.path.join(__datapath__, 'Growth Rate',f'GR{file}.txt' if file > 0 else 'GR.txt')) 
        x = datafile[:,0]
        y = datafile[:,1]
        covar = np.diag(datafile[:,2]**2)
        assert len(x) == len(y) == covar.shape[0] == covar.shape[1]
        return x,y,covar
    
    def get_Lya(self):
        datafile = loadtxt(os.path.join(__datapath__, 'Lyman-alpha','DmH.txt'))
        datafile2 = loadtxt(os.path.join(__datapath__, 'Lyman-alpha','CovDmh.txt')) 
        x = datafile[:,0]
        y = datafile[:,1]
        covar = datafile2
        assert len(x) == len(y) == covar.shape[0] == covar.shape[1]
        return x,y,covar
    
    def get_GRB(self,Lambda=1,b=1,sigma_sys=0.7571):
        datafile = loadtxt(os.path.join(__datapath__, 'GRB','GRB.txt'),usecols=(1,2,3,4,5))
        z = datafile[:,0]
        S_b = datafile[:,1]
        sigma_S_b = datafile[:,2]
        E_p = datafile[:,3]
        sigma_E_p = datafile[:,4]

        mu1 = (1+z)/(4*np.pi)
        mu2 = (E_p/300)**b
        mu3 = (S_b**-1/100)
        mu = (5/2)*(np.log10(mu1*mu2*mu3)+ Lambda)

        sigma_mu1 = (5/(2*np.log(10)))**2
        sigma_mu2 = (b*sigma_E_p/E_p)**2
        sigma_mu3 = (sigma_S_b/S_b)**2
        sigma_mu = sigma_mu1*(sigma_mu2+sigma_mu3+sigma_sys**2)

        covar = np.diag(sigma_mu)

        x = z
        y = mu
        return x,y,covar

    def get_SNE(self):
        data = loadtxt(os.path.join(__datapath__, 'Pantheon_E','SNE.txt'))
        corr = loadtxt(os.path.join(__datapath__, 'Pantheon_E','SSNE.txt'))
        x = data[:,0]
        y = 1/data[:,1]
        sigma = data[:,2]
        covar = sigma * corr * sigma.T
        return x,y,covar

    def get_QSA(self):
        data = loadtxt(os.path.join(__datapath__, 'Quasars','DL_all_short.txt'))
        x = data[:,0]
        y = data[:,1]
        sigma = data[:,2]
        covar = np.diag(sigma**2)
        return x,y,covar

