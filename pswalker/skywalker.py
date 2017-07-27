#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from threading import Lock

import numpy as np
from bluesky import RunEngine
from bluesky.plans import (checkpoint, plan_mutator, null, run_decorator,
                           abs_set)
from bluesky.callbacks import LiveTable
from pcdsdevices.epics.pim import PIM
from pcdsdevices.epics.mirror import OffsetMirror

from .plan_stubs import recover_threshold, prep_img_motors
from .suspenders import (BeamEnergySuspendFloor, BeamRateSuspendFloor,
                         PvAlarmSuspend, LightpathSuspender)
from .iterwalk import iterwalk
from .utils.argutils import as_list

logger = logging.getLogger(__name__)


def branching_plan(plan, branches, branch_choice, branch_msg='checkpoint'):
    """
    Plan that allows deviations from the original plan at checkpoints.

    Parameters
    ----------
    plan: iterable
        Iterable that returns Msg objects as in a Bluesky plan

    branches: list of functions
        Functions that return valid plans. These are the deviations we may take
        when plan yields a checkpoint.

    branch_choice: function
        Function that tells us which branch to take. This must return None when
        we want to continue to normal plan and an integer that matches an index
        in branches when we want to deviate.

    branch_msg: str, optional
        Which message to branch on. By default, this is checkpoint.
    """
    def do_branch():
        choice = branch_choice()
        if choice is None:
            yield null()
        else:
            branch = branches[choice]
            logger.debug("Switching to branch %s", choice)
            yield from branch()

    # No nested branches
    branch_lock = Lock()

    def branch_handler(msg):
        if msg.command == branch_msg:
            nonlocal branch_lock
            has_lock = branch_lock.acquire(blocking=False)
            if has_lock:
                try:
                    def new_gen():
                        nonlocal branch_lock
                        with branch_lock:
                            if branch_choice() is not None:
                                yield from checkpoint()
                                yield from do_branch()
                                logger.debug("Resuming plan after branch")
                            yield msg
                finally:
                    branch_lock.release()
                    return new_gen(), None
        return None, None

    brancher = plan_mutator(plan, branch_handler)
    return (yield from brancher)


def lcls_RE(alarming_pvs=None, RE=None):
    """
    Instantiate a run engine that pauses when the lcls beam has problems, and
    optionally when various PVs enter a MAJOR alarm state.

    Parameters
    ----------
    alarming_pvs: list of str, optional
        If provided, we'll suspend the run engine when any of these PVs report
        a MAJOR alarm state.

    RE: RunEngine, optional
        If provided, we'll add suspenders to and return the provided RunEngine
        instead of creating a new one.

    Returns
    -------
    RE: RunEngine
    """
    RE = RE or RunEngine({})
    RE.install_suspender(BeamEnergySuspendFloor(0.01))
    RE.install_suspender(BeamRateSuspendFloor(2))
    alarming_pvs = alarming_pvs or []
    for pv in alarming_pvs:
        RE.install_suspender(PvAlarmSuspend(pv, "MAJOR"))
    RE.msg_hook = RE.log.debug
    return RE


m1h = "MIRR:FEE1:M1H"
m1h_xy = "STEP:M1H"
m1h_gan_x = "STEP:FEE1:611:MOTR"
m1h_name = "m1h"
m2h = "MIRR:FEE1:M2H"
m2h_xy = "STEP:M2H"
m2h_gan_x = "STEP:FEE1:861:MOTR"
m2h_name = "m2h"
m3h = "MIRR:XRT:M2H"
m3h_xy = "XRT:M2H"
m3h_gan_x = "GANTRY:XRT:M2H"
m3h_name = "xrtm2"
hx2 = "HX2:SB1:PIM"
hx2_name = "hx2"
dg3 = "HFX:DG3:PIM"
dg3_name = "dg3"
mfxdg1 = "MFX:DG1:PIM"
mfxdg1_det = "MFX:DG1:P6740"
mfxdg1_name = "mfxdg1"
mecy1 = "MEC:PIM1"
mecy1_det = "MEC:HXM:CVV:01"
mecy1_name = "mecy1"
pitch_key = "pitch"
cent_x_key = "detector_stats2_centroid_y"
fmt = "{}_{}"
m1h_pitch = fmt.format(m1h_name, pitch_key)
m2h_pitch = fmt.format(m2h_name, pitch_key)
hx2_cent_x = fmt.format(hx2_name, cent_x_key)
dg3_cent_x = fmt.format(dg3_name, cent_x_key)


def homs_RE():
    """
    Instantiate an lcls_RE with the correct alarming pvs and a suspender for
    lightpath blockage.

    Returns
    -------
    RE: RunEngine
    """
    # Subscribe a LiveTable to the HOMS stuff
    RE = lcls_RE()
    RE.subscribe('all', LiveTable([m1h_pitch, m2h_pitch,
                                   hx2_cent_x, dg3_cent_x]))
    # TODO determine what the correct alarm pvs even are
    # TODO include lightpath suspender
    return RE


def homs_system():
    """
    Instantiate the real mirror and yag objects from the real homs system, and
    pack them into a dictionary.

    Returns
    -------
    system: dict
    """
    system = {}
    system['m1h'] = OffsetMirror(m1h, m1h_xy, m1h_gan_x, name=m1h_name)
    system['m1h2'] = OffsetMirror(m1h, m1h_xy, m1h_gan_x, name=m1h_name+"2")
    system['m2h'] = OffsetMirror(m2h, m2h_xy, m2h_gan_x, name=m2h_name)
    system['m2h2'] = OffsetMirror(m2h, m2h_xy, m2h_gan_x, name=m2h_name+"2")
    system['xrtm2'] = OffsetMirror(m3h, m3h_xy, m3h_gan_x, name=m3h_name)
    system['xrtm22'] = OffsetMirror(m3h, m3h_xy, m3h_gan_x, name=m3h_name+"2")
    system['hx2'] = PIM(hx2, name=hx2_name)
    system['dg3'] = PIM(dg3, name=dg3_name)
    system['mfxdg1'] = PIM(mfxdg1, det_pv=mfxdg1_det, name=mfxdg1_name)
    system['mecy1'] = PIM(mecy1, det_pv=mecy1_det, name=mecy1_name)
    system['y1'] = system['hx2']
    system['y2'] = system['dg3']
    return system


def get_thresh_signal(yag):
    """
    Given a yag object, return the signal we'll be using to determine if the
    yag has beam on it.
    """
    return yag.detector.stats2.centroid.y


def make_homs_recover(yags, yag_index, motor, threshold, center=0,
                      get_signal=get_thresh_signal):
    """
    Make a recovery plan for a particular yag/motor combination in the homs
    system.
    """
    def homs_recover():
        sig = get_signal(yags[yag_index])
        if motor.position < center:
            dir_init = 1
        else:
            dir_init = -1

        def plan():
            yield from prep_img_motors(yag_index, yags, timeout=10)
            yield from recover_threshold(sig, threshold, motor, dir_init,
                                         timeout=120, has_stop=False)
        return (yield from plan())

    return homs_recover


def make_pick_recover(yag1, yag2, threshold):
    """
    Make a function of zero arguments that will determine if a recovery plan
    needs to be run, and if so, which plan to use.
    """
    def pick_recover():
        return None
        num = 25
        sigs = []
        if yag1.position == "IN":
            for i in range(num):
                sig = get_thresh_signal(yag1)
                sigs.append(sig)
            if max(sigs) < threshold[0]:
                return 0
            else:
                return None
        elif yag2.position == "IN":
            for i in range(num):
                sig = get_thresh_signal(yag2)
                sigs.append(sig)
            if max(sigs) < threshold[1]:
                return 1
            else:
                return None

    return pick_recover


def skywalker(detectors, motors, det_fields, mot_fields, goals,
              first_steps=1,
              gradients=None, tolerances=20, averages=20, timeout=600,
              branches=None, branch_choice=lambda: None, md=None):
    """
    Iterwalk as a base, with arguments for branching
    """
    _md = {'goals'     : goals,
           'detectors' : [det.name for det in as_list(detectors)],
           'mirrors'   : [mot.name for mot in as_list(motors)],
           'plan_name' : 'homs_skywalker',
           'plan_args' : dict(goals=goals, gradients=gradients,
                              tolerances=tolerances, averages=averages,
                              timeout=timeout, det_fields=as_list(det_fields),
                              mot_fields=as_list(mot_fields),
                              first_steps=first_steps)
          }
    _md.update(md or {})

    @run_decorator(md=_md)
    def letsgo():
        walk = iterwalk(detectors, motors, goals, first_steps=first_steps,
                        gradients=gradients,
                        tolerances=tolerances, averages=averages, timeout=timeout,
                        detector_fields=det_fields, motor_fields=mot_fields,
                        system=detectors + motors)
        return (yield from branching_plan(walk, branches, branch_choice))


    return (yield from letsgo())

def get_lightpath_suspender(yags):
    # TODO initialize lightpath
    # Make the suspender to go to the last yag and exclude prev yags
    return LightpathSuspender(yags[-1], exclude=yags[:-1])


def homs_skywalker(goals, y1='y1', y2='y2', gradients=None, tolerances=5,
                   averages=100, timeout=600, has_beam_floor=[0.1, 0.1], md=None,
                   first_steps=0.0001):
    """
    Skywalker with homs-specific devices and recovery methods
    """
    if gradients is None:
        gradients = [-4000, 32000]
    system = homs_system()
    if isinstance(y1, str):
        y1 = system[y1]
    if isinstance(y2, str):
        y2 = system[y2]
    m1h = system['m1h']
    m2h = system['m2h']
    m1h.low_limit = -150
    m1h.high_limit = 250
    m2h.low_limit = -290
    m2h.high_limit = 110
    m1 = m1h
    m2 = m2h
    recover_m1 = make_homs_recover([y1, y2], 0, m1h, 0.1, center=239.98)
    recover_m2 = make_homs_recover([y1, y2], 1, m2h, 0.1, center=102.37)
    choice = make_pick_recover(y1, y2, has_beam_floor)

    _md = {'goals': goals,
           'detectors': [y1.name, y2.name],
           'mirrors': [m1.name, m2.name],
           'plan_name': 'homs_skywalker',
           'plan_args': dict(goals=goals, y1=repr(y1), y2=repr(y2),
                             gradients=gradients, tolerances=tolerances,
                             averages=averages, timeout=timeout,
                             has_beam_floor=has_beam_floor,
                             first_steps=first_steps)
          }
    _md.update(md or {})
    goals = [480 - g for g in goals]

    @run_decorator(md=_md)
    def letsgo():
        #for yag in (y1, y2):
        #    try:
        #        if not np.isclose(yag.zoom.position, 25):
        #            yield from abs_set(yag.zoom, 25)
        #    except AttributeError:
        #        logger.error()
        #        pass
        return (yield from skywalker([y1, y2], [m1h, m2h], cent_x_key,
                                     pitch_key, goals,
                                     gradients=gradients,
                                     tolerances=tolerances, averages=averages,
                                     timeout=timeout,
                                     branches=[recover_m1, recover_m2],
                                     branch_choice=choice,
                                     first_steps=first_steps))
    return (yield from letsgo())
