# roblox_farm.py
# pip install pywin32 mss numpy pynput psutil pydirectinput

import time
import ctypes

import numpy as np
import mss
import psutil
import pydirectinput as pdi

import win32gui
import win32con
import win32process
import winsound
from pynput import keyboard

# ----------------------------
# DEBUG
# ----------------------------
DEBUG = True

def dbg(msg: str):
    if DEBUG:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")

def fmt_bgr(bgr):
    return f"BGR({bgr[0]},{bgr[1]},{bgr[2]})"

def rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"

# ----------------------------
# DPI awareness
# ----------------------------
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ----------------------------
# pydirectinput settings
# ----------------------------
pdi.FAILSAFE = False
pdi.PAUSE = 0.0

# ----------------------------
# Window standardisation
# ----------------------------
WIN_X, WIN_Y = 50, 50
WIN_W, WIN_H = 1280, 720

# ----------------------------
# Click coords (client)
# ----------------------------
TRAINER_CLICK = (669, 224)
TRAINER_SPAM_COUNT = 4
ACCEPT_BATTLE = (981, 290)

FIGHT_CLICK = (836, 537)

# ----------------------------
# Move button coords (client)
# ----------------------------
MOVE1_CLICK = (552, 490)    # top-left
MOVE2_CLICK = (1097, 475)   # top-right
MOVE3_CLICK = (557, 582)    # bottom-left  
MOVE4_CLICK = (1061, 567)  # bottom-right 

END_DIALOGUE_CLICK = (642, 225)

# ----------------------------
# Prompt anchors (colour checks)
# ----------------------------
PROMPT_NO_ANCHOR_XY = (1038, 473)
PROMPT_NO_EXPECTED_RGB = (51, 51, 51)    # #333333

FIGHT_ANCHOR_XY = (836, 537)
FIGHT_EXPECTED_RGB = (102, 38, 38)       # #662626

# Learn move prompt anchor (user requested)
LEARN_L_ANCHOR_XY = (273, 560)
LEARN_L_EXPECTED_RGB = (255, 255, 255)   # #FFFFFF exact

# ----------------------------
# Colour sampling
# ----------------------------
PATCH_RADIUS = 2

NO_COLOR_TOL = 18
FIGHT_COLOR_TOL = 25
LEARN_COLOR_TOL = 10  # tight since you want exact white

# ----------------------------
# PP counts
# ----------------------------
PP_MOVE1 = 20
PP_MOVE2 = 10
PP_MOVE3 = 0
PP_MOVE4 = 5 

# ----------------------------
# Timing + pacing
# ----------------------------
MOVE_TIME = 0.20
POST_CLICK_SLEEP = 0.25  # generic
DIALOGUE_CLICK_DELAY = 0.70

TRAINER_HAS_POKEMON = 4

PROMPT_TIMEOUT_S = 10.0
PROMPT_POLL_S = 0.05
PROMPT_STABLE_HITS = 3

PROMPT_DISAPPEAR_TIMEOUT_S = 3.0
PROMPT_DISAPPEAR_POLL_S = 0.05

BATTLE_DELAY_BONUS_S = 1.0
ACCEPT_TO_FIRST_FIGHT_DELAY_S = 5.0

POST_ACCEPT_SLEEP = 0.60 + BATTLE_DELAY_BONUS_S
POST_FIGHT_SLEEP = 0.40 + BATTLE_DELAY_BONUS_S
POST_MOVE_SLEEP = 1.00 + BATTLE_DELAY_BONUS_S
MOVE_TO_PROMPT_SETTLE = 0.35 + BATTLE_DELAY_BONUS_S
END_BATTLE_SLEEP = 0.60 + BATTLE_DELAY_BONUS_S
DIALOGUE_CLICK_DELAY_BATTLE = DIALOGUE_CLICK_DELAY + BATTLE_DELAY_BONUS_S

# Learn-move transition wait: give the UI time to reach the screen with the L
LEARN_WAIT_TOTAL_S = 2.5
LEARN_WAIT_POLL_S = 0.10

# ----------------------------
# Hotkeys + Pause
# ----------------------------
stop_requested = False
resume_requested = False

paused = False
roblox_hwnd_for_pause = None  # set in main()

PAUSE_POLL_S = 0.05  # how often we poll while paused

was_paused = False

def pause_point():
    """
    Hard pause: blocks here until unpaused or stopped.
    On resume, refocus Roblox exactly once.
    """
    global paused, was_paused

    # If we are paused, block here
    while paused and not stop_requested:
        was_paused = True
        time.sleep(PAUSE_POLL_S)

    # If we just transitioned from paused -> unpaused, refocus once
    if was_paused and not stop_requested:
        was_paused = False
        if roblox_hwnd_for_pause:
            activate_window(roblox_hwnd_for_pause)
        dbg("PAUSE: resumed, refocused Roblox")



def pauseable_sleep(seconds: float):
    """
    Sleep that respects pause and stop.
    Never calls time.sleep() with a negative value.
    """
    end = time.time() + max(0.0, seconds)
    while not stop_requested:
        pause_point()
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))


def on_key_press(key):
    global stop_requested, resume_requested, paused

    if key == keyboard.Key.esc:
        stop_requested = True
        dbg("HOTKEY: ESC pressed, stop_requested=True")
        return False

    if isinstance(key, keyboard.KeyCode):
        if key.char == "0":
            resume_requested = True
            dbg("HOTKEY: 0 pressed, resume_requested=True")

        if key.char and key.char.lower() == "p":
            paused = not paused
            if paused:
                dbg("HOTKEY: P pressed, PAUSED")
                winsound.Beep(700, 120)
                winsound.Beep(700, 120)
            else:
                dbg("HOTKEY: P pressed, UNPAUSED")
                winsound.Beep(1100, 120)


# ----------------------------
# Window helpers
# ----------------------------
def find_roblox_hwnd():
    target_exes = {"RobloxPlayerBeta.exe", "RobloxStudioBeta.exe"}
    candidates = []

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.IsIconic(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe = psutil.Process(pid).name()
        except Exception:
            return

        if exe in target_exes:
            try:
                l, t, r, b = win32gui.GetClientRect(hwnd)
                area = (r - l) * (b - t)
            except Exception:
                area = 0
            candidates.append((area, hwnd))

    win32gui.EnumWindows(enum_cb, None)
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1]


def set_window_rect(hwnd, x, y, w, h):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, x, y, w, h, win32con.SWP_SHOWWINDOW)


def activate_window(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.02)


def get_client_rect_on_screen(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bottom - top
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return sx, sy, w, h


def client_to_screen(hwnd, cx, cy):
    return win32gui.ClientToScreen(hwnd, (int(cx), int(cy)))


# ----------------------------
# Capture + pixel helpers
# ----------------------------
def capture_client_bgr(hwnd, sct):
    pause_point()
    x, y, w, h = get_client_rect_on_screen(hwnd)
    shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
    return np.array(shot)[:, :, :3]  # BGR


def avg_patch_bgr(frame, x, y, r=2):
    h, w = frame.shape[:2]
    x0 = max(0, x - r)
    x1 = min(w - 1, x + r)
    y0 = max(0, y - r)
    y1 = min(h - 1, y + r)
    patch = frame[y0:y1 + 1, x0:x1 + 1]
    bgr = patch.reshape(-1, 3).mean(axis=0)
    return tuple(int(round(v)) for v in bgr.tolist())


def close_bgr(a, b, tol=30):
    return (abs(a[0] - b[0]) <= tol and
            abs(a[1] - b[1]) <= tol and
            abs(a[2] - b[2]) <= tol)


def rgb_to_bgr(rgb):
    r, g, b = rgb
    return (b, g, r)


def sample_patch_at(hwnd, sct, xy):
    frame = capture_client_bgr(hwnd, sct)
    return avg_patch_bgr(frame, xy[0], xy[1], r=PATCH_RADIUS)


def sample_no_bgr(hwnd, sct):
    return sample_patch_at(hwnd, sct, PROMPT_NO_ANCHOR_XY)


def sample_fight_bgr(hwnd, sct):
    return sample_patch_at(hwnd, sct, FIGHT_ANCHOR_XY)


def sample_learn_bgr(hwnd, sct):
    return sample_patch_at(hwnd, sct, LEARN_L_ANCHOR_XY)


def is_no_visible_once(hwnd, sct):
    pause_point()
    got = sample_no_bgr(hwnd, sct)
    expected = rgb_to_bgr(PROMPT_NO_EXPECTED_RGB)
    ok = close_bgr(got, expected, tol=NO_COLOR_TOL)
    if DEBUG:
        dbg(f"CHECK No@{PROMPT_NO_ANCHOR_XY} got {fmt_bgr(got)} expect RGB{PROMPT_NO_EXPECTED_RGB} {rgb_to_hex(PROMPT_NO_EXPECTED_RGB)} tol={NO_COLOR_TOL} -> {ok}")
    return ok


def is_fight_visible_once(hwnd, sct):
    pause_point()
    got = sample_fight_bgr(hwnd, sct)
    expected = rgb_to_bgr(FIGHT_EXPECTED_RGB)
    ok = close_bgr(got, expected, tol=FIGHT_COLOR_TOL)
    if DEBUG:
        dbg(f"CHECK Fight@{FIGHT_ANCHOR_XY} got {fmt_bgr(got)} expect RGB{FIGHT_EXPECTED_RGB} {rgb_to_hex(FIGHT_EXPECTED_RGB)} tol={FIGHT_COLOR_TOL} -> {ok}")
    return ok


def is_learn_move_prompt(hwnd, sct):
    pause_point()
    got = sample_learn_bgr(hwnd, sct)
    expected = rgb_to_bgr(LEARN_L_EXPECTED_RGB)  # white stays white in BGR
    ok = close_bgr(got, expected, tol=LEARN_COLOR_TOL)
    if DEBUG:
        dbg(f"CHECK Learn@{LEARN_L_ANCHOR_XY} got {fmt_bgr(got)} expect RGB{LEARN_L_EXPECTED_RGB} {rgb_to_hex(LEARN_L_EXPECTED_RGB)} tol={LEARN_COLOR_TOL} -> {ok}")
    return ok


# ----------------------------
# Sounds
# ----------------------------
def beep_timeout_alert():
    winsound.Beep(1000, 200)
    pauseable_sleep(1.0)
    winsound.Beep(1000, 200)


def beep_stop_alert():
    winsound.Beep(900, 250)
    pauseable_sleep(0.2)
    winsound.Beep(900, 250)
    pauseable_sleep(0.2)
    winsound.Beep(900, 250)


# ----------------------------
# Clicking with pydirectinput + Roblox desync fix
# ----------------------------
def click_client(hwnd, cx, cy, post_sleep=POST_CLICK_SLEEP, label="CLICK"):
    if stop_requested:
        dbg(f"{label}: stop_requested=True, skipping click at {(cx, cy)}")
        return

    pause_point()

    activate_window(hwnd)
    sx, sy = client_to_screen(hwnd, cx, cy)

    dbg(f"{label}: client={(cx, cy)} screen={(sx, sy)} post_sleep={post_sleep}")

    pdi.moveTo(sx, sy, duration=MOVE_TIME)

    # Roblox cursor recalculation jiggle
    pdi.moveRel(1, 0, duration=0)
    pdi.moveRel(-1, 0, duration=0)

    # Robust click with holds
    pdi.mouseDown()
    pauseable_sleep(0.08)
    pdi.mouseUp()
    pauseable_sleep(0.03)

    pdi.mouseDown()
    pauseable_sleep(0.05)
    pdi.mouseUp()

    pauseable_sleep(post_sleep)


# ----------------------------
# PP logic
# ----------------------------
def choose_move_and_spend_pp(pp1, pp2, pp3, pp4):
    if pp1 > 0:
        return 1, pp1 - 1, pp2, pp3, pp4
    if pp2 > 0:
        return 2, pp1, pp2 - 1, pp3, pp4
    if pp3 > 0:
        return 3, pp1, pp2, pp3 - 1, pp4
    if pp4 > 0:
        return 4, pp1, pp2, pp3, pp4 - 1

    return 0, pp1, pp2, pp3, pp4



def move_xy(move_idx):
    if move_idx == 1:
        return MOVE1_CLICK
    if move_idx == 2:
        return MOVE2_CLICK
    if move_idx == 3:
        return MOVE3_CLICK
    if move_idx == 4:
        return MOVE4_CLICK
    return None


# ----------------------------
# Battle flow
# ----------------------------
def start_trainer_battle(hwnd):
    dbg("STATE: start_trainer_battle")
    for i in range(TRAINER_SPAM_COUNT):
        if stop_requested:
            return
        pause_point()
        click_client(hwnd, *TRAINER_CLICK, post_sleep=POST_CLICK_SLEEP, label=f"TRAINER_CLICK {i+1}/{TRAINER_SPAM_COUNT}")

    click_client(hwnd, *ACCEPT_BATTLE, post_sleep=POST_ACCEPT_SLEEP, label="ACCEPT_BATTLE")
    dbg(f"STATE: waiting for battle load {ACCEPT_TO_FIRST_FIGHT_DELAY_S}s")
    pauseable_sleep(ACCEPT_TO_FIRST_FIGHT_DELAY_S)


def wait_no_visible_stable(hwnd, sct, timeout_s):
    start = time.time()
    hits = 0
    while not stop_requested:
        pause_point()

        if is_no_visible_once(hwnd, sct):
            hits += 1
            dbg(f"STATE: No visible hit {hits}/{PROMPT_STABLE_HITS}")
            if hits >= PROMPT_STABLE_HITS:
                return True
        else:
            if hits != 0:
                dbg("STATE: No not visible, resetting stable hits to 0")
            hits = 0

        if (time.time() - start) >= timeout_s:
            dbg(f"STATE: wait_no_visible_stable timed out after {timeout_s}s")
            return False

        pauseable_sleep(PROMPT_POLL_S)

    return False


def wait_no_disappear(hwnd, sct):
    dbg("STATE: wait_no_disappear")
    start = time.time()
    while not stop_requested and (time.time() - start) < PROMPT_DISAPPEAR_TIMEOUT_S:
        pause_point()
        if not is_no_visible_once(hwnd, sct):
            dbg("STATE: No disappeared")
            return True
        pauseable_sleep(PROMPT_DISAPPEAR_POLL_S)
    dbg("STATE: No did not disappear in time")
    return False


def handle_yesno_if_present(hwnd, sct):
    """
    If No is visible:
      - Wait a bit and repeatedly check for Learn screen (L) so we do not click No too early.
      - If Learn is seen, beep and wait for user to press 0.
      - Else click No and wait for it to disappear.
    """
    global resume_requested

    if stop_requested:
        return False

    pause_point()

    # First check if No exists
    if not is_no_visible_once(hwnd, sct):
        dbg("STATE: handle_yesno_if_present -> No not present")
        return True

    dbg("STATE: handle_yesno_if_present -> No present, checking for Learn screen before clicking No")

    t0 = time.time()
    while not stop_requested and (time.time() - t0) < LEARN_WAIT_TOTAL_S:
        pause_point()

        if is_learn_move_prompt(hwnd, sct):
            dbg("STATE: Learn screen detected, pausing for user")
            winsound.Beep(1400, 200)
            winsound.Beep(900, 200)
            print("[LEARN MOVE] Handle it manually, then press 0 to resume.")

            resume_requested = False
            while not stop_requested and not resume_requested:
                pause_point()
                time.sleep(0.05)
            return not stop_requested

        pauseable_sleep(LEARN_WAIT_POLL_S)

    dbg("STATE: Learn screen NOT detected within wait window, clicking No")
    click_client(hwnd, *PROMPT_NO_ANCHOR_XY, post_sleep=0.40 + BATTLE_DELAY_BONUS_S, label="CLICK_NO")
    wait_no_disappear(hwnd, sct)
    return not stop_requested


def click_end_dialogue(hwnd):
    dbg("STATE: click_end_dialogue")
    for i in range(4):
        if stop_requested:
            return
        pause_point()
        click_client(hwnd, *END_DIALOGUE_CLICK, post_sleep=DIALOGUE_CLICK_DELAY_BATTLE, label=f"END_DIALOGUE {i+1}/4")


def click_fight_if_valid(hwnd, sct):
    if stop_requested:
        return False

    pause_point()

    # Mutual exclusion: if No is on screen, do not click fight
    if is_no_visible_once(hwnd, sct):
        dbg("STATE: Fight blocked because No is visible")
        return False

    if is_fight_visible_once(hwnd, sct):
        click_client(hwnd, *FIGHT_CLICK, post_sleep=POST_FIGHT_SLEEP, label="CLICK_FIGHT")
        return True

    dbg("STATE: Fight not clicked because fight colour check failed")
    return False


def wait_no_then_handle_or_recover(hwnd, sct, last_move_xy):
    alerted = False
    recoveries = 0
    max_recoveries = 2

    dbg("STATE: wait_no_then_handle_or_recover (expecting No prompt)")

    while not stop_requested:
        pause_point()

        if wait_no_visible_stable(hwnd, sct, timeout_s=1.0):
            dbg("STATE: No found after move, handling prompt")
            return handle_yesno_if_present(hwnd, sct)

        if not alerted:
            start = time.time()
            while not stop_requested and (time.time() - start) < PROMPT_TIMEOUT_S:
                pause_point()

                if wait_no_visible_stable(hwnd, sct, timeout_s=0.5):
                    dbg("STATE: No found during extended wait, handling prompt")
                    return handle_yesno_if_present(hwnd, sct)
                pauseable_sleep(PROMPT_POLL_S)

            if stop_requested:
                return False

            dbg("STATE: No not found in time, timeout alert and begin recovery")
            beep_timeout_alert()
            alerted = True

        if recoveries < max_recoveries:
            recoveries += 1
            dbg(f"STATE: Recovery attempt {recoveries}/{max_recoveries}")

            # If No appeared now, handle it
            if is_no_visible_once(hwnd, sct):
                dbg("STATE: No appeared during recovery, handling")
                ok = handle_yesno_if_present(hwnd, sct)
                return ok

            clicked_fight = click_fight_if_valid(hwnd, sct)
            if clicked_fight and not stop_requested:
                mx, my = last_move_xy
                click_client(hwnd, mx, my, post_sleep=POST_MOVE_SLEEP, label="RECOVERY_CLICK_MOVE")
                pauseable_sleep(MOVE_TO_PROMPT_SETTLE)
                alerted = False
                continue

        dbg("STATE: Recovery exhausted, continuing to poll")
        pauseable_sleep(PROMPT_POLL_S)

    return False


def main():
    global stop_requested, roblox_hwnd_for_pause

    dbg("BOOT: starting")

    hwnd = find_roblox_hwnd()
    if not hwnd:
        print("Roblox window not found.")
        return

    roblox_hwnd_for_pause = hwnd
    dbg(f"BOOT: Roblox hwnd={hwnd}")

    set_window_rect(hwnd, WIN_X, WIN_Y, WIN_W, WIN_H)
    pauseable_sleep(0.2)
    activate_window(hwnd)

    kb = keyboard.Listener(on_press=on_key_press)
    kb.start()

    pp1, pp2, pp3 = PP_MOVE1, PP_MOVE2, PP_MOVE3

    print("Running. ESC stops. 0 resumes learn-move prompt. P toggles pause.")
    print(f"PP start: move1={pp1}, move2={pp2}, move3={pp3}")

    with mss.mss() as sct:
        while not stop_requested:
            pause_point()

            if pp1 <= 0 and pp2 <= 0 and pp3 <= 0:
                print("[DONE] All PP depleted.")
                beep_stop_alert()
                break

            start_trainer_battle(hwnd)
            if stop_requested:
                break

            for i in range(TRAINER_HAS_POKEMON):
                if stop_requested:
                    break

                pause_point()
                dbg(f"STATE: Pokémon loop {i+1}/{TRAINER_HAS_POKEMON}")

                # If Yes/No is up, handle it first
                ok = handle_yesno_if_present(hwnd, sct)
                if not ok or stop_requested:
                    break

                # Click fight only when valid
                fight_start = time.time()
                while not stop_requested:
                    pause_point()

                    # If No appears, handle it then keep trying
                    if is_no_visible_once(hwnd, sct):
                        ok = handle_yesno_if_present(hwnd, sct)
                        if not ok or stop_requested:
                            break
                        continue

                    if click_fight_if_valid(hwnd, sct):
                        break

                    if (time.time() - fight_start) > 6.0:
                        pauseable_sleep(0.25)
                    else:
                        pauseable_sleep(0.10)

                if stop_requested:
                    break

                move_idx, pp1, pp2, pp3, pp4 = choose_move_and_spend_pp(pp1, pp2, pp3, pp4)
                if move_idx == 0:
                    print("[DONE] No PP remaining.")
                    beep_stop_alert()
                    stop_requested = True
                    break

                mx, my = move_xy(move_idx)
                dbg(f"STATE: selecting move{move_idx} client={(mx, my)} PP now m1={pp1} m2={pp2} m3={pp3} m4={pp4}")

                click_client(hwnd, mx, my, post_sleep=POST_MOVE_SLEEP, label=f"CLICK_MOVE{move_idx}")
                pauseable_sleep(MOVE_TO_PROMPT_SETTLE)

                # Only expect switch prompt if there is another Pokémon coming
                if i < TRAINER_HAS_POKEMON - 1:
                    ok = wait_no_then_handle_or_recover(hwnd, sct, last_move_xy=(mx, my))
                    if not ok or stop_requested:
                        break
                else:
                    dbg("STATE: last Pokémon, not expecting No prompt, waiting for battle end UI")
                    pauseable_sleep(1.5 + BATTLE_DELAY_BONUS_S)

            if stop_requested:
                break

            click_end_dialogue(hwnd)
            pauseable_sleep(END_BATTLE_SLEEP)

    print("Stopped.")


if __name__ == "__main__":
    main()
