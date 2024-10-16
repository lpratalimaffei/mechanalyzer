"""
  Therm Calculations
"""

import os
import math
import multiprocessing
import random
import automol.inchi
import automol.geom
from phydat import phycon
from mechanalyzer.inf import rxn as rinfo
import thermfit.cbh


# Set up the references for building
def prepare_refs(ref_scheme, spc_dct, spc_names,
                 repeats=False, parallel=False, zrxn=None):
    """ Generate all of the reference (basis) species for
        a list of species. Will also generate needed info
        if it does not exist.

    add refs to species list as necessary
    """

    if parallel:
        nproc_avail = len(os.sched_getaffinity(0)) - 1

        num_spc = len(spc_names)
        spc_per_proc = math.floor(num_spc / nproc_avail)

        queue = multiprocessing.Queue()
        procs = []
        random.shuffle(spc_names)
        for proc_n in range(nproc_avail):
            spc_start = proc_n*spc_per_proc
            if proc_n == nproc_avail - 1:
                spc_end = num_spc
            else:
                spc_end = (proc_n+1)*spc_per_proc

            spc_lst = spc_names[spc_start:spc_end]

            proc = multiprocessing.Process(
                target=_prepare_refs,
                args=(queue, ref_scheme, spc_dct, spc_lst,
                      repeats, parallel, zrxn))
            procs.append(proc)
            proc.start()

        basis_dct = {}
        unique_refs_dct = {}
        for _ in procs:
            bas_dct, unq_dct = queue.get()
            basis_dct.update(bas_dct)
            bas_ichs = [
                unique_refs_dct[spc]['inchi']
                if 'inchi' in unique_refs_dct[spc]
                else unique_refs_dct['reacs']
                for spc in unique_refs_dct]
            for spc in unq_dct:
                new_ich = (
                    unq_dct[spc]['inchi']
                    if 'inchi' in unq_dct[spc] else unq_dct[spc]['reacs'])
                if new_ich not in bas_ichs:
                    cnt = len(list(unique_refs_dct.keys())) + 1
                    if isinstance(new_ich, str):
                        ref_name = 'REF_{}'.format(cnt)
                        unique_refs_dct[ref_name] = unq_dct[spc]
                    else:
                        ref_name = 'TS_REF_{}'.format(cnt)
                        unique_refs_dct[ref_name] = unq_dct[spc]
        for proc in procs:
            proc.join()
    else:
        basis_dct, unique_refs_dct = _prepare_refs(
            None, ref_scheme, spc_dct, spc_names,
            repeats=repeats, parallel=parallel,
            zrxn=zrxn)

    return basis_dct, unique_refs_dct


def _prepare_refs(queue, ref_scheme, spc_dct, spc_names,
                  repeats=False, parallel=False, zrxn=None):
    """ Prepare references
    """

    print(
        'Processor {} will prepare species: {}'.format(
            os.getpid(), ', '.join(spc_names)))
    spc_ichs = [spc_dct[spc]['inchi'] for spc in spc_names]
    dct_ichs = [spc_dct[spc]['inchi'] for spc in spc_dct.keys()
                if spc != 'global' and 'ts' not in spc]

    # Print the message
    msg = '\nDetermining reference molecules for scheme: {}'.format(ref_scheme)
    msg += '\n'

    basis_dct = {}
    unique_refs_dct = {}
    for spc_name, spc_ich in zip(spc_names, spc_ichs):

        # Build the basis set and coefficients for spc/TS
        msg += '\nDetermining basis for species: {}'.format(spc_name)
        if zrxn is not None:
            rcls = automol.reac.reaction_class(zrxn)
            if rcls in thermfit.cbh.CBH_TS_CLASSES:
                scheme = ref_scheme
            else:
                scheme = 'basic'
            if '_' in scheme:
                scheme = 'cbh' + scheme.split('_')[1]
            spc_basis, coeff_basis = thermfit.cbh.ts_basis(
                zrxn, scheme)
        else:
            spc_basis, coeff_basis = thermfit.cbh.species_basis(
                spc_ich, ref_scheme)
        spc_basis = tuple(automol.inchi.add_stereo(bas) for bas in spc_basis
                          if isinstance(bas, str))

        msg += '\nInCHIs for basis set:'
        for base in spc_basis:
            msg += '\n  {}'.format(base)

        # Add to the dct containing info on the species basis
        basis_dct[spc_name] = (spc_basis, coeff_basis)

        # Add to the dct with reference dct if it is not in the spc dct
        for ref in spc_basis:
            bas_ichs = [
                unique_refs_dct[spc]['inchi']
                if 'inchi' in unique_refs_dct[spc] else
                unique_refs_dct[spc]['reacs']
                for spc in unique_refs_dct]
            cnt = len(list(unique_refs_dct.keys())) + 1
            if isinstance(ref, str):
                if ((ref not in spc_ichs and ref not in dct_ichs)
                        or repeats) and ref not in bas_ichs:
                    ref_name = 'REF_{}'.format(cnt)
                    msg += (
                        '\nAdding reference species {}, InChI string:{}'
                    ).format(ref, ref_name)
                    unique_refs_dct[ref_name] = create_spec(ref)
            else:
                if _chk(ref, spc_ichs, dct_ichs, bas_ichs, repeats):
                    ref_name = 'TS_REF_{}'.format(cnt)
                    msg += (
                        '\nAdding reference species {}, InChI string:{}'
                    ).format(ref, ref_name)
                    unique_refs_dct[ref_name] = create_ts_spc(
                        ref, spc_dct, spc_dct[spc_name]['mult'],
                        rcls)
    print(msg)

    ret = None
    if parallel:
        queue.put((basis_dct, unique_refs_dct))
    else:
        ret = (basis_dct, unique_refs_dct)

    return ret


def create_ts_spc(ref, spc_dct, mult, rxnclass):
    """ add a ts species to the species dictionary
    """

    # Obtain the Reaction InChIs, Charges, Mults
    reacs, prods = ref[0], ref[1]
    rxn_ichs = (
        tuple(automol.inchi.add_stereo(ich) for ich in reacs if ich),
        tuple(automol.inchi.add_stereo(ich) for ich in prods if ich)
    )

    rxn_muls, rxn_chgs = (), ()
    for rgts in (reacs, prods):
        rgt_muls, rgt_chgs = (), ()
        for rgt in rgts:
            found = False
            for name in spc_dct:
                if 'inchi' in spc_dct[name]:
                    if spc_dct[name]['inchi'] == rgt:
                        rgt_muls += (spc_dct[name]['mult'],)
                        rgt_chgs += (spc_dct[name]['charge'],)
                        found = True
                        break
            if not found:
                new_spc = create_spec(rgt)
                rgt_muls += (new_spc['mult'],)
                rgt_chgs += (new_spc['charge'],)
        rxn_muls += (rgt_muls,)
        rxn_chgs += (rgt_chgs,)

    return {
        'reacs': list(reacs),
        'prods': list(prods),
        'charge': 0,
        'inchi': '',
        'class': rxnclass,
        'mult': mult,
        'ts_locs': (0,),
        'rxn_info': rinfo.from_data(rxn_ichs, rxn_chgs, rxn_muls, mult)
    }


def create_spec(ich, charge=0,
                mc_nsamp=(True, 3, 1, 3, 100, 12),
                hind_inc=30.):
    """ add a species to the species dictionary
    """
    rad = automol.formula.electron_count(automol.inchi.formula(ich)) % 2
    mult = 1 if not rad else 2

    return {
        'inchi': ich,
        'inchikey': automol.inchi.inchi_key(ich),
        'sens': 0.0,
        'charge': charge,
        'mult': mult,
        'mc_nsamp': mc_nsamp,
        'hind_inc': hind_inc * phycon.DEG2RAD
    }


# Helpers
def _chk(ref, spc_ichs, dct_ichs, bas_ichs, repeats):
    """ a """

    ini = (
        ((ref not in spc_ichs and ref not in dct_ichs) or repeats) and
        (ref not in bas_ichs)
    )
    rref = ref[::-1]
    sec = (
        ((rref not in spc_ichs and rref not in dct_ichs) or repeats) and
        (ref not in bas_ichs[::-1])
    )

    return ini or sec
