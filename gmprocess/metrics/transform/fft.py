# Third party imports
import numpy as np

# Local imports
from gmprocess.metrics.transform.transform import Transform
from gmprocess.fft import compute_fft

# Third-party imports
from obspy.signal.util import next_pow_2


class FFT(Transform):
    """Class for computing the fast fourier transform.
    """

    def __init__(self, transform_data, damping=None, period=None, times=None,
                 max_period=None, allow_nans=None, bandwidth=None):
        """
        Args:
            transform_data (obspy.core.stream.Stream or numpy.ndarray):
                Intensity measurement component.
            damping (float):
                Damping for spectral amplitude calculations. Default is None.
            period (float):
                Period for spectral amplitude calculations. Default is None.
            times (numpy.ndarray):
                Times for the spectral amplitude calculations. Default is None.
        """
        super().__init__(transform_data, damping=None, period=None, times=None,
                         max_period=None, allow_nans=None, bandwidth=None)
        self.max_period = max_period
        self.allow_nans = allow_nans
        self.bandwidth = bandwidth
        self.result = self.get_fft()

    def get_fft(self):
        """
        Calculated the fft of each trace's data.

        Returns:
            numpy.ndarray: Computed fourier amplitudes.
        """
        fft_dict = {}
        for trace in self.transform_data:

            if self.allow_nans:
                nfft = len(trace.data)
            else:
                nfft = self.get_nfft()

            # Check if we already have computed the FFT for this trace
            if trace.hasCached('fas_spectrum'):
                spectra = trace.getCached('fas_spectrum')
                sampling_rate = trace.stats.sampling_rate
                freqs = np.fft.rfftfreq(nfft, 1 / sampling_rate)
            else:
                spectra, freqs = compute_fft(trace, nfft)
                trace.setCached('fas_spectrum', spectra)

            tdict = {
                'freqs': freqs,
                'spectra': spectra
            }
            fft_dict[trace.stats['channel'].upper()] = tdict

        return fft_dict

    def get_nfft(self):
        """
        Returns the number of points for the FFT that will ensure that the
        Fourier Amplitude Spectrum can be computed without returning NaNs
        (due to the spectral resolution requirements of the Konno-Ohmachi
        smoothing).

        Returns:
            int: Number of points for the FFT.
        """
        nyquist = 0.5 * self.transform_data[0].stats.sampling_rate
        min_freq = 1.0 / self.max_period
        df = (min_freq * 10**(3.0 / self.bandwidth)) - (
            min_freq / 10**(3.0 / self.bandwidth))
        return next_pow_2(nyquist / df)
