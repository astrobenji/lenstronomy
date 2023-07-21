import numpy as np
import lenstronomy.Util.param_util as param_util
import lenstronomy.Util.util as util
from scipy import signal
from lenstronomy.Util.kin_sampling_util import KinNN_image_align
from lenstronomy.Sampling.Likelihoods import kinematic_NN_call

__all__ = ['KinLikelihood']


class KinLikelihood(object):
    """
    Class to compute the likelihood associated to binned 2D kinematic maps
    """
    def __init__(self, kinematic_data_2D_class, lens_model_class, lens_light_model_class, kwargs_data, idx_lens=0,
                 idx_lens_light=0):
        """
        :param kinematic_data_2D_class: KinData class instance
        :param lens_model_class: LensModel class instance
        :param lens_light_model_class: LightModel class instance
        :param kwargs_data: kwargs describing image rotation
        :param idx_lens: int, index of the LensModel mass profile to consider for kinematics
        :param idx_lens_light: int, index of the lens LightModel profile to consider for kinematics
        """
        self.lens_model_class = lens_model_class
        self.z_lens = self.lens_model_class.z_lens
        self.lens_light_model_class = lens_light_model_class
        self._idx_lens = idx_lens
        self._idx_lens_light = idx_lens_light
        self.kin_class = kinematic_data_2D_class

        self.kin_input = self.kin_class.KinBin.kin_bin2kwargs()
        self.image_input = self.kwargs_data2image_input(kwargs_data)
        self.kinematic_NN = kinematic_NN_call.kinematic_NN()
        self.kinNN_input = {'deltaPix':0.02, 'image': np.ones((551,551))}
        self.KiNNalign = KinNN_image_align(self.kin_input, self.image_input, self.kinNN_input)

        self.data = self.kin_class.KinBin._data
        self.psf = self.kin_class.PSF.kernel_point_source
        self.bin_mask = self.kin_class.KinBin._bin_mask
        self.covariance = self.kin_class.KinBin._covariance

        self.kin_x_grid, self.kin_y_grid = self.kin_class.KinBin.kin_grid()

        self.lens_light_bool_list = list(np.zeros_like(self.lens_light_model_class.profile_type_list,dtype=bool))
        self.lens_light_bool_list[self._idx_lens_light]=True

        D_d_fiducial = 1215.739  # fiducial distances used to create training set
        D_s_fiducial = 1650.753
        D_ds_fiducial = 1042.883
        z_d_fiducial = 0.5
        D_dt_fiducial = (1 + z_d_fiducial) * D_d_fiducial * D_s_fiducial / D_ds_fiducial
        self.fiducial_scale = D_dt_fiducial / (D_d_fiducial * (1 + z_d_fiducial))
        self.vrms=None

    def calc_vrms(self, kwargs_lens, kwargs_lens_light, kwargs_special,verbose=False):
        """
        Calculates Log likelihood from 2D kinematic likelihood
        """
        self.update_image_input(kwargs_lens)
        self.light_map = self.lens_light_model_class.surface_brightness(self.kin_x_grid,self.kin_y_grid,kwargs_lens_light,
                                                                   self.lens_light_bool_list)
        input_params,same_orientation=self.convert_to_NN_params(kwargs_lens,kwargs_lens_light,kwargs_special)
        if self.kinematic_NN.SKiNN_installed:
            velo_map = self.kinematic_NN.generate_map(input_params, verbose=verbose)
            velo_map=self.rescale_distance(velo_map,kwargs_special) #RESCALE ACCORDING TO D_d, D_dt
            #Rotation and interpolation in kin data coordinates
            self.kinNN_input['image']=velo_map
            self.KiNNalign.update(self.kin_input, self.image_input, self.kinNN_input)
            self.rotated_velo = self.KiNNalign.interp_image()
            #Convolution by PSF to calculate Vrms and binning
            vrms = self.auto_binning(self.rotated_velo,self.light_map)
            return vrms
        else:
            return np.nan
    def logL(self, kwargs_lens, kwargs_lens_light, kwargs_special,verbose=False):
        """
        Calculates Log likelihood from 2D kinematic likelihood
        """
        if self.kinematic_NN.SKiNN_installed:
            self.update_image_input(kwargs_lens)
            self.light_map = self.lens_light_model_class.surface_brightness(self.kin_x_grid,self.kin_y_grid,kwargs_lens_light,
                                                                       self.lens_light_bool_list)
            input_params,same_orientation=self.convert_to_NN_params(kwargs_lens,kwargs_lens_light,kwargs_special)
            if self.kinematic_NN.check_bounds(input_params,same_orientation=same_orientation,verbose=verbose)==False:
                #params not within training set. Penalty
                return -10**8
            self.vrms=self.calc_vrms(kwargs_lens, kwargs_lens_light, kwargs_special,verbose=verbose)
            logL = self._logL(self.vrms)
        else:
            logL=np.nan
        return logL

    def convert_to_NN_params(self, kwargs_lens, kwargs_lens_light, kwargs_special):
        """
        converts lenstronomy kwargs into input vector for SKiNN, also returns whether or not mass and light are aligned
        """
        # lenstronomy to GLEE conversion
        # orientation_mass,q_mass=param_util.ellipticity2phi_q(kwargs_lens[self._idx_lens]['e1'],
        #                                                      kwargs_lens[self._idx_lens]['e2'])
        orientation_mass = kwargs_lens[self._idx_lens]['phi']
        q_mass =  kwargs_lens[self._idx_lens]['q']
        # orientation_light, q_light = param_util.ellipticity2phi_q(kwargs_lens_light[self._idx_lens]['e1'],
        #                                                         kwargs_lens_light[self._idx_lens]['e2'])
        orientation_light = kwargs_lens_light[self._idx_lens]['phi']
        q_light = kwargs_lens_light[self._idx_lens]['q']

        same_orientation=True #confirm that angles are aligned
        if np.abs(orientation_mass-orientation_light)>0.05:
            if q_light<0.95 or q_mass<0.95:
                same_orientation=False

        thetaE_lenstro=kwargs_lens[self._idx_lens]['theta_E']
        gamma_lenstro=kwargs_lens[self._idx_lens]['gamma']
        gamma_GLEE=(gamma_lenstro-1)/2
        RE_scale=(2/(1+q_mass))**(1/(2*gamma_GLEE)) * np.sqrt(q_mass)
        thetaE_GLEE=thetaE_lenstro/RE_scale
        return np.array([q_mass, q_light, thetaE_GLEE, kwargs_lens_light[self._idx_lens]['n_sersic'],
                         kwargs_lens_light[self._idx_lens]['R_sersic'], 8.0e-2, gamma_GLEE,
                        kwargs_special['b_ani'], kwargs_special['incli']*180/np.pi]),same_orientation

    def rescale_distance(self, image, kwargs_special):
        """
        rescales velocity map according to distance, requires lens redshift
        """
        new_scale = kwargs_special['D_dt'] / (kwargs_special['D_d'] * (1 +self.z_lens))
        factor = np.sqrt(
            new_scale / self.fiducial_scale)  # vrms^2 propto D_dt/Dd (see https://arxiv.org/pdf/2109.14615.pdf Eq. 20)
        return image * factor

    def kwargs_data2image_input(self,kwargs_data):
        """
        Creates the kwargs of the image needed for 2D kinematic likelihood
        """
        deltaPix = np.sqrt(np.abs(np.linalg.det(kwargs_data['transform_pix2angle'])))
        kwargs = {'image':kwargs_data['image_data'], 'deltaPix':deltaPix,
                  'transform_pix2angle':kwargs_data['transform_pix2angle'],
                  'ra_at_xy0':kwargs_data['ra_at_xy_0'],'dec_at_xy0':kwargs_data['dec_at_xy_0']}
        return kwargs

    def update_image_input(self,kwargs_lens):
        """
        Updates the image_input for rotation with the new values of orientation and center of the lens model.
        """
        orientation_ellipse=kwargs_lens[self._idx_lens]['phi']
        q =  kwargs_lens[self._idx_lens]['q']
        cx = kwargs_lens[self._idx_lens]['center_x']
        cy = kwargs_lens[self._idx_lens]['center_y']
        self.image_input['ellipse_PA'] = orientation_ellipse
        self.image_input['offset_x'] = cx
        self.image_input['offset_y'] = cy

    def auto_binning(self,rotated_map, light_map):
        """
        Function to convolve and bin the NN rotated output
        """
        vrms = rotated_map
        mgeCar = light_map

        vrms = signal.fftconvolve(vrms, self.psf, mode='same')
        mgeCar_con = signal.fftconvolve(mgeCar, self.psf, mode='same')

        numerator = []
        denominator = []

        for idx in range(len(self.data)):
            math_pos = np.where(self.bin_mask == idx)
            if np.shape(math_pos[0])[0]==0:
                raise ValueError('binmap mismatch with data: no pixels in bin with idx %i' %(idx))
            numerator.append(np.sum(vrms[math_pos]*mgeCar_con[math_pos]))
            denominator.append(np.sum(mgeCar_con[math_pos]))

        Vrms = np.array(numerator) / np.array(denominator).clip(0)

        return Vrms

    def _logL(self,vrms):
        """
        Calculates the log likelihood for a given binned model
        """
        # log_like = (vrms - self.data)**2 / self.noise**2
        cov_inv=np.linalg.inv(self.covariance)
        log_like=np.matmul(np.matmul((vrms - self.data).T,cov_inv),(vrms - self.data))
        logL = - np.sum(log_like) / 2

        if not np.isfinite(logL):
            return -10 ** 15

        return logL

