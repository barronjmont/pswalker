################################################################################
#                                  Skywalker                                   #
################################################################################

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import cv2
import numpy as np
import matplotlib.pyplot as plt

from tqdm import tqdm
from psp.Pv import Pv
from joblib import Memory
from beamDetector.detector import Detector
from walker.iterwalk import IterWalker
from simtrace import run_sim
from utils.cvUtils import to_uint8, plot_image
from multiprocessing import Process
# from joblib import Memory

# cachedir = "cache"
# mem = Memory(cachedir=cachedir, verbose=0)
N = 256

################################################################################
#                                Imager Class                                  #
################################################################################

class Imager(object):
    """
    Imager object that will encapsulate the various yag screens along the
    beamline.
    """

    def __init__(self, x, z, **kwargs):
        self.x = x
        self.z = z
        self.detector = kwargs.get("det", Detector(prep_mode="clip"))
        self.image    = None
        self.centroid = None
        self.bounding_box = None
        self.pos = np.array([self.z, self.x])
        self._scale = None
        self.sum = None
        self.beam = False
        # self.image_sz = kwargs.get("img_sz", 0.0005)
        self.mppix = kwargs.get("mppix", None)

    def get(self):
        """Get an image from the imager."""
        try:
            uint_norm = to_uint8(self.image, "norm")
            self._scale = self.image.sum() / self.sum
            # print(self._scale)
            # import IPython; IPython.embed()
            # import ipdb; ipdb.set_trace()
            return to_uint8(uint_norm * self._scale, "clip")
        except TypeError:
            self.sum = self.image.sum()
            return self.get()

    def get_centroid(self):
        """Return the centroid of the image."""
        # if self.detector.beam_is_present(self.image):
        try:
            self.centroid, self.bounding_box = self.detector.find(self.get())
            self.beam = True
            return self.centroid
        except IndexError:
            self.beam = False
            return None
        # else:
        #     raise ValueError

        
################################################################################
#                                 Mirror Class                                 #
################################################################################

class Mirror(object):
    """
    Mirror class to encapsulate the two HOMS (or any) mirrors.
    """

    def __init__(self, x, alpha, z):
        self.x = x
        self.alpha = alpha
        self.z = z
        self.pos = np.array([self.z, self.x])

################################################################################
#                                 Source Class                                 #
################################################################################

class Source(object):
    def __init__(self, x, xp, y, yp, z):
        self.x  = x
        self.xp = xp
        self.y  = y
        self.yp = yp
        self.z = z
        self.pos = np.array([self.z, self.x])
    
################################################################################
#                               Helper Functions                               #
################################################################################

def put_val(pv, val):
    try:
        pv.put(float(val))
    except ValueError:
        print("Invalid input type. Must be castable to float.")    

def distance(x1, x2):
    return np.linalg.norm(x2-x1)

def inch2meter(val):
    return val * 0.0254

def move_seq(seq, do_plot=False):
    for s in tqdm(seq):
        m1h_alpha = s[0]
        m1h.alpha = s[0]
        m2h_alpha = s[1]
        m2h.alpha = s[1]
        simulator(p2h, p3h, dg3, und_x, und_xp, und_y, und_yp, und_z, m1h_x, 
                  m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, m2h_z, 
                  p3h_x, p3h_z, dg3_x, dg3_z, mx, my, ph_e)
        plt.close("all")
        if do_plot:
	        imagers = Process(target=plot, args=(p2h, p3h, dg3, p1, p2, m1h, m2h))
	        imagers.start()

def scan_for_beam(seq, imager, do_plot=False):
    for s in seq:
        m1h_alpha = s[0]
        m1h.alpha = s[0]
        m2h_alpha = s[1]
        m2h.alpha = s[1]
        simulator(p2h, p3h, dg3, und_x, und_xp, und_y, und_yp, und_z, m1h_x, 
                  m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, m2h_z, 
                  p3h_x, p3h_z, dg3_x, dg3_z, mx, my, ph_e)
        if do_plot: 
            imagers = Process(target=plot,args=(p2h, p3h, dg3, p1, p2, m1h, m2h))
            imagers.start()
        centroid = imager.get_centroid()
        if centroid is not None:
            print("Seq: {0}, Centroid: {1}".format(s, centroid))
            plot_image(imager.get())
            break

def solve_alpha_1(x0, xp0, d2, d3, xm1h, xp2h):
    return (-d3*xp0 - x0 + 2*xm1h - xp2h)/(2*(d2 - d3))

def solve_alpha_2(x0, xp0, d2, d4, d5, a1, xm1h, xm2h, xp3h):
    return (a1*d2 - a1*d5 + d5*xp0/2 + x0/2 - xm1h + xm2h + xp3h/2)/(d4 - d5)

################################################################################
#                              Simulator Functions                             #
################################################################################

# @mem.cache
def sim_wrapper(mx, my, energy, fee_slit_x, fee_slit_y, lhoms, x0, x0p, y0p, 
                m1h_x, m1h_z, m1h_a, p2h_x, p2h_z, m2h_x, m2h_z, m2h_a, p3h_x, 
                p3h_z, dg3_x, dg3_z):
    return run_sim(mx, my, energy, fee_slit_x, fee_slit_y, lhoms, x0, x0p, y0p, 
                   m1h_x, m1h_z, m1h_a, p2h_x, p2h_z, m2h_x, m2h_z, m2h_a, p3h_x, 
                   p3h_z, dg3_x, dg3_z)

def simulator(imager1, imager2, imager3, und_x, und_xp, und_y, und_yp, und_z, 
              m1h_x, m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, m2h_z, 
              p3h_x, p3h_z, dg3_x, dg3_z, mx, my, ph_e):
    # image1, image2, image3 = sim_wrapper(
    #     mx, my, ph_e, 100, 100, 1.0, und_x, und_xp, und_yp, m1h_x, m1h_z, 
    #     m1h_alpha, m2h_x, m2h_z, p2h_x, p2h_z, m2h_alpha, p3h_x, p3h_z, dg3_x, 
    #     dg3_z)
    image1, image2, image3 = run_sim(mx, my, ph_e, 10, 10, und_x, und_xp, m1h_x, 
                                     m1h_alpha, m2h_x, m2h_alpha, 5, und_yp)
    
    imager1.image = np.array(image1).T
    imager2.image = np.array(image2).T
    imager3.image = np.array(image3).T
    # imager2.image = np.array(image2).T[:,::-1]
    # imager3.image = np.array(image3).T[:,::-1]

    imager1.sum = imager1.image.sum()
    imager2.sum = imager1.image.sum()
    imager3.sum = imager1.image.sum()

    # import ipdb; ipdb.set_trace()

    # import IPython; IPython.embed()

def plot(imager1, imager2, imager3, p1, p2, m1h, m2h, centroid=True, r=2):
    # import ipdb; ipdb.set_trace()
    fig = plt.figure(figsize=(4, 12))
    fig.suptitle('Beam Images', fontsize=20)
    ax = fig.add_subplot(311)
    ax.imshow(imager1.get())
    plt.title('P2H (M1H Alpha: {0}'.format(m1h.alpha))
    if centroid:
        centroid_1 = imager1.get_centroid()
        if centroid_1 is not None:
            circ = plt.Circle(imager1.get_centroid(), radius=r, color='black')
            ax.add_patch(circ)
            plt.text(0.95, 0.05, "Centroid: {0}".format(imager1.centroid), 
                     ha='right', va='center', color='w', transform=ax.transAxes)
        else:
            plt.text(0.95, 0.05, "No Beam Found", ha='right', va='center', 
                     color='w', transform=ax.transAxes)
    plt.grid()

    bx = fig.add_subplot(312)
    bx.imshow(imager2.get())
    plt.title('P3H (M2H Alpha: {0}'.format(m2h.alpha))
    if centroid:
        centroid_2 = imager2.get_centroid()
        if centroid_2 is not None:
            circ = plt.Circle(imager2.get_centroid(), radius=r, color='black')
            bx.add_patch(circ)
            plt.text(0.95, 0.05, "Centroid: {0}".format(imager2.centroid), 
                     ha='right', va='center', color='w', transform=bx.transAxes)
        else:
            plt.text(0.95, 0.05, "No Beam Found", ha='right', va='center', 
                     color='w', transform=bx.transAxes)
    plt.axvline(x=p1, linestyle='--')
    plt.grid()

    cx = fig.add_subplot(313)
    cx.imshow(imager3.get())
    plt.title('DG3')
    if centroid:
        centroid_3 = imager3.get_centroid()
        if centroid_3 is not None:
            circ = plt.Circle(imager3.get_centroid(), radius=r, color='black')
            cx.add_patch(circ)
            plt.text(0.95, 0.05, "Centroid: {0}".format(imager3.centroid), 
                     ha='right', va='center', color='w', transform=cx.transAxes)
        else:
            plt.text(0.95, 0.05, "No Beam Found", ha='right', va='center', 
                     color='w', transform=cx.transAxes)        
    plt.axvline(x=p2, linestyle='--')
    plt.grid()
    # plt.draw()
    plt.show()
    

################################################################################
#                                     Main                                     #
################################################################################

if __name__ == "__main__":
    
    nom = 0.0014
    # Initial Conditions
    # Undulator Vals
    und_x = 0
    und_xp = 0
    und_y = 0
    und_yp = 0
    und_z = 0

    # M1H Vals
    m1h_x = 0
    m1h_alpha = 0
    m1h_z = 90.510

    # P2H Vals
    p2h_x = 0.0
    p2h_z = 100.828

    # M2H Vals
    m2h_x = 0
    m2h_alpha =  0
    m2h_z = 101.843

    # P3H Vals
    p3h_x =  0.0
    p3h_z = 103.660

    # DG3 Vals
    dg3_x = 0
    dg3_z = 375.000

    # Simulation values
    mx = 1201
    my = 301
    ph_e = 7000

    # Goal Pixels
    p1 = 0.0306
    p2 = 0.0306
    alpha = 0

    # Reset to Zero
    p2h_x = 0.
    m1h_alpha = 0
    m2h_alpha = 0.00


    # Additional
    # m1h_alpha = solve_alpha_1(und_x, und_xp, m1h_z, p2h_z, m1h_x, p2h_x) + nom - np.pi/2
    # m2h_alpha = solve_alpha_2(und_x, und_xp, m1h_z, m2h_z, p3h_z, m1h_alpha,  m1h_x,  m2h_x, p3h_x) + nom - np.pi/2
# x0, xp0, d2, d4, d5, a1, xm1h, xm2h, xp3h
    do_plot=True

    
    # Detector Obj
    det_p23h = Detector(kernel=(9,9), threshold=9.0)
    det_dg3 = Detector(kernel=(11,11), threshold=6.0)


    # Beamline Objects
    # Undulator
    undulator = Source(und_x, und_xp, und_y, und_yp, und_z)
    # M1H
    m1h = Mirror(m1h_x, m1h_alpha, m1h_z)
    # P2H
    p2h = Imager(p2h_x, p2h_z, det=det_p23h)
    # M2H
    m2h = Mirror(m2h_x, m2h_alpha, m2h_z)
    # P3H
    p3h = Imager(p3h_x, p3h_z, det=det_p23h)
    # DG3
    dg3 = Imager(dg3_x, dg3_z, det=det_dg3)

    # Walker Object
    walker = IterWalker(undulator, m1h, m2h, p3h, dg3, p1=p1, p2=p2)

    # from IPython import embed; embed()

    # # Alignment procedure

    # # Initial Positions
    # simulator(p2h, p3h, dg3, und_x, und_xp, und_y, und_yp, und_z, m1h_x, 
    #           m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, m2h_z, p3h_x, 
    #           p3h_z, dg3_x, dg3_z, mx, my, ph_e)
    # plot(p2h, p3h, dg3, p1, p2, m1h, m2h)
    # # import IPython; IPython.embed()


    # Move beam through sequence
    # No beam in range [3.333e-7 * i for i in range(-90, 90, 3)
    # Beam moves close to no amount for this range. -90 gives x still in the 400
    # range. Otherwise issue is that the beam is still not not
    # showing itself on p3h or dg3, but it is present on p2h.
    n_seq = 2
    alpha_1 = 0
    alpha_2 = 1e-6
    alpha_1_seq = [alpha_1 * i for i in range(n_seq)] 
    alpha_2_seq = [alpha_2 * i for i in range(n_seq)] 
    seq = zip(alpha_1_seq[:n_seq], alpha_2_seq[:n_seq])
    # scan_for_beam(seq, p3h, do_plot=True)
    move_seq(seq, do_plot=True)    
    # from IPython import embed; embed()

    # for s in seq:
    #     m1h_alpha = s[0]
    #     m1h.alpha = s[0]
    #     m2h_alpha = s[1]
    #     m2h.alpha = s[1]
    #     simulator(p2h, p3h, dg3, und_x, und_xp, und_y, und_yp, und_z, m1h_x, 
    #               m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, m2h_z, 
    #               p3h_x, p3h_z, dg3_x, dg3_z, mx, my, ph_e)
    #     plot(p2h, p3h, dg3, p1, p2, m1h, m2h,)

    # # Walk beam to Center 
    # try:
    #     while True:
    #         alpha, turn = walker.step()
    #         print("\nNew alpha {0} for {1}".format(alpha, turn))
    #         print("M1H: {0} M2H: {1}".format(m1h.alpha, m2h.alpha))
    #         print("D1: {0} D2: {1}".format(walker._d1_x, walker._d2_x))            
    #         if turn == "alpha1":
    #             m1h_alpha = alpha
    #             m1h.alpha = alpha
    #         elif turn == "alpha2":
    #             m2h_alpha = alpha
    #             m2h.alpha = alpha
    #         simulator(p2h, p3h, dg3, und_x, und_xp, und_y, und_yp, und_z, 
    #                   m1h_x, m1h_alpha, m1h_z, p2h_x, p2h_z, m2h_x, m2h_alpha, 
    #                   m2h_z, p3h_x, p3h_z, dg3_x, dg3_z, mx, my, ph_e)
    #         if do_plot:
    #             plot(p2h, p3h, dg3, p1, p2, m1h, m2h)
    # except StopIteration:
    #     print("Reached End")

    # for i in range(2):



