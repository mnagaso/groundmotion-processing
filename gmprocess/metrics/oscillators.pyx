# stdlib imports
import warnings

# third party imports
import numpy as np
from numpy cimport ndarray
cimport numpy as np
cimport cython
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from gmprocess.stationstream import StationStream
from gmprocess.stationtrace import StationTrace
from obspy.signal.invsim import corn_freq_2_paz, simulate_seismometer
from obspy import read

# local imports
from gmprocess.constants import GAL_TO_PCTG

cdef extern from "cfuncs.h":
    void calculate_spectrals_c(double *acc, int np, double dt,
                               double period, double damping, double *sacc,
                               double *svel, double *sdis);

cpdef list calculate_spectrals(trace, period, damping):
    """
    Returns a list of spectral responses for acceleration, velocity,
            and displacement.
    Args:
        trace (obspy Trace object): The trace to be acted upon
        period (float): Period in seconds.
        damping (float): Fraction of critical damping.

    Returns:
        list: List of spectral responses (np.ndarray).
    """
    cdef int new_np = trace.stats.npts
    cdef double new_dt = trace.stats.delta
    cdef double new_sample_rate = trace.stats.sampling_rate
    # The time length of the trace in seconds
    cdef double tlen = (new_np - 1) * new_dt
    cdef int ns

    # This is the resample factor for low-sample-rate/high-frequency
    ns = (int)(10. * new_dt / period - 0.01) + 1
    if ns > 1:
        # Increase the number of samples as necessary
        new_np = new_np * ns
        # Make the new number of samples a power of two
        # leaving this out for now; it slows things down but doesn't
        # appear to affect the results. YMMV.
        # new_np = 1 if new_np == 0 else 2**(new_np - 1).bit_length()
        # The new sample interval
        new_dt = tlen / (new_np - 1)
        # The new sample rate
        new_sample_rate = 1.0 / new_dt
        # Make a copy because resampling happens in place
        trace = trace.copy()
        # Resample the trace
        trace.resample(new_sample_rate, window=None)

    cdef ndarray[double, ndim=1] spectral_acc = np.zeros(new_np)
    cdef ndarray[double, ndim=1] spectral_vel = np.zeros(new_np)
    cdef ndarray[double, ndim=1] spectral_dis = np.zeros(new_np)
    cdef ndarray[double, ndim=1] acc = trace.data

    calculate_spectrals_c(<double *>acc.data, new_np, new_dt,
                          period, damping,
                          <double *>spectral_acc.data,
                          <double *>spectral_vel.data,
                          <double *>spectral_dis.data)
    return [spectral_acc, spectral_vel, spectral_dis, new_np, new_dt,
            new_sample_rate]


def get_acceleration(stream, units='%%g'):
    """
    Returns a stream of acceleration with specified units.
    Args:
        stream (obspy.core.stream.Stream): Strong motion timeseries
            for one station. With units of g (cm/s/s).
        units (str): Units of accelearation for output. Default is %g
    Returns:
        obpsy.core.stream.Stream: stream of acceleration.
    """
    cdef int idx
    accel_stream = Stream()
    for idx in range(len(stream)):
        trace = stream[idx]
        accel_trace = trace.copy()
        if units == '%%g':
            accel_trace.data = trace.data * GAL_TO_PCTG
            accel_trace.stats['units'] = '%%g'
        elif units == 'm/s/s':
            accel_trace.data = trace.data * 0.01
            accel_trace.stats['units'] = 'm/s/s'
        else:
            accel_trace.data = trace.data
            accel_trace.stats['units'] = 'cm/s/s'
        accel_stream.append(accel_trace)
    return accel_stream


def get_spectral(period, stream, damping=0.05, times=None):
    """
    Returns a stream of spectral response with units of %%g.
    Args:
        period (float): Period for spectral response.
        stream (obspy.core.stream.Stream): Strong motion timeseries
            for one station.
        damping (float): Damping of oscillator.
        times (np.ndarray): Array of times for the horizontal channels.
            Default is None.
    Returns:
        obpsy.core.stream.Stream or numpy.ndarray: stream of spectral response.
    """
    traces = []
    num_trace_range = range(len(stream))
    cdef int len_data = stream[0].data.shape[0]

    if isinstance(stream, (StationStream, Stream)):
        for idx in num_trace_range:
            trace = stream[idx]
            sa_list = calculate_spectrals(trace, period, damping)
            acc_sa = sa_list[0]
            acc_sa *= GAL_TO_PCTG
            stats = trace.stats.copy()
            stats.npts = sa_list[3]
            stats.delta = sa_list[4]
            stats.sampling_rate = sa_list[5]
            stats['units'] = '%%g'
            spect_trace = StationTrace(data=acc_sa, header=stats)
            traces += [spect_trace]
        spect_stream = StationStream(traces)
        return spect_stream
    else:
        rotated = []
        for idx in range(0, len(stream)):
            rot_matrix = stream[idx]
            rotated_spectrals = []
            for idy in range(0, len(rot_matrix)):
                stats = {'npts': len(rot_matrix[idy]),
                         'delta': times[1] - times[0],
                         'sampling_rate': 1.0 / (times[1] - times[0])
                        }
                new_trace = Trace(data=rot_matrix[idy], header=stats)
                sa_list = calculate_spectrals(new_trace, period, damping)
                acc_sa = sa_list[0]
                acc_sa *= GAL_TO_PCTG
                rotated_spectrals.append(acc_sa)
            rotated += [rotated_spectrals]
        return rotated


def get_velocity(stream):
    """
    Returns a stream of velocity with units of cm/s.
    Args:
        stream (obspy.core.stream.Stream): Strong motion timeseries
            for one station.
    Returns:
        obpsy.core.stream.Stream: stream of velocity.
    """
    cdef int idx
    veloc_stream = Stream()
    for idx in range(len(stream)):
        trace = stream[idx]
        veloc_trace = trace.copy()
        veloc_trace.integrate()
        veloc_trace.stats['units'] = 'cm/s'
        veloc_stream.append(veloc_trace)
    return veloc_stream
