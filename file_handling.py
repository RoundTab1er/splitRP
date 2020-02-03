import configparser
import numpy as np
import os.path
import copy
import cv2


# Public Functions
def resource_path(relative_path): return os.path.join(os.path.abspath("."), relative_path)


def xywh2dict(x, y, w, h): return {'left': x, 'top': y, 'width': w, 'height': h}


def dict2xywh(d): return [d["left"], d["top"], d["width"], d["height"]]


def processing(img, color=None, resize=None, crop=None):
    if crop is not None:
        img = img[crop["top"]:crop["top"] + crop["height"], crop["left"]:crop["left"] + crop["width"]]
    if color is not None:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if type(color) is int:
            (thresh, img) = cv2.threshold(img, color, 255, cv2.THRESH_BINARY)
    if resize is not None:
        img = cv2.resize(img, None, None, resize[0], resize[1], cv2.INTER_AREA)
    return img


# Classes
class Test:
    def __init__(self, name, image_paths, match_per, unmatch_per, crop_area=None, resize=None, color_proc=None):
        self.name = name
        self.image_paths = image_paths
        self.match_percent = match_per
        self.unmatch_percent = unmatch_per
        self.crop_area = copy.copy(crop_area)
        self.resize = [resize, resize] if resize is not None and type(resize) is not list else resize
        self.color_proc = color_proc
        self.images = []

    def conform_crop(self, area):       # Adjust self.crop_area relative to 'area' given.
        if self.crop_area is not None:
            if area["left"] + area["width"] > self.crop_area["left"] >= area["left"]:
                self.crop_area["left"] -= area["left"]
            else:
                self.crop_area["left"] = 0
            if area["top"] + area["height"] > self.crop_area["top"] >= area["top"]:
                self.crop_area["top"] -= area["top"]
            else:
                self.crop_area["top"] = 0
        else:
            self.crop_area = xywh2dict(0, 0, area["width"], area["height"])

    def load_images(self, area, scale):
        self.conform_crop(area)
        if self.resize is not None:
            self.resize = np.divide(self.resize, scale)
        self.images = []
        for file in self.image_paths:
            img = cv2.imread(resource_path(file), 1)
            img = img[area["top"]: area["top"] + area["height"], area["left"]: area["left"] + area["width"]]
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            img = cv2.resize(img, None, None, scale[0], scale[1], cv2.INTER_AREA)
            self.images.append(processing(img, self.color_proc, self.resize, self.crop_area))


class TestPack:
    def __init__(self, name, match_tests, match_send='', unmatch_packs=None, nomatch_pack=None, nomatch_send=''):
        self.name = name
        self.match_tests = match_tests
        self.match_send = match_send
        self.unmatch_packs = unmatch_packs
        self.nomatch_pack = nomatch_pack
        self.nomatch_send = nomatch_send


class FileAccess:
    def __init__(self, filename):
        self.cfg = configparser.ConfigParser(inline_comment_prefixes="#")
        self.cfg.read_file(open(resource_path(filename)))

        self.resolution = [int(n) for n in self.cfg["Settings"]["NativeResolution"].replace(" ", "").split("x")]
        self.master_crop = xywh2dict(
            *[int(n) for n in self.cfg["Settings"]["ScreenshotArea"].replace(" ", "").replace(":", ",").split(",")])
        self.directory = f"images\\{self.cfg['Settings']['ImageDirectory'].strip()}\\"
        self.runlog = int(self.cfg["Settings"]["RunLogging"].strip())

        self.tests = {}
        for test in [s.strip() for s in self.cfg["Settings"]["Tests"].strip().split(",")]:
            self.tests[test] = self.build_test(test)

        self.test_packs = {}
        for pack in [s.strip() for s in self.cfg["Settings"]["TestPacks"].strip().split(",")]:
            self.test_packs[pack] = self.build_pack(pack)
        self.first_pack = self.test_packs[self.cfg["Settings"]["FirstPack"].strip()]

    def init_packs(self):       # Can this be part of TestPack class?
        for name, pack in self.test_packs.items():
            if pack.unmatch_packs is not None:
                for p in range(0, len(pack.unmatch_packs), 1):
                    pack.unmatch_packs[p] = self.test_packs[pack.unmatch_packs[p]]
            pack.nomatch_pack = self.test_packs[pack.nomatch_pack] if pack.nomatch_pack is not None else pack
        self.first_pack = self.test_packs[self.cfg["Settings"]["FirstPack"].strip()]

    def build_test(self, name):
        imgs = [self.directory + s.strip() for s in self.cfg[name]["Images"].strip().split("|")]
        match = float(self.cfg[name]["Match"].strip())
        unmatch = float(self.cfg[name]["Unmatch"].strip())

        if "Crop" in self.cfg[name].keys():
            crop = xywh2dict(*[int(n) for n in self.cfg[name]["Crop"].replace(" ", "").replace(":", ",").split(",")])
        else:
            crop = None

        resize = float(self.cfg[name]["Resize"].strip()) if "Resize" in self.cfg[name].keys() else None

        if "Color" in self.cfg[name].keys():
            color = [s.strip().lower() for s in self.cfg[name]["Color"].split(":")]
            if color[0] == "thresh" and len(color) > 1:
                try:
                    color = int(color[1])
                except:
                    color = None
            elif color[0] != "gray" and color[0] != "grey":
                color = None
        else:
            color = None

        return Test(name, imgs, match, unmatch, crop, resize, color)

    def build_pack(self, name):
        match = [self.tests[s.strip()] for s in self.cfg[name]["Match"].split(",")]
        unmatch = [s.strip() for s in self.cfg[name]["Unmatch"].split(",")] if "UnMatch" in self.cfg[name].keys()\
            else None
        nomatch = self.cfg[name]["NoMatch"].strip() if "NoMatch" in self.cfg[name].keys() else None
        match_send = self.cfg[name]["MatchSend"].strip().replace("\\r\\n", "\r\n") \
            if "MatchSend" in self.cfg[name].keys() else ''
        nomatch_send = self.cfg[name]["NoMatchSend"].strip().replace("\\r\\n", "\r\n") \
            if "NoMatchSend" in self.cfg[name].keys() else ''

        return TestPack(name, match, match_send, unmatch, nomatch, nomatch_send)

    def convert(self, resolution):
        def scale(screen_dict, h, w):
            coords = dict2xywh(screen_dict)
            return xywh2dict(int(coords[0] * w), int(coords[1] * h), int(coords[2] * w), int(coords[3] * h))

        if resolution["height"] != self.resolution[1] or resolution["width"] != self.resolution[0]:
            print("Resizing values to different resolution.")
            dif_h = resolution["height"] / self.resolution[1]
            dif_w = resolution["width"] / self.resolution[0]
            self.master_crop = scale(self.master_crop, dif_h, dif_w)

            if '{0:.3f}'.format(dif_h) != '{0:.3f}'.format(dif_w):
                print("[Warning: Screen resolution does not match aspect ratio of tests.\r\n"
                      "          No guarantees on this working.]")
        else:
            dif_h, dif_w = 1.0, 1.0
        for test in self.tests.values():
            test.load_images(self.master_crop, [dif_w, dif_h])
