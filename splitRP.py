import time
import socket
from select import select as select
import mss
import mss.tools
import keyboard
from file_handling import *


#   ~~~Define Public Functions~~~
def compare(img1, img2):
    composite = cv2.absdiff(img1, img2)         # Composite images into difference map.
    shape = np.shape(composite)                 # [Pixel height, width, (color channels)]
    color_channels = 1 if len(shape) == 2 else shape[2]
    depth = 255         # depth needs to be resolved based on data type? (uint8 = 255, float = 1?)
    similarity = 100 * (1 - ((np.sum(composite) / depth) / (shape[0] * shape[1] * color_channels)))

    return similarity


#   ~~~Define Classes~~~
class LivesplitClient(socket.socket):
    def __init__(self, host=None, port=16834, timeout=3):
        self.host, self.port = None, None
        self.connected = False
        self._lastattempt = time.time() - timeout
        self.attempt = 1

        if host is not None:
            self.connect(host, port, timeout)

    def connect(self, host, port=16834, timeout=3):
        if time.time() - self._lastattempt > timeout:
            if self.connected: self.close()
            super().__init__(socket.AF_INET, socket.SOCK_STREAM)
            self.setblocking(False)

            self.connect_ex((host, port))
            ready_to_read, ready_to_write, in_error = select([], [self], [], 0)
            if not ready_to_write:
                self.connected = False
                self._lastattempt = time.time()
                self.attempt += 1
            else:
                self.host, self.port = host, port
                self.connected = True
                self.attempt = 1
                self.setblocking(True)
        return self.connected

    def send(self, *args):
        try:
            super().send(*args)
        except:
            self.connected = False
            return False
        return True

    def recv(self, *args):
        try:
            out = super().recv(*args).decode()
        except:
            out = "Dead Jim"
            self.connected = False
        return out


class Timer:
    def __init__(self, max_stored=250):
        self.slowest = 0.0
        self.started = time.time()
        self._began = None

        self._durations = [0] * max_stored
        self._dur_pointer = 0
        self._dur_count = 0

    def clear(self):
        self._durations = [0] * len(self._durations)
        self._dur_pointer = 0
        self._dur_count = 0
        self.restart()

    def restart(self):
        self.started = time.time()
        self.slowest = 0.0
        self._began = None

    def start(self):
        self.started = time.time()
        self._began = self.started

    def stop(self):
        self.split()
        self._began = None

    def split(self):
        t = time.time()
        if self._began is None:
            self._began = t
            # self.started = t
            return 0.0
        else:
            dur = t - self._began
            if dur > self.slowest:
                self.slowest = dur
            self._durations[self._dur_pointer] = dur

            dur_len = len(self._durations) - 1
            self._dur_pointer = self._dur_pointer + 1 if self._dur_pointer < dur_len else 0
            if self._dur_count < dur_len:
                self._dur_count += 1

            self._began = t
            return dur

    def avg(self, of_last=None):
        if of_last is None or of_last > self._dur_count or of_last < 1:
            s = sum(self._durations)
            c = self._dur_count
        else:
            c = of_last
            if of_last > self._dur_pointer:
                s = sum(self._durations[0:self._dur_pointer]) + sum(self._durations[-(of_last - self._dur_pointer):])
            else:
                s = sum(self._durations[self._dur_pointer - of_last:self._dur_pointer])
        if c == 0:
            return 1.0
        return s / c

    def now(self):
        if self._began is not None:
            return time.time() - self._began
        else:
            return time.time() - self.started

    def all(self):
        return copy.copy(self._durations)

    def last(self):
        return self._durations[self._dur_pointer-1]

    def active(self):
        return True if self._began is not None else False


class ScreenShot:
    def __init__(self, area=None, monitor=1, *kwargs):
        with mss.mss() as self.sct:
            self.monitor_list = self.sct.monitors
            self.monitor = self.monitor_list[monitor]
            if area is None:
                area = self.monitor
            self.set_crop(area)

    def shot(self):
        return np.array(self.sct.grab(self.cap_area))

    def set_crop(self, area, monitor=None):
        if monitor is not None:
            self.monitor = self.sct.monitors[monitor]
        self.cap_area = xywh2dict(
            self.monitor["left"] + area["left"], self.monitor["top"] + area["top"], area["width"], area["height"]
        )


class Engine:
    def __init__(self):
        self.start = time.time()
        self.img_limit = 120
        self.frame_limit = 60
        self.send_queue = ""
        self.run_log = []
        self.drop_frame = False
        self.log_enabled = settings.verbose
        self.live_run = True

        self.run_timer = Timer()
        self.process_timer = Timer()
        self.shot_timer = Timer()
        self.fps_timer = Timer()

        self.reset()

        # Instantiate keyboard input.
        self.reset_key = settings.reset_key
        self.keys_down = {}
        self.key_hook = keyboard.hook(self.test_hotkey)

        # Wait for first screenshot to be captured:
        self.rawshot = screen.shot()
        while self.rawshot is None:
            pass
        self.lastshot = self.rawshot

        print("Started and ready...")

    def reset(self):
        self.output_log()
        self.write_images()

        self.cur_pack = file.first_pack
        self.cycle = True
        self.split_num = -0.5
        self.frame_count = 0

        self.run_timer.clear()
        self.process_timer.clear()
        self.shot_timer.clear()
        self.fps_timer.restart()

        self.run_log = []

    def send(self):
        if self.send_queue != "":
            livesplit.send(self.send_queue.encode())
            self.send_queue = ""

    def test_hotkey(self, event):
        if event.event_type == keyboard.KEY_DOWN:
            self.keys_down[event.name] = event.scan_code
        elif event.event_type == keyboard.KEY_UP:
            self.keys_down = {}
        if self.live_run:
            if self.keys_down == self.reset_key:
                self.reset()
                print(f"RESET ({self.keys_down})")
            if self.keys_down == settings.video_key:
                self.live_run = False

    def log_action(self, actions, frame, img=None):
        if img is not None:
            img = [self.lastshot, self.rawshot, img]
            self.split_num += .5
        self.run_log.append([self.split_num, actions, frame, time.time(), img])

    def output_log(self):
        if len(self.run_log) != 0:
            last = None
            cnt, dur = 0, 0.0
            whole, fract = 0, 0
            out = "\r\n--- RUN LOG ---\r\n"
            for num, actions, frame, t, imgs in self.run_log:
                if last is not None:
                    cnt = frame - last[2]
                    dur = t - last[3]
                    actions = str(actions).replace("\r\n", "\\r\\n")
                out += f"{num}: [{'{0:.3f}'.format((whole + fract) / self.frame_limit)}] ({whole}|{fract})" \
                       f" on {frame} took {'{0:.3f}'.format(dur)} over" \
                       f" {cnt} ({'{0:.3f}'.format(cnt / self.frame_limit)}) did {actions}\r\n"
                if num >= 1.0:
                    if num % 1 == 0:
                        whole += cnt
                    else:
                        fract += cnt
                last = [num, actions, frame, t]
            print(out + f"FINAL: [{'{0:.3f}'.format((whole + fract) / self.frame_limit)}] ({whole + fract}) - "
                        f"In: {'{0:.3f}'.format(whole / self.frame_limit)} ({whole}), "
                        f"Out: {'{0:.3f}'.format(fract / self.frame_limit)} ({fract}) (times by frame count)"
                        f"\r\n--- END ---\r\n")

    def write_images(self):
        if file.runlog:
            for split, act, frame, t, img_list in self.run_log:
                if img_list is not None:
                    cv2.imwrite(f'runlog/{split}a.png', img_list[0])
                    cv2.imwrite(f'runlog/{split}b.png', img_list[1])
                    if file.runlog == 2:
                        cv2.imwrite(f'runlog/{split}c.png', img_list[2])

    def multi_test(self, tests, match=True, compare_all=False):
        best, worst = 0.0, 100.0
        result = False
        out_shot = None

        for test in tests:
            shot = processing(self.rawshot, test.color_proc, test.resize, test.crop_area)
            if out_shot is None:
                out_shot = shot
            percent = test.match_percent if match else test.unmatch_percent

            for img in test.images:
                if np.shape(img) != np.shape(shot):
                    print("THIS AIN'T GON' WERK!")
                    print(test.name, np.shape(img), np.shape(shot))
                    showImage(img)
                    showImage(shot)
                similarity = compare(img, shot)
                if similarity > best: best = similarity
                if similarity < worst: worst = similarity

                if similarity >= percent:
                    if not compare_all:
                        return [True, best, worst, shot]
                    else:
                        out_shot = shot
                        result = True

        return [result, best, worst, shot]

    def live_analyze(self, cur_match):
        if self.cycle:  # If Matching Cycle...
            if cur_match[0]:  # If match found...
                self.send_queue = self.cur_pack.match_send
                self.run_timer.stop()
                self.cycle = False
                fps = int(1 / self.fps_timer.avg())
                print(f"{int(self.split_num)}: [{'{0:.3f}'.format(self.run_timer.last())}] "
                      f"on {self.frame_count} with {'{0:.2f}'.format(cur_match[1])}% @ "
                      f"{int(1 / self.fps_timer.avg(fps))}fps -- {str.upper(self.cur_pack.name)} "
                      f"'{self.cur_pack.match_send}'".replace("\r\n", "\\r\\n"))
                self.log_action(self.cur_pack.match_send, self.frame_count, cur_match[3])

        elif not cur_match[0]:  # If UnMatch Cycle and no match found
            if self.cur_pack.unmatch_packs is not None:
                for pack in self.cur_pack.unmatch_packs:
                    match = self.multi_test(pack.match_tests)
                    if match[0]:
                        self.send_queue = pack.match_send
                        self.cur_pack = pack
                        print(f"*{pack.name}* ({'{0:.2f}'.format(cur_match[1])}) - Sent '{pack.match_send}'".
                              replace("\r\n", "\\r\\n"))
                        self.log_action(pack.match_send, self.frame_count)
                        return

            self.send_queue = self.cur_pack.nomatch_send
            self.run_timer.start()
            self.cycle = True
            print(f"          - on {self.frame_count} with {'{0:.2f}'.format(cur_match[1])}% - "
                  f"'{self.cur_pack.nomatch_send}'".replace("\r\n", "\\r\\n"))
            self.log_action(self.cur_pack.nomatch_send, self.frame_count, cur_match[3])
            self.cur_pack = self.cur_pack.nomatch_pack

    def mp4_analyze(self, cur_match):
        def acts_to_time(action_list, timer):
            for action in action_list:
                if action == "split" or action == "unpause":
                    timer.split()
                elif action == "pause":
                    timer.stop()
                elif action == "start":
                    timer.start()

        if self.cycle:  # If Matching Cycle...
            if cur_match[0]:  # If match found...
                self.log_action(self.cur_pack.match_actions, self.frame_count, cur_match[3])
                print(f"{self.split_num}: Matched {self.cur_pack.name}")
                self.cycle = False

        elif not cur_match[0]:  # If UnMatch Cycle and no match found
            if self.cur_pack.unmatch_packs is not None:
                for pack in self.cur_pack.unmatch_packs:
                    match = self.multi_test(pack.match_tests)
                    if match[0]:
                        self.log_action(pack.match_actions, self.frame_count)
                        self.cur_pack = pack
                        self.fps_timer.split()
                        print(f"{self.split_num}: Unmatched to {self.cur_pack.name}")
                        return

            self.log_action(self.cur_pack.nomatch_actions, self.frame_count, cur_match[3])
            print(f"{self.split_num}: NoMatched to {self.cur_pack.nomatch_pack.name}")
            self.cycle = True
            self.cur_pack = self.cur_pack.nomatch_pack

    def console_logging(self, cur_match, output=False):
        self.fps_timer.split()
        elapsed = time.time() - self.fps_timer.started
        # Per-second output, if enabled.
        if elapsed >= 1.0:
            fps = int(1 / self.fps_timer.avg())
            if output:
                print(f"{self.cur_pack.name}  ({'{0:.2f}'.format(cur_match[1])}%) "
                      f"- FPS: {'{0:.1f}'.format(1 / self.fps_timer.avg(fps))} "
                      f"({'{0:.2f}'.format(elapsed)})   * Shot: "
                      f"{'{0:.4f}'.format(self.shot_timer.avg())} ({'{0:.5f}'.format(self.shot_timer.slowest)})"
                      f"   * Proc: {'{0:.4f}'.format(self.process_timer.avg())} "
                      f"({'{0:.5f}'.format(self.process_timer.slowest)})")
            # Reset timers per second.
            self.process_timer.clear()
            self.shot_timer.clear()
            self.fps_timer.restart()

    def run_loop(self):
        file.convert(screen.monitor)
        file.init_packs()
        screen.set_crop(file.master_crop)

        while self.live_run:
            self.run()

        # Video processing.
        loc = input("Enter location of video file: ")
        first = input("Start frame? (none for zero): ")
        last = input("Last frame? (none for all): ")
        first = 0 if first == "" else int(first)
        last = None if last == "" else int(last)
        self.video(loc, first, last)

        print("\r\n")
        wait = input("...Press Enter to exit...")

    def run(self):
        self.lastshot = self.rawshot        # Hold previous shot for logging.

        self.shot_timer.start()
        self.rawshot = screen.shot()        # Capture current screenshot. (blocking process)
        self.shot_timer.stop()

        self.send()                         # Send signal to livesplit after screen.shot for timing consistency.

        # Frame limiting only kicks in when average cycle is more than twice the limit. Then drops every other frame.
        if 2 * (self.shot_timer.avg() + self.process_timer.avg()) < 1 / (self.frame_limit + 2):
            self.drop_frame = not self.drop_frame
            if self.drop_frame:
                return

        # Test current screenshot against current test pack.
        self.process_timer.start()
        cur_match = self.multi_test(self.cur_pack.match_tests, self.cycle, True)
        self.live_analyze(cur_match)        # Take action based on cycle and results.
        self.process_timer.stop()

        self.console_logging(cur_match, self.log_enabled)             # Per second logging operations.
        self.frame_count += 1

    def video(self, path, start=0, end=None):
        video = cv2.VideoCapture(path)
        rate = video.get(cv2.CAP_PROP_FPS)
        total_frames = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if end is None or end > total_frames:
            end = total_frames

        total_frames = end - start
        tenth_frames = int(total_frames / 10)
        iter_frames = 1
        self.frame_count = 0

        has_frames, frame = video.read()
        video.set(cv2.CAP_PROP_POS_FRAMES, start)
        res = np.shape(frame)

        vid_file = FileAccess('clustertruck.rp')
        vid_file.convert(xywh2dict(0, 0, res[1], res[0]))
        vid_file.init_packs()
        crop = dict2xywh(vid_file.master_crop)
        self.cur_pack = vid_file.first_pack
        self.frame_limit = rate

        vid_timer = Timer()
        vid_timer.start()
        print(f"Video analysis of {path} containing {total_frames} frames @ {rate}fps now running.\r\n")

        while has_frames and video.get(cv2.CAP_PROP_POS_FRAMES) < end:
            if self.frame_count == tenth_frames * iter_frames:
                print(f"\r\n--- {iter_frames * 10}% Complete - {self.frame_count} of {total_frames}")
                iter_frames += 1
            self.frame_count += 1

            frame = frame[crop[1]:crop[1] + crop[3], crop[0]:crop[0] + crop[2]]
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

            self.rawshot = frame
            cur_match = self.multi_test(self.cur_pack.match_tests, self.cycle, True)
            self.mp4_analyze(cur_match)  # Take action based on cycle and results.

            self.lastshot = frame
            has_frames, frame = video.read()

        vid_timer.stop()
        self.output_log()
        self.write_images()

        def tally_runs():
            rta, igt, waste, first, last, w_last = 0, 0, 0, 0, 0, 0
            out_log = []

            log = copy.copy(self.run_log)
            start = len(log)

            # Discard any events that happen outside the start and final split of each run in the log.
            for x in range(len(self.run_log)-1, -1, -1):
                for action in self.run_log[x][1]:
                    if action == "split":
                        if start is not None:
                            del log[x+1:start]
                            start = None
                    elif action == "start":
                        start = x
            del log[:start]

            # Tally the frame-counts of RTA, IGT, and WASTE timing, for all runs in the log.
            for entry in log:
                for action in entry[1]:
                    frame = entry[2]
                    if action == "split":
                        rta = frame - first
                        igt += frame - last
                        last = frame
                    elif action == "pause":
                        w_last = frame
                    elif action == "unpause":
                        waste += frame - w_last
                        last = frame
                    elif action == "start":
                        if rta != 0:
                            out_log.append([rta, igt, waste])
                        first, last = frame, frame
                        igt, waste, w_last = 0, 0, 0

            out_log.append([rta, igt, waste])
            return out_log

        tally = tally_runs()
        tally_out = "--- SUMMARY ---\r\n"
        for rta, igt, waste in tally:
            tally_out += f"RTA: {'{0:.3f}'.format(rta / rate)}({rta}) " \
                         f"IGT: {'{0:.3f}'.format(igt / rate)}({igt}) " \
                         f"WASTE: {'{0:.3f}'.format(waste / rate)}({waste})"

        print(tally_out + f"\r\nVideo Analysis took: {vid_timer.last()} of duration: {total_frames / rate}")


#   ~~~Instantiate Objects~~~
screen = ScreenShot(monitor=1)

settings = SettingsAccess("settings.cfg")
file = FileAccess('clustertruck.rp')

livesplit = LivesplitClient()
mainloop = Engine()
livesplit.connect("localhost", 16834)

#   ~~~Let's Go!~~~
mainloop.run_loop()
