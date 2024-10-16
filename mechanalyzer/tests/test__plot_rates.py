""" Test the mechanalyzer.plotter.rates functions
"""


import os
import tempfile
import numpy as np
from mechanalyzer.plotter import rates


TMP_DIR = tempfile.mkdtemp()
PLOTFILE_NAME = os.path.join(TMP_DIR, 'rate_comparison.pdf')
print('Temp Run Dir:', TMP_DIR)

TEMPS = np.array([500, 1000, 1500])
KTS = np.array([1e10, 1e11, 1e12])


ALIGNED_RXN_KTP_DCT = {
    (('H2', 'O'), ('OH', 'H'), (None,)): [
        {'high': (TEMPS, KTS), 1: (TEMPS, KTS), 10: (TEMPS, KTS)},
        {'high': (TEMPS, 2*KTS), 10: (TEMPS, 2*KTS)}],

    (('H', 'O2'), ('OH', 'O'), (None,)): [
        {'high': (TEMPS, KTS), 1: (TEMPS, KTS), 10: (TEMPS, KTS)},
        None]
}


def test_build_plots():
    """ Test the build_plots function
    """
    rates.build_plots(
        ALIGNED_RXN_KTP_DCT, filename=PLOTFILE_NAME)


def test_build_plots_ratio_sort():
    """ Test the build_plots function with sorting by ratio
    """
    rates.build_plots(
        ALIGNED_RXN_KTP_DCT, filename=PLOTFILE_NAME, ratio_sort=True)


if __name__ == '__main__':
    test_build_plots()
    test_build_plots_ratio_sort()
