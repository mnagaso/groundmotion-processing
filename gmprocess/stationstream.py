# stdlib imports
import json
import logging

# third party imports
import numpy as np
from obspy.core.stream import Stream
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.inventory import (Inventory, Network, Station,
                                  Channel, Site, Equipment, Comment,
                                  Response, InstrumentSensitivity)
# local imports
from .stationtrace import StationTrace
from gmprocess.exception import GMProcessException

UNITS = {
    'acc': 'cm/s/s',
    'vel': 'cm/s'
}
REVERSE_UNITS = {
    'cm/s/s': 'acc',
    'cm/s': 'vel'
}

# Number of samples for Landzos interpolation.
N_LANCZOS = 20

# if we find places for these in the standard metadata,
# remove them from this list. Anything here will
# be extracted from the stats standard dictionary,
# combined with the format_specific dictionary,
# serialized to json and stored in the station description.
UNUSED_STANDARD_PARAMS = [
    'instrument_period',
    'instrument_damping',
    'process_time',
    'process_level',
    'structure_type',
    'corner_frequency',
    'source_file'
]


class StationStream(Stream):
    def __init__(self, traces=None, inventory=None):
        super(StationStream, self).__init__()

        if len(traces):
            # sometimes traces have different start/end times
            # let's get the minimum bounding times here
            # and trim the trace before we add it to the stream.
            starts = [trace.stats.starttime for trace in traces]
            ends = [trace.stats.endtime for trace in traces]
            sts = [s.timestamp for s in starts]
            ets = [e.timestamp for e in ends]

            # Do we need to try to fix the start/end times?
            times_match = len(set(sts)) == 1 & len(set(ets)) == 1
            if not times_match:
                newstart = max(starts)
                newend = min(ends)
                if newstart >= newend:
                    for trace in traces:
                        trace.fail(
                            'Trimming start/end times across traces for '
                            'this stream resulting in a start time after '
                            'the end time.'
                        )
                        self.append(trace)
                else:
                    # First try to simply cut, the most minimally invasive
                    # option
                    for trace in traces:
                        if inventory is None:
                            if not isinstance(trace, StationTrace):
                                raise ValueError(
                                    'Input Traces to StationStream must be of '
                                    'subtype StationTrace unless an invenotry '
                                    'is also provided.')
                        else:
                            if not isinstance(trace, StationTrace):
                                trace = StationTrace(
                                    data=trace.data,
                                    header=trace.stats,
                                    inventory=inventory
                                )

                        # Apply the new start/end times
                        trace = trace.slice(starttime=newstart,
                                            endtime=newend)
                        trace.setProvenance(
                            'cut',
                            {
                                'new_start_time': newstart,
                                'new_end_time': newend
                            }
                        )

                        self.append(trace)

                    # Did that work?
                    starts = [trace.stats.starttime for trace in self.traces]
                    sts = [s.timestamp for s in starts]
                    ends = [trace.stats.endtime for trace in self.traces]
                    ets = [e.timestamp for e in ends]
                    deltas = [trace.stats.delta for trace in self.traces]
                    new_delta = min(deltas)
                    newstart = max(starts)
                    newend = min(ends)
                    new_duration = newend-newstart
                    new_npts = int(new_duration / new_delta + 1)
                    success = len(set(sts)) == 1 & len(set(ets)) == 1

                    # If not, resample
                    if not success:
                        for tr in self.traces:
                            tr.interpolate(
                                sampling_rate=1/new_delta,
                                method='lanczos',
                                starttime=newstart,
                                npts=new_npts,
                                a=N_LANCZOS)
                            tr.setProvenance(
                                'interpolate',
                                {
                                    'interpolation_method': 'lanczos',
                                    'new_number_of_samples': new_npts,
                                    'new_start_time': newstart,
                                    'a': N_LANCZOS
                                }
                            )
            else:
                for trace in traces:
                    if inventory is None:
                        if not isinstance(trace, StationTrace):
                            raise ValueError(
                                'Input Traces to StationStream must be of '
                                'subtype StationTrace unless an invenotry '
                                'is also provided.')
                    else:
                        if not isinstance(trace, StationTrace):
                            trace = StationTrace(
                                data=trace.data,
                                header=trace.stats,
                                inventory=inventory
                            )
                    self.append(trace)

        self.validate()
        self.parameters = {}

    def validate(self):
        """Some validation checks for Traces within the StationStream.

        """
        logging.debug(self)

        # Check that channel codes are unique_npts
        self.__check_channels()

        # Check that id is consistent, and set id if it passes the check.
        self.id = None
        self.__check_id()

        # The ID check is the only one that raises an exception, the
        # rest of these label the stream as failed rather than raise
        # an exception.
        self.__check_sample_rate()
        self.__check_npts()
        self.__check_starts()

    def __check_sample_rate(self):
        unique_sampling_rates = set([tr.stats.sampling_rate for tr in self])
        if len(unique_sampling_rates) > 1:
            for tr in self:
                tr.fail('StationStream traces have different sampling rates.')

    def __check_npts(self):
        unique_npts = set([len(tr) for tr in self])
        if len(unique_npts) > 1:
            for tr in self:
                tr.fail('StationStream traces have a different number '
                        'of points.')

    def __check_starts(self):
        unique_starts = set([tr.stats.starttime.timestamp for tr in self])
        if len(unique_starts) > 1:
            for tr in self:
                tr.fail('StationStream traces have different start '
                        'times.')

    def __check_channels(self):
        if len(self):
            all_codes = []
            for tr in self:
                stats = tr.stats
                all_codes.append(
                    "%s.%s.%s" % (stats.network, stats.station, stats.channel))
            if len(set(all_codes)) != len(all_codes):
                for tr in self:
                    tr.fail('Nonunique channel code in StationStream.')

    def __check_id(self):
        # Check that id is consistent, and set id if it passes the check.
        if len(self):
            stats = self.traces[0].stats
            id_str = ("%s.%s.%s" %
                      (stats.network, stats.station, stats.channel[0:2]))

            # Check that the id would be the same for all traces
            for tr in self:
                stats = tr.stats
                test_str = ("%s.%s.%s" %
                            (stats.network, stats.station, stats.channel[0:2]))
                if id_str != test_str:
                    raise ValueError(
                        'Inconsistent stream ID for different traces.')
            self.id = id_str

    def get_id(self):
        """
        Get the StationStream ID.

        This consists of the network, station, and first two characters of the
        channel (to indicate instrument type). This is currently consistent
        with how the channels are grouped and ignores the location code because
        it doesn't seem like it is defined in a consistent fashion.
        """
        return self.id

    def get_net_sta(self):
        """
        Get just the network and station compopnent of the ID.
        """
        return '.'.join(self.get_id().split('.')[0:2])

    def get_inst(self):
        """
        Get just the network and station compopnent of the ID.
        """
        return self.get_id().split('.')[2]

    @property
    def passed(self):
        """
        Check the traces to see if any have failed any processing steps.

        Returns:
            bool: True if no failures in Traces, False if there are.

        """
        return self.check_stream()

    def __str__(self, extended=False, indent=0):
        """
        String summary of the StationStream.

        Args:
            extended (bool):
                Unused; kept for compatibility with ObsPy parent class.
            indent (int):
                Number of characters to indent.
        """
        if self.traces:
            id_length = self and max(len(tr.id) for tr in self) or 0
        else:
            id_length = 0
        if self.passed:
            pass_str = ' (passed)'
        else:
            pass_str = ' (failed)'
        ind_str = ' ' * indent
        out = ('%s StationTrace(s) in StationStream%s:\n%s'
               % (ind_str + str(len(self.traces)), pass_str, ind_str))
        lc = [_i.__str__(id_length, indent) for _i in self]
        out += ("\n" + ind_str).join(lc)
        return out

    def setStreamParam(self, param_id, param_attributes):
        """Add to the StationStreams's set of arbitrary metadata.

        Args:
            param_id (str):
                Key for parameters dictionary.
            param_attributes (dict or list):
                Parameters for the given key.
        """
        self.parameters[param_id] = param_attributes

    def getStreamParamKeys(self):
        """Get a list of all available parameter keys.

        Returns:
            list: List of available parameter keys.
        """
        return list(self.parameters.keys())

    def getStreamParam(self, param_id):
        """Retrieve some arbitrary metadata.

        Args:
            param_id (str):
                Key for parameters dictionary.

        Returns:
            dict or list:
                Parameters for the given key.
        """
        if param_id not in self.parameters:
            raise KeyError(
                'Parameter %s not found in StationStream' % param_id)
        return self.parameters[param_id]

    def getProvenanceDocuments(self):
        provdocs = []
        for trace in self.traces:
            provdoc = trace.getProvenanceDocument()
            provdocs.append(provdoc)
        return provdocs

    def getInventory(self):
        """
        Extract an ObsPy inventory object from a Stream read in by gmprocess
        tools.
        """
        networks = [trace.stats.network for trace in self]
        if len(set(networks)) > 1:
            raise Exception(
                "Input stream has stations from multiple networks.")

        # We'll first create all the various objects. These strongly follow the
        # hierarchy of StationXML files.
        source = ''
        if 'standard' in self[0].stats and 'source' in self[0].stats.standard:
            source = self[0].stats.standard.source
        inv = Inventory(
            # We'll add networks later.
            networks=[],
            # The source should be the id whoever create the file.
            source=source)

        net = Network(
            # This is the network code according to the SEED standard.
            code=networks[0],
            # A list of stations. We'll add one later.
            stations=[],
            description="source",
            # Start-and end dates are optional.
        )
        channels = []
        for trace in self:
            logging.debug('trace: %s' % trace)
            channel = _channel_from_stats(trace.stats)
            channels.append(channel)

        subdict = {}
        for k in UNUSED_STANDARD_PARAMS:
            if k in self[0].stats.standard:
                subdict[k] = self[0].stats.standard[k]

        format_specific = {}
        if 'format_specific' in self[0].stats:
            format_specific = dict(self[0].stats.format_specific)

        big_dict = {'standard': subdict,
                    'format_specific': format_specific}
        try:
            jsonstr = json.dumps(big_dict)
        except Exception as e:
            raise GMProcessException('Exception in json.dumps: %s' % e)
        sta = Station(
            # This is the station code according to the SEED standard.
            code=self[0].stats.station,
            latitude=self[0].stats.coordinates.latitude,
            elevation=self[0].stats.coordinates.elevation,
            longitude=self[0].stats.coordinates.longitude,
            channels=channels,
            site=Site(name=self[0].stats.standard.station_name),
            description=jsonstr,
            creation_date=UTCDateTime(1970, 1, 1),  # this is bogus
            total_number_of_channels=len(self))

        net.stations.append(sta)
        inv.networks.append(net)

        return inv

    def check_stream(self):
        """
        Processing checks get regorded as a 'failure' parameter in
        StationTraces. Streams also need to be classified as passed/faild,
        where if any of the checks have failed for consistent traces then the
        stream has failed.
        """
        stream_checks = []
        for tr in self:
            stream_checks.append(tr.hasParameter('failure'))
        if any(stream_checks):
            return False
        else:
            return True


def _channel_from_stats(stats):
    if stats.standard.units in UNITS:
        units = UNITS[stats.standard.units]
    else:
        units = ''
    instrument = stats.standard.instrument
    serialnum = stats.standard.sensor_serial_number
    if len(instrument) or len(serialnum):
        equipment = Equipment(type=instrument,
                              serial_number=serialnum)
    else:
        equipment = None
    depth = 0.0
    azimuth = None
    c1 = 'horizontal_orientation' in stats.standard
    c2 = c1 and not np.isnan(stats.standard.horizontal_orientation)
    if c2:
        azimuth = stats.standard.horizontal_orientation
    else:
        azimuth = 0

    response = None
    if 'response' in stats:
        response = stats['response']

    # we may have instrument sensitivity...
    if not np.isnan(stats['standard']['instrument_sensitivity']):
        sens = stats['standard']['instrument_sensitivity']
        frequency = 1 / stats['standard']['instrument_period']
        sensitivity = InstrumentSensitivity(sens,
                                            frequency=frequency,
                                            input_units='M/S',
                                            output_units='COUNTS')
        response = Response(instrument_sensitivity=sensitivity)

    comments = Comment(stats.standard.comments)
    logging.debug('channel: %s' % stats.channel)
    channel = Channel(stats.channel,
                      stats.location,
                      stats.coordinates['latitude'],
                      stats.coordinates['longitude'],
                      stats.coordinates['elevation'],
                      depth,
                      azimuth=azimuth,
                      sample_rate=stats.sampling_rate,
                      storage_format=stats.standard.source_format,
                      calibration_units=units,
                      comments=[comments],
                      response=response,
                      sensor=equipment)
    return channel
