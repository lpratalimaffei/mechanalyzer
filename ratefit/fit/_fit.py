"""
  Fit the rate constants read from the MESS output to
  Arrhenius, Plog, Troe, and Chebyshev expressions
"""

import copy
import mess_io
import ioformat
from ratefit.fit import arrhenius as arrfit
from ratefit.fit import chebyshev as chebfit
from ratefit.fit import troe as troefit
from ratefit.fit._util import filter_ktp_dct
from ratefit.fit._pdep import pressure_dependent_ktp_dct


DEFAULT_PDEP_DCT = {
    'temps': (500.0, 1000.0),
    'tol': 20.0,
    'pval': 1.0,
    'plow': None,
    'phigh': None
}
DEFAULT_ARRFIT_DCT = {
    'dbltol': 15.0,
    'dblcheck': 'max'
}
DEFAULT_TROE_DCT = {
    'params': ('ts1', 'ts2', 'ts3', 'alpha'),
    'tol': 20.0
}
DEFAULT_CHEB_DCT = {
    'tdeg': 6,
    'pdeg': 4,
    'tol': 20.0
}


def fit_ktp_dct(mess_path, inp_fit_method,
                pdep_dct=None,
                arrfit_dct=None,
                chebfit_dct=None,
                troefit_dct=None,
                label_dct=None,
                fit_temps=None, fit_pressures=None,
                fit_tunit='K', fit_punit='atm'):
    """ Parse the MESS output and fit the rates to
        Arrhenius expressions written as CHEMKIN strings
    """

    # Read the mess input and output strings using the path
    mess_out_str = ioformat.pathtools.read_file(mess_path, 'rate.out')

    # Set dictionaries if they are unprovided
    pdep_dct = pdep_dct or DEFAULT_PDEP_DCT
    arrfit_dct = arrfit_dct or DEFAULT_ARRFIT_DCT
    chebfit_dct = chebfit_dct or DEFAULT_CHEB_DCT
    troefit_dct = troefit_dct or DEFAULT_TROE_DCT

    if label_dct is None:
        labels = mess_io.reader.rates.labels(mess_out_str, read_fake=False)
        label_dct = dict(zip(labels, labels))

    # Loop through reactions, fit rates, and write ckin strings
    chemkin_str_dct = {}
    rxn_pairs = gen_reaction_pairs(label_dct)
    for (name_i, lab_i), (name_j, lab_j) in rxn_pairs:

        # Set the name and A conversion factor
        reaction = name_i + '=' + name_j
        print('------------------------------------------------\n')
        print('Reading and Fitting Rates for {}'.format(reaction))

        # Read the rate constants out of the mess outputs
        print('\nReading k(T,P)s from MESS output...')
        ktp_dct, cheb_fit_temps = read_rates(
            mess_out_str, pdep_dct, lab_i, lab_j,
            fit_temps=fit_temps, fit_pressures=fit_pressures,
            fit_tunit=fit_tunit, fit_punit=fit_punit)

        # Check the ktp dct and fit_method to see how to fit rates
        fit_method = _assess_fit_method(ktp_dct, inp_fit_method)

        # Get the desired fits in the form of CHEMKIN strs
        if fit_method is None:
            continue
        if fit_method == 'arrhenius':
            chemkin_str = arrfit.pes(
                ktp_dct, reaction, mess_path, **arrfit_dct)
        elif fit_method == 'chebyshev':
            chemkin_str = chebfit.pes(
                ktp_dct, reaction, mess_path,
                fit_temps=cheb_fit_temps, **chebfit_dct)
            if not chemkin_str:
                chemkin_str = arrfit.pes(
                    ktp_dct, reaction, mess_path, **arrfit_dct)
        elif fit_method == 'troe':
            chemkin_str += troefit.pes(
                ktp_dct, reaction, mess_path, **troefit_dct)

        # Update the chemkin string dct {PES FORMULA: [PES CKIN STRS]}
        print('\nFinal Fitting Parameters in CHEMKIN Format:', chemkin_str)
        ridx = reaction.replace('=', '_')
        chemkin_str_dct.update({ridx: chemkin_str})

    return chemkin_str_dct


def gen_reaction_pairs(label_dct):
    """ Generate pairs of reactions
    """

    rxn_pairs = ()
    for name_i, lab_i in label_dct.items():
        if 'F' not in lab_i and 'B' not in lab_i:
            for name_j, lab_j in label_dct.items():
                if 'F' not in lab_j and 'B' not in lab_j and lab_i != lab_j:
                    rxn_pairs += (((name_i, lab_i), (name_j, lab_j)),)

    # Only grab the forward reactions, remove the reverse reactions
    sorted_rxn_pairs = ()
    for pair in rxn_pairs:
        rct, prd = pair
        if (rct, prd) in sorted_rxn_pairs or (prd, rct) in sorted_rxn_pairs:
            continue
        sorted_rxn_pairs += ((rct, prd),)

    return sorted_rxn_pairs


# Readers
def read_rates(mess_out_str, pdep_dct, rct_lab, prd_lab,
               fit_temps=None, fit_pressures=None,
               fit_tunit=None, fit_punit=None):
    """ Read the rate constants from the MESS output and
        (1) filter out the invalid rates that are negative or undefined
        and obtain the pressure dependent values
    """

    # Initialize vars
    ktp_dct = {}
    bimol = bool('W' not in rct_lab)

    # Read temperatures, pressures and rateks from MESS output
    mess_temps, tunit = mess_io.reader.rates.temperatures(mess_out_str)
    mess_press, punit = mess_io.reader.rates.pressures(mess_out_str)

    fit_temps = fit_temps if fit_temps is not None else mess_temps
    fit_pressures = fit_pressures if fit_pressures is not None else mess_press
    fit_tunit = fit_tunit if fit_tunit is not None else tunit
    fit_punit = fit_punit if fit_punit is not None else punit

    fit_temps = list(set(list(fit_temps)))
    fit_temps.sort()
    assert set(fit_temps) <= set(mess_temps)
    assert set(fit_pressures) <= set(mess_press)

    # Read all k(T,P) values from MESS output; filter negative/undefined values
    calc_ktp_dct = mess_io.reader.rates.ktp_dct(
        mess_out_str, rct_lab, prd_lab)
    print(
        '\nRemoving invalid k(T,P)s from MESS output that are either:\n',
        '  (1) negative, (2) undefined [***], or (3) below 10**(-21) if',
        'reaction is bimolecular')
    filt_ktp_dct = filter_ktp_dct(calc_ktp_dct, bimol)

    # Filter the ktp dictionary by assessing the presure dependence
    if filt_ktp_dct:
        if list(filt_ktp_dct.keys()) == ['high']:
            print('\nValid k(T)s only found at High Pressure...')
            ktp_dct['high'] = filt_ktp_dct['high']
        else:
            if pdep_dct:
                print(
                    '\nUser requested to assess pressure dependence',
                    'of reaction.')
                ktp_dct = pressure_dependent_ktp_dct(filt_ktp_dct, **pdep_dct)
            else:
                ktp_dct = copy.deepcopy(filt_ktp_dct)

    return ktp_dct, fit_temps


def _assess_fit_method(ktp_dct, inp_fit_method):
    """ Assess if there are any rates to fit and if so, check if
        the input fit method should be used, or just simple Arrhenius
        fits will suffice because there is only one pressure for which
        rates exist to be fit.

        # If only one pressure (outside HighP limit), just run Arrhenius
    """

    if ktp_dct:
        pressures = list(ktp_dct.keys())
        npressures = len(pressures)
        if npressures == 1 or (npressures == 2 and 'high' in pressures):
            fit_method = 'arrhenius'
        else:
            fit_method = inp_fit_method
    else:
        fit_method = None

    # Print message to say what fitting will be done
    if fit_method == 'arrhenius':
        if inp_fit_method != 'arrhenius':
            print(
                '\nRates at not enough pressures for Troe/Chebyshev.')
        print(
            '\nFitting k(T,P)s to PLOG/Arrhenius Form....')
    elif fit_method == 'chebyshev':
        print(
            '\nFitting k(T,P)s to Chebyshev Form...')
    elif fit_method == 'troe':
        print(
            '\nFitting k(T,P)s to Tree Form...')
    elif fit_method is None:
        print(
            '\nNo valid k(T,Ps)s from MESS output to fit.',
            'Skipping to next reaction...')

    return fit_method
