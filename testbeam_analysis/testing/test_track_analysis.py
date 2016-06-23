''' Script to check the correctness of the analysis. The analysis is done on raw data and all results are compared to a recorded analysis.
'''
import os

import unittest

from testbeam_analysis import track_analysis
from testbeam_analysis.tools import test_tools

# Get package path
testing_path = os.path.dirname(__file__)  # Get the absoulte path of the online_monitor installation

# Set the converter script path
tests_data_folder = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(testing_path)) + r'/testing/test_track_analysis/'))


class TestTrackAnalysis(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if os.name != 'nt':
            try:
                from xvfbwrapper import Xvfb  # virtual X server for plots under headless LINUX travis testing is needed
                cls.vdisplay = Xvfb()
                cls.vdisplay.start()
            except (ImportError, EnvironmentError):
                pass
        cls.output_folder = tests_data_folder
        cls.pixel_size = (250, 50)  # in um

    @classmethod
    def tearDownClass(cls):  # remove created files
        os.remove(os.path.join(cls.output_folder, 'TrackCandidates.h5'))
        os.remove(os.path.join(cls.output_folder, 'TrackCandidates_2.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks.pdf'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_2.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_2.pdf'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_All.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_All.pdf'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_All_Iter.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_All_Iter.pdf'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_merged.h5'))
        os.remove(os.path.join(cls.output_folder, 'Tracks_merged.pdf'))

    def test_track_finding(self):
        track_analysis.find_tracks(input_tracklets_file=os.path.join(tests_data_folder, 'Tracklets_small.h5'),
                                   input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                   output_track_candidates_file=os.path.join(self.output_folder, 'TrackCandidates.h5'))
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'TrackCandidates_result.h5'), os.path.join(self.output_folder, 'TrackCandidates.h5'))
        self.assertTrue(data_equal, msg=error_msg)
        track_analysis.find_tracks(input_tracklets_file=os.path.join(tests_data_folder, 'Tracklets_small.h5'),
                                   input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                   output_track_candidates_file=os.path.join(self.output_folder, 'TrackCandidates_2.h5'),
                                   chunk_size=293)
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'TrackCandidates_result.h5'), os.path.join(self.output_folder, 'TrackCandidates_2.h5'))
        self.assertTrue(data_equal, msg=error_msg)

    def test_track_fitting(self):
        # Test 1: Fit DUTs and always exclude one DUT (normal mode for unbiased residuals and efficiency determination)
        track_analysis.fit_tracks(input_track_candidates_file=os.path.join(tests_data_folder, 'TrackCandidates_result.h5'),
                                  input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                  output_tracks_file=os.path.join(self.output_folder, 'Tracks.h5'),
                                  fit_duts=None,
                                  include_duts=[-3, -2, -1, 1, 2, 3],
                                  ignore_duts=None,
                                  track_quality=1,
                                  use_correlated=False)
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'Tracks_result.h5'), os.path.join(self.output_folder, 'Tracks.h5'), exact=False)
        self.assertTrue(data_equal, msg=error_msg)

        # Test 2: As test 1 but chunked data analysis, should result in the same tracks
        track_analysis.fit_tracks(input_track_candidates_file=os.path.join(tests_data_folder, 'TrackCandidates_result.h5'),
                                  input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                  output_tracks_file=os.path.join(self.output_folder, 'Tracks_2.h5'),
                                  fit_duts=None,
                                  include_duts=[-3, -2, -1, 1, 2, 3],
                                  ignore_duts=None,
                                  track_quality=1,
                                  use_correlated=False,
                                  chunk_size=4999)
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'Tracks_result.h5'), os.path.join(self.output_folder, 'Tracks_2.h5'), exact=False)
        self.assertTrue(data_equal, msg=error_msg)

        # Test 3: Fit all DUTs at once (special mode for constrained residuals)
        track_analysis.fit_tracks(input_track_candidates_file=os.path.join(tests_data_folder, 'TrackCandidates_result.h5'),
                                  input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                  output_tracks_file=os.path.join(self.output_folder, 'Tracks_All.h5'),
                                  fit_duts=None,
                                  include_duts=None,
                                  ignore_duts=None,
                                  track_quality=1,
                                  use_correlated=False)
        # Fit DUTs consecutevly, but use always the same DUTs. Should result in the same data as above
        track_analysis.fit_tracks(input_track_candidates_file=os.path.join(tests_data_folder, 'TrackCandidates_result.h5'),
                                  input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                  output_tracks_file=os.path.join(self.output_folder, 'Tracks_All_Iter.h5'),
                                  fit_duts=None,
                                  include_duts=[-3, -2, -1, 0, 1, 2, 3],
                                  ignore_duts=None,
                                  track_quality=1,
                                  use_correlated=False)
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'Tracks_All.h5'), os.path.join(self.output_folder, 'Tracks_All_Iter.h5'), exact=False)
        self.assertTrue(data_equal, msg=error_msg)

        # Fit tracks and eliminate merged tracks
        track_analysis.fit_tracks(input_track_candidates_file=os.path.join(tests_data_folder, 'TrackCandidates_result.h5'),
                                  input_alignment_file=os.path.join(tests_data_folder, r'Alignment_result.h5'),
                                  output_tracks_file=os.path.join(self.output_folder, 'Tracks_merged.h5'),
                                  fit_duts=None,
                                  include_duts=[-3, -2, -1, 1, 2, 3],
                                  ignore_duts=None,
                                  track_quality=1,
                                  use_correlated=False,
                                  min_track_distance=True  # Activate track merge cut
                                  )
        data_equal, error_msg = test_tools.compare_h5_files(os.path.join(tests_data_folder, 'Tracks_merged_result.h5'), os.path.join(self.output_folder, 'Tracks_merged.h5'), exact=False)
        self.assertTrue(data_equal, msg=error_msg)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTrackAnalysis)
    unittest.TextTestRunner(verbosity=2).run(suite)