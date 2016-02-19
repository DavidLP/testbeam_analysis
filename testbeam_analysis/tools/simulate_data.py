''' This module provides a class that is able to simulate data via Monte Carlo. A random seed can be set.
The deposited charge follows a user defined function (e.g. a Landau function). Special processes like delta electrons
are not simulated and also the track angle is not takeb into account. 
Charge sharing between pixels is calculated using Einsteins diffusion equation solved at equidistand z position within the sensor.
'''

import numpy as np
import tables as tb
import logging
import progressbar
from numba import njit
import math
from pyLandau import landau


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - [%(levelname)-8s] (%(threadName)-10s) %(message)s")


# Jitted function for fast calculations
@njit()
def _calc_sigma_diffusion(distance, temperature, bias):
    ''' Calculates the sigma of the diffusion according to Einsteins equation.
    Parameters
    ----------
    length : number
        the drift distance
    temperature : number
        Temperature of the sensor
    bias : number
        bias voltage of the sensor

    Returns
    -------
    number

    '''

    boltzman_constant = 8.6173324e-5
    return distance * np.sqrt(2 * temperature / bias * boltzman_constant)


@njit()
def _bivariante_normal_cdf_limits(a1, a2, b1, b2, mu1, mu2, sigma):
    '''Calculates the integral of the bivariante normal distribution between x = [a1, a2], y = [b1, b2]. The normal distribution has two mu: mu1, mu2 but only one common sigma.

    Parameters
    ----------
    a1, a2: number
        Integration limits in x

    b1, b2: number
        Integration limits in y

    mu1, mu2: number, array like
        Position in x, y where the integral is evaluated

    sigma: number
        distribution parameter

    Returns
    -------
    number, array like
    '''

    return 1 / (4.) * (math.erf((a2 - mu1) / np.sqrt(2 * sigma ** 2)) - math.erf((a1 - mu1) / np.sqrt(2 * sigma ** 2))) * (math.erf((b2 - mu2) / np.sqrt(2 * sigma ** 2)) - math.erf((b1 - mu2) / np.sqrt(2 * sigma ** 2)))


@njit()
def _calc_charge_fraction(position, position_z, pixel_index_x, pixel_index_y, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc):
    ''' Calculates the fraction of charge [0, 1] within one rectangular pixel volume when diffusion is considered. The calculation is done within the local pixel coordinate system,
        with the origin [x_pitch / 2, y_pitch / 2, 0]

        Parameters
        ----------
        position_i : array
            Position in x/y within the seed pixel where the charge is created
        pixel_index_x, pixel_index_y : number
            Pixel index relative to seed (= 0/0) to  get the charge fraction for
        temperature: number
            Temperature of the sensor
        bias: number
            Bias voltage of the sensor
        digitization_sigma_cc: number
            The sigma is higher due to repulsion, so correct sigma with factor > 1, very simple approximation,  for further info see NIMA 606 (2009) 508-516
        pixel_size_x, pixel_size_y : number
            Pixel dimensions in x/y in um

        Returns
        -------
        number
    '''
    sigma = _calc_sigma_diffusion(distance=position_z, temperature=temperature, bias=bias) * digitization_sigma_cc

    if (sigma == 0):  # Tread not defined calculation input
        return 1.
    return _bivariante_normal_cdf_limits(pixel_size_x * (pixel_index_x - 1. / 2.), pixel_size_x * (pixel_index_x + 1. / 2.), pixel_size_y * (pixel_index_y - 1. / 2.), pixel_size_y * (pixel_index_y + 1. / 2.), position[0], position[1], sigma)


@njit()
def _create_charge_sharing_hits(relative_position, column, row, charge, max_column, max_row, thickness, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc, result_hits, index):
    ''' Create additional hits due to charge sharing.
    Run time optimized loops using an abort condition utilizing that the charge sharing always decreases for increased 
    distance to seed pixel and the fact that the total charge fraction sum is 1
    '''

    total_fraction = 0.  # Charge fraction summed up for all pixels used; should be 1. if all pixels are considered
    min_fraction = 1e-3
    n_hits = 0  # Total Number of hits created

    position_z = thickness / 2  # FIXME: Charges are distributed along a track and not in the center z

    for actual_column in range(column, max_column):  # Calc charge in pixels in + column direction
        if total_fraction >= 1. - min_fraction or _calc_charge_fraction(relative_position, position_z, actual_column - column, 0, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc) < min_fraction:  # Omit row loop if charge fraction is already too low for seed row (=0)
            break

        for actual_row in range(row, max_row):  # Calc charge in pixels in + row direction
            fraction = _calc_charge_fraction(relative_position, position_z, actual_column - column, actual_row - row, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc)
            total_fraction += fraction
            if fraction < min_fraction:  # Abort loop if fraction is too small, next pixel have even smaller fraction
                break
            # ADD HIT
            result_hits[index][0], result_hits[index][1], result_hits[index][2] = actual_column, actual_row, fraction * charge
            index += 1
            n_hits += 1
            if total_fraction >= 1. - min_fraction:
                break

        for actual_row in range(row - 1, 0, -1):  # Calc charge in pixels in - row direction
            fraction = _calc_charge_fraction(relative_position, position_z, actual_column - column, actual_row - row, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc)
            total_fraction += fraction
            if fraction < min_fraction:  # Abort loop if fraction is too small, next pixel have even smaller fraction
                break
            # ADD HIT
            result_hits[index][0], result_hits[index][1], result_hits[index][2] = actual_column, actual_row, fraction * charge
            index += 1
            n_hits += 1
            if total_fraction >= 1. - min_fraction:
                break

    for actual_column in range(column - 1, 0, -1):  # Calc charge in pixels in + column direction
        if total_fraction >= 1. - min_fraction or _calc_charge_fraction(relative_position, position_z, actual_column - column, 0, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc) < min_fraction:  # Omit row loop if charge fraction is already too low for seed row (=0)
            break

        for actual_row in range(row, max_row):  # Calc charge in pixels in + row direction
            fraction = _calc_charge_fraction(relative_position, position_z, actual_column - column, actual_row - row, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc)
            total_fraction += fraction
            if fraction < min_fraction:  # Abort loop if fraction is too small, next pixel have even smaller fraction
                break
            # ADD HIT
            result_hits[index][0], result_hits[index][1], result_hits[index][2] = actual_column, actual_row, fraction * charge
            index += 1
            n_hits += 1
            if total_fraction >= 1. - min_fraction:
                break

        for actual_row in range(row - 1, 0, -1):  # Calc charge in pixels in - row direction
            fraction = _calc_charge_fraction(relative_position, position_z, actual_column - column, actual_row - row, pixel_size_x, pixel_size_y, temperature, bias, digitization_sigma_cc)
            total_fraction += fraction
            if fraction < min_fraction:  # Abort loop if fraction is too small, next pixel have even smaller fraction
                break
            # ADD HIT
            result_hits[index][0], result_hits[index][1], result_hits[index][2] = actual_column, actual_row, fraction * charge
            index += 1
            n_hits += 1
            if total_fraction >= 1. - min_fraction:
                break

    return index, n_hits


@njit()
def _add_charge_sharing_hits(relative_position, hits_digits, max_column, max_row, thickness, pixel_size_x, pixel_size_y, temperature, bias):
    ''' Takes the arrea of seed hits and adds for each seed hit additionally hits that arise from charge sharing. To calculate the charge sharing a lot of
    parameters are needed.
    '''
    n_hits_per_seed_hit = np.zeros(hits_digits.shape[0], dtype=np.int16)
    result_hits = np.zeros(shape=(5 * hits_digits.shape[0], 3), dtype=np.float32)  # Result array to be filled; up to 5 hits per seed hit is expected
    result_index = 0
    for actual_index in range(hits_digits.shape[0]):
        actual_hit_digit = hits_digits[actual_index]
        result_index, n_hits = _create_charge_sharing_hits(relative_position=relative_position[actual_index],
                                                           column=actual_hit_digit[0],
                                                           row=actual_hit_digit[1],
                                                           charge=actual_hit_digit[2],
                                                           max_column=max_column,
                                                           max_row=max_row,
                                                           thickness=thickness,
                                                           pixel_size_x=pixel_size_x,
                                                           pixel_size_y=pixel_size_y,
                                                           temperature=temperature,
                                                           bias=bias,
                                                           digitization_sigma_cc=1.,
                                                           result_hits=result_hits,
                                                           index=result_index)

        n_hits_per_seed_hit[actual_index] = n_hits

    return result_hits[:result_index], n_hits_per_seed_hit


class SimulateData(object):

    def __init__(self, random_seed=None):
        np.random.seed(random_seed)  # Set the random number seed to be able to rerun with same data
        self.reset()

    def set_std_settings(self):
        # Setup settings
        self.n_duts = 6
        self.z_positions = [i * 10000 for i in range(self.n_duts)]  # in um; st: every 10 cm
        self.offsets = [(-2500, -2500)] * self.n_duts  # in x, y in mu
        self.temperature = 300  # Temperature in Kelvin, needed for charge sharing calculation

        # Beam settings
        self.beam_position = (0, 0)  # Average beam position in x, y at z = 0 in mu
        self.beam_position_sigma = (2000, 2000)  # in x, y at z = 0 in mu
        self.beam_angle = 0  # Average beam angle in theta at z = 0 in mRad
        self.beam_angle_sigma = 1  # Deviation from e average beam angle in theta at z = 0 in mRad
        self.tracks_per_event = 1  # Average number of tracks per event
        self.tracks_per_event_sigma = 1  # Deviation from the average number of tracks, makes no track pe event possible!

        # Device settings
        self.dut_bias = [50] * self.n_duts  # Sensor bias voltage for each device in volt
        self.dut_thickness = [100] * self.n_duts  # Sensor thickness for each device in um
        self.dut_threshold = [0] * self.n_duts  # Detection threshold for each device in electrons, influences efficiency!
        self.dut_noise = [50] * self.n_duts  # Noise for each device in electrons
        self.dut_pixel_size = [(50, 50)] * self.n_duts  # Pixel size for each device in x / y in um
        self.dut_n_pixel = [(1000, 1000)] * self.n_duts  # Number of pixel for each device in x / y
        self.dut_efficiencies = [1.] * self.n_duts  # Efficiency for each device from 0. to 1. for hits above threshold

        # Digitization settings
        self.digitization_charge_sharing = True
        self.digitization_sigma_cc = 1.35  # Correction factor for charge cloud sigma(z) to take into account also repulsion; for further info see NIMA 606 (2009) 508-516

        # Internals
        self._hit_dtype = np.dtype([('event_number', np.int64), ('frame', np.uint8), ('column', np.uint16), ('row', np.uint16), ('charge', np.uint16)])

    def reset(self):
        self.set_std_settings()
        self._hit_files = None

    def create_data_and_store(self, base_file_name, n_events, chunk_size=100000):
        logging.info('Simulate %d events with %d DUTs', n_events, self.n_duts)
        # Create output h5 files with emtpy hit ta
        output_files = []
        hit_tables = []
        for dut_index in range(self.n_duts):
            output_files.append(tb.open_file(base_file_name + '_DUT%d.h5' % dut_index, 'w'))
            hit_tables.append(output_files[dut_index].createTable(output_files[dut_index].root, name='Hits', description=self._hit_dtype, title='Simulated hits for test beam analysis', filters=tb.Filters(complib='blosc', complevel=5, fletcher32=False)))

        progress_bar = progressbar.ProgressBar(widgets=['', progressbar.Percentage(), ' ', progressbar.Bar(marker='*', left='|', right='|'), ' ', progressbar.AdaptiveETA()], maxval=len(range(0, n_events, chunk_size)), term_width=80)
        progress_bar.start()
        # Fill output files in chunks
        for chunk_index, _ in enumerate(range(0, n_events, chunk_size)):
            actual_events, actual_digitized_hits = self._create_data(start_event_number=chunk_index * chunk_size, n_events=chunk_size)
            for dut_index in range(self.n_duts):
                actual_dut_events, actual_dut_hits = actual_events[dut_index], actual_digitized_hits[dut_index]
                actual_hits = np.zeros(shape=actual_dut_events.shape[0], dtype=self._hit_dtype)
                actual_hits['event_number'] = actual_dut_events
                actual_hits['column'] = actual_dut_hits.T[0]
                actual_hits['row'] = actual_dut_hits.T[1]
                actual_hits['charge'] = actual_dut_hits.T[2] / 10.  # One charge LSB corresponds to 10 electrons
                hit_tables[dut_index].append(actual_hits)
            progress_bar.update(chunk_index)
        progress_bar.finish()

        for output_file in output_files:
            output_file.close()

    def _create_tracks(self, n_tracks):
        '''Creates tracks with gaussian distributed angles at gaussian distributed positions at z=0.

        Parameters
        ----------
        n_tracks: number
            Number of tracks created

        Returns
        -------
        Four np.arrays with position x,y and angles phi, theta
        '''

        logging.debug('Create %d tracks at x/y = (%d/%d +- %d/%d) um and theta = (%d +- %d) mRad', n_tracks, self.beam_position[0], self.beam_position[1], self.beam_position_sigma[0], self.beam_position_sigma[1], self.beam_angle, self.beam_angle_sigma)

        if self.beam_angle / 1000. > np.pi or self.beam_angle / 1000. < 0:
            raise ValueError('beam_angle has to be between [0..pi] Rad')

        if self.beam_position_sigma[0] != 0:
            track_positions_x = np.random.normal(self.beam_position[0], self.beam_position_sigma[0], n_tracks)

        else:
            track_positions_x = np.repeat(self.beam_position[0], repeats=n_tracks)  # Constant x = mean_x

        if self.beam_position_sigma[1] != 0:
            track_positions_y = np.random.normal(self.beam_position[1], self.beam_position_sigma[0], n_tracks)

        else:
            track_positions_y = np.repeat(self.beam_position[1], repeats=n_tracks)  # Constant y = mean_y

        if self.beam_angle_sigma != 0:
            track_angles_theta = np.abs(np.random.normal(self.beam_angle / 1000., self.beam_angle_sigma / 1000., size=n_tracks))  # Gaussian distributed theta
        else:  # Allow sigma = 0
            track_angles_theta = np.repeat(self.beam_angle / 1000., repeats=n_tracks)  # Constant theta = 0

        # Cut down to theta = 0 .. Pi
        while(np.any(track_angles_theta > np.pi) or np.any(track_angles_theta < 0)):
            track_angles_theta[track_angles_theta > np.pi] = np.random.normal(self.beam_angle, self.beam_angle_sigma, size=track_angles_theta[track_angles_theta > np.pi].shape[0])
            track_angles_theta[track_angles_theta < 0] = np.random.normal(self.beam_angle, self.beam_angle_sigma, size=track_angles_theta[track_angles_theta < 0].shape[0])

        track_angles_phi = np.random.random(size=n_tracks) * 2 * np.pi  # Flat distributed phi = [0, Pi[

        return track_positions_x, track_positions_y, track_angles_phi, track_angles_theta

    def _create_hits_from_tracks(self, track_positions_x, track_positions_y, track_angles_phi, track_angles_theta):
        '''Creates exact intersection points (x, y) at the given DUT z_positions for the given tracks. The tracks are defined with with the position at z = 0 (track_positions_x, track_positions_y) and
        an angle (track_angles_phi, track_angles_theta).

        Returns
        -------
        Two np.arrays with position, angle
        '''
        logging.debug('Intersect tracks with DUTs to create hits')

        intersections = []
        track_positions = np.column_stack((track_positions_x, track_positions_y))  # Track position at z = 0
        for z_position in self.z_positions:
            r = z_position / np.cos(track_angles_theta)  # r in spherical coordinates at actual z_position
            extrapolate = (r * np.array([np.cos(track_angles_phi) * np.sin(track_angles_theta), np.sin(track_angles_phi) * np.sin(track_angles_theta)])).T
            intersections.append(track_positions + extrapolate)
        return intersections

    def _digitize_hits(self, event_number, hits):
        ''' Takes the Monte Carlo hits and transfers them to the local DUT coordinate system and discretizes the position and creates additional hit belonging to a cluster.'''
        logging.debug('Digitize hits')
        digitized_hits = []
        event_numbers = []  # The event number index can be different for each DUT due to noisy pixel and charge sharing hits

        for dut_index, dut_hits in enumerate(hits):  # Loop over DUTs
            # Transform hits position into pixel array
            dut_hits -= np.array(self.offsets[dut_index])  # Add DUT offset
            dut_hits_digits = np.zeros(shape=(dut_hits.shape[0], 3))  # Create new array with additional charge column
            dut_hits_digits[:, :2] = dut_hits / np.array(self.dut_pixel_size[dut_index])  # Position in pixel numbers
            dut_hits_digits[:, :2] = np.around(dut_hits_digits[:, :2] - 0.5) + 1  # Pixel discretization, column/row index start from 1
            dut_hits_digits[:, 2] = self._get_charge_deposited(dut_index, n_entries=dut_hits.shape[0])  # Fill charge column

            actual_event_number = event_number

            # Create cluster from seed hits arising from charge sharing
            if self.digitization_charge_sharing:
                relative_position = dut_hits - (dut_hits_digits[:, :2] - 0.5) * self.dut_pixel_size[dut_index]  # Calculate the relative position within the pixel, origin is in the center
                dut_hits_digits, n_hits_per_event = _add_charge_sharing_hits(relative_position.T,
                                                                             hits_digits=dut_hits_digits,
                                                                             max_column=self.dut_n_pixel[dut_index][0],
                                                                             max_row=self.dut_n_pixel[dut_index][1],
                                                                             thickness=self.dut_thickness[dut_index],
                                                                             pixel_size_x=self.dut_pixel_size[dut_index][0],
                                                                             pixel_size_y=self.dut_pixel_size[dut_index][1],
                                                                             temperature=self.temperature,
                                                                             bias=self.dut_bias[dut_index])
                actual_event_number = np.repeat(actual_event_number, n_hits_per_event)

            # Mask hits outside of the DUT
            selection_x = np.logical_and(dut_hits_digits.T[0] > 0, dut_hits_digits.T[0] <= self.dut_n_pixel[dut_index][0])  # Hits that are inside the x dimension of the DUT
            selection_y = np.logical_and(dut_hits_digits.T[1] > 0, dut_hits_digits.T[1] <= self.dut_n_pixel[dut_index][1])  # Hits that are inside the y dimension of the DUT
            selection = np.logical_and(selection_x, selection_y)
            dut_hits_digits = dut_hits_digits[selection]  # reduce hits to valid hits
            actual_event_number = actual_event_number[selection]  # Reducce event number to event number with valid hits

            # Mask hits due to inefficiency
            selection = np.ones_like(actual_event_number, dtype=np.bool)
            hit_indices = np.arange(actual_event_number.shape[0])  # Indices of hits
            np.random.shuffle(hit_indices)  # shuffle these indeces
            n_inefficient_hit = int(hit_indices.shape[0] * (1. - self.dut_efficiencies[dut_index]))
            selection[hit_indices[:n_inefficient_hit]] = False

            dut_hits_digits = dut_hits_digits[selection]
            actual_event_number = actual_event_number[selection]

            # Add noise to charge
            dut_hits_digits[:, 2] += np.random.normal(0, self.dut_noise[dut_index], dut_hits_digits[:, 2].shape[0])

            # Delete hits below threshold
            actual_event_number = actual_event_number[dut_hits_digits[:, 2] >= self.dut_threshold[dut_index]]
            dut_hits_digits = dut_hits_digits[dut_hits_digits[:, 2] >= self.dut_threshold[dut_index]]

            # Append results
            digitized_hits.append(dut_hits_digits)
            event_numbers.append(actual_event_number)

        return (event_numbers, digitized_hits)

    def _create_data(self, start_event_number=0, n_events=10000):
        # Calculate the number of tracks per event
        n_tracks_per_event = np.random.normal(self.tracks_per_event, self.tracks_per_event_sigma, n_events).astype(np.int)
        n_tracks_per_event[n_tracks_per_event < 0] = 0  # One cannot have less than 0 tracks per event, this will be triggered events without a track

        # Create event number
        events = np.arange(n_events)
        event_number = np.repeat(events, n_tracks_per_event).astype(np.int64)  # Create an event number of events with tracks
        event_number += start_event_number

        # Create tracks
        track_positions_x, track_positions_y, track_angles_phi, track_angles_theta = self._create_tracks(n_tracks_per_event.sum())

        # Create MC hits
        hits = self._create_hits_from_tracks(track_positions_x, track_positions_y, track_angles_phi, track_angles_theta)

        # Create detector response: digitized hits
        hits_digitized = self._digitize_hits(event_number, hits)
        return hits_digitized

    def _get_charge_deposited(self, dut_index, n_entries, eta=0.2):
        ''' Calculates the charge distribution wich is approximated by a Landau and returns n_entries random samples from this
        distribution. The device thickness defines the MPV 

        '''
        x = np.arange(0, 10, 0.1)
        y = landau.landau(x, mu=1. - 0.22278298, eta=eta)  # MPV is at mu + 0.22278298; eta is different according to the device thickness; this is neglected here
        p = y / np.sum(y)  # Propability
        mpv = 77 * self.dut_thickness[dut_index]
        charge = x * mpv

        return np.random.choice(charge, n_entries, p=p)

if __name__ == '__main__':
    simulate_data = SimulateData(0)
    simulate_data.digitization_charge_sharing = False
    simulate_data.create_data_and_store('simulated_data', n_events=1000000)


#     x = np.arange(0, 10, 0.1)
# y = landau.landau(x, mu=1. - 0.22278298, eta=0.2)  # MPV is at mu + 0.22278298; eta is different according to the device thickness; this is neglected here
# p = y / np.sum(y)  # Propability
#     mpv = 77 * 100
#     charge = x * mpv
#
#
#     c = np.random.choice(charge, 1000, p=p)
#
#
# #
# plt.plot(x, y)
#     plt.hist(c, bins=1000, range=(charge[0], charge[-1]))
#     plt.show()


# TEST: Plot charge sharing
#     import matplotlib.pyplot as plt
#     from matplotlib import cm
#     from mpl_toolkits.mplot3d.axes3d import Axes3D
#     from itertools import product, combinations
#     import mpl_toolkits.mplot3d.art3d as art3d
#     from matplotlib.patches import Circle, PathPatch, Rectangle
#     from matplotlib.widgets import Slider, Button, RadioButtons
#
#     simulate_data.digitization_sigma_cc = 1.
#     simulate_data.dut_pixel_size = [(50, 250)] * simulate_data.n_duts
#     simulate_data.dut_bias = [60] * simulate_data.n_duts
#
#     x_min, x_max, y_min, y_max, dx, dy = -150, 150, -150, 150, 4, 4
#
#     fig = plt.figure(figsize=(14, 6))
#     ax = fig.gca(projection='3d')
# l = ax.plot_wireframe(x_grid, y_grid, simulate_data._calc_charge_fraction(dut_index=0, position=(x_grid, y_grid), z=200, pixel_index=(0, 0)), label='cdf', color='blue', alpha=0.3)
#     x, y, z = [], [], []
#
#     for ix in np.arange(x_min, x_max, dx):
#         for iy in np.arange(y_min, y_max, dy):
#             x.append(ix)
#             y.append(iy)
#             z.append(_calc_charge_fraction(position_x=ix, position_y=iy, position_z=200, pixel_index_x=0, pixel_index_y=0, pixel_size_x=50, pixel_size_y=50, temperature=300, bias=60, digitization_sigma_cc=1.))
#     ax.plot(x, y, z, label='cdf', color='blue', alpha=0.3)
#
#     x, y, z = [], [], []
#     for ix in np.arange(x_min, x_max, dx):
#         for iy in np.arange(y_min, y_max, dy):
#             x.append(ix)
#             y.append(iy)
#             z.append(_calc_charge_fraction(position_x=ix, position_y=iy, position_z=200, pixel_index_x=1, pixel_index_y=0, pixel_size_x=50, pixel_size_y=50, temperature=300, bias=60, digitization_sigma_cc=1.))
#     ax.plot(x, y, z, label='cdf', color='red', alpha=0.3)
#     plt.show()