__author__ = 'aymgal'

import pytest
import numpy as np
import lenstronomy.Util.simulation_util as sim_util
from lenstronomy.ImSim.image_model import ImageModel
from lenstronomy.Sampling.likelihood import LikelihoodModule
from lenstronomy.Sampling.parameters import Param
from lenstronomy.LensModel.lens_model import LensModel
from lenstronomy.LightModel.light_model import LightModel
from lenstronomy.Data.imaging_data import ImageData
from lenstronomy.Data.psf import PSF

from lenstronomy.Sampling.Samplers.dynesty_sampler import DynestySampler


class TestDynestySampler(object):
    """
    test the fitting sequences
    """

    def setup(self):

        # data specifics
        sigma_bkg = 0.05  # background noise per pixel
        exp_time = 100  # exposure time (arbitrary units, flux per pixel is in units #photons/exp_time unit)
        numPix = 10  # cutout pixel size
        deltaPix = 0.1  # pixel size in arcsec (area per pixel = deltaPix**2)
        fwhm = 0.5  # full width half max of PSF

        # PSF specification

        kwargs_data = sim_util.data_configure_simple(numPix, deltaPix, exp_time, sigma_bkg)
        data_class = ImageData(**kwargs_data)
        kwargs_psf_gaussian = {'psf_type': 'GAUSSIAN', 'fwhm': fwhm, 'pixel_size': deltaPix}
        psf = PSF(**kwargs_psf_gaussian)
        kwargs_psf = {'psf_type': 'PIXEL', 'kernel_point_source': psf.kernel_point_source}
        psf_class = PSF(**kwargs_psf)
        kwargs_spemd = {'theta_E': 1., 'gamma': 1.8, 'center_x': 0, 'center_y': 0, 'e1': 0.1, 'e2': 0.1}

        lens_model_list = ['SPEP']
        self.kwargs_lens = [kwargs_spemd]
        lens_model_class = LensModel(lens_model_list=lens_model_list)
        kwargs_sersic = {'amp': 1., 'R_sersic': 0.1, 'n_sersic': 2, 'center_x': 0, 'center_y': 0}
        # 'SERSIC_ELLIPSE': elliptical Sersic profile
        kwargs_sersic_ellipse = {'amp': 1., 'R_sersic': .6, 'n_sersic': 3, 'center_x': 0, 'center_y': 0,
                                 'e1': 0.1, 'e2': 0.1}

        lens_light_model_list = ['SERSIC']
        self.kwargs_lens_light = [kwargs_sersic]
        lens_light_model_class = LightModel(light_model_list=lens_light_model_list)
        source_model_list = ['SERSIC_ELLIPSE']
        self.kwargs_source = [kwargs_sersic_ellipse]
        source_model_class = LightModel(light_model_list=source_model_list)

        kwargs_numerics = {'supersampling_factor': 1, 'supersampling_convolution': False, 'compute_mode': 'regular'}
        imageModel = ImageModel(data_class, psf_class, lens_model_class, source_model_class,
                                lens_light_model_class, kwargs_numerics=kwargs_numerics)
        image_sim = sim_util.simulate_simple(imageModel, self.kwargs_lens, self.kwargs_source,
                                         self.kwargs_lens_light)

        data_class.update_data(image_sim)
        kwargs_data['image_data'] = image_sim
        kwargs_data_joint = {'multi_band_list': [kwargs_data, kwargs_psf, kwargs_numerics], 'multi_band_type': 'single-band'}
        self.data_class = data_class
        self.psf_class = psf_class

        kwargs_model = {'lens_model_list': lens_model_list,
                             'source_light_model_list': source_model_list,
                             'lens_light_model_list': lens_light_model_list,
                             'fixed_magnification_list': [False],
                             }
        self.kwargs_numerics = {
            'subgrid_res': 1,
            'psf_subgrid': False}

        kwargs_constraints = {'image_plane_source_list': [False] * len(source_model_list)}

        kwargs_likelihood = {
                                  'source_marg': True,
                                  'point_source_likelihood': False,
                                  'position_uncertainty': 0.004,
                                  'check_solver': False,
                                  'solver_tolerance': 0.001,
                                  }
        self.param_class = Param(kwargs_model, **kwargs_constraints)
        self.Likelihood = LikelihoodModule(kwargs_data_joint=kwargs_data_joint, kwargs_model=kwargs_model,
                                           param_class=self.param_class, **kwargs_likelihood)
        self.sampler  = DynestySampler(self.Likelihood, remove_output_dir=True)

        prior_means  = np.zeros_like(self.sampler.lowers)
        prior_sigmas = np.ones_like(self.sampler.lowers)
        self.sampler_gauss = DynestySampler(self.Likelihood, prior_type='gaussian',
                                            prior_means=prior_means, 
                                            prior_sigmas=prior_sigmas,
                                            remove_output_dir=True)

    def test_sampler(self):
        kwargs_run = {
            'dlogz_init': 0.05,
            'nlive_init': 10,
            'nlive_batch': 20,
        }
        samples, means, logZ, logZ_err, logL = self.sampler.run(kwargs_run)
        assert len(samples) == 16
        samples, means, logZ, logZ_err, logL = self.sampler_gauss.run(kwargs_run)
        assert len(samples) == 16


if __name__ == '__main__':
    pytest.main()
