"""Synthesised 15 s soundtrack, 120 BPM, locked to the picture's cuts."""
import wave

import numpy as np

SR, DUR = 48000, 15.0
N = int(SR * DUR)
L = np.zeros(N)
R = np.zeros(N)
rev_send = np.zeros(N)
rng = np.random.default_rng(4)


def place(sig, t0, gain=1.0, pan=0.0, send=0.0):
    i = int(t0 * SR)
    if i >= N:
        return
    s = sig[: N - i] * gain
    L[i : i + len(s)] += s * np.sqrt((1 - pan) / 2)
    R[i : i + len(s)] += s * np.sqrt((1 + pan) / 2)
    rev_send[i : i + len(s)] += s * send


def tt(d):
    return np.arange(int(d * SR)) / SR


def lowpass(x, cut):
    """One-pole low-pass; cut may be an array (Hz per sample)."""
    cut = np.broadcast_to(np.asarray(cut, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * cut / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def kick(big=False):
    t = tt(0.9 if big else 0.45)
    f = 42 + 120 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t * (3.5 if big else 8))
    s[:240] += rng.standard_normal(240) * np.linspace(0.6, 0, 240)
    return np.tanh(s * 1.8)


def hat():
    t = tt(0.08)
    n = rng.standard_normal(len(t))
    n = n - lowpass(n, 7000)
    return n * np.exp(-t * 70) * 0.5


def clap():
    t = tt(0.35)
    n = rng.standard_normal(len(t))
    n = lowpass(n - lowpass(n, 900), 5000)
    env = np.exp(-t * 16) * (1 + 0.6 * (np.sin(t * 2 * np.pi * 90) > 0) * (t < 0.03))
    return n * env * 0.8


def impact():
    t = tt(2.4)
    sub = np.sin(2 * np.pi * (38 + 30 * np.exp(-t * 6)) * t) * np.exp(-t * 1.6)
    n = rng.standard_normal(len(t))
    noise = lowpass(n, 2500 * np.exp(-t * 3) + 200) * np.exp(-t * 3.2)
    return np.tanh(sub * 1.4 + noise * 0.9)


def whoosh(d, up=True):
    t = tt(d)
    n = rng.standard_normal(len(t))
    x = t / d
    cut = 300 + 6000 * (x if up else 1 - x) ** 2
    env = np.sin(np.pi * x) ** 2
    return lowpass(n, cut) * env * 1.6


def riser(d):
    t = tt(d)
    x = t / d
    n = lowpass(rng.standard_normal(len(t)), 400 + 9000 * x**2)
    f = 110 * 2 ** (x * 3)
    saw = 2 * ((np.cumsum(f) / SR) % 1) - 1
    return (n * 0.8 + lowpass(saw, 600 + 5000 * x) * 0.35) * x**2.2


def blip(f=2600, d=0.03):
    t = tt(d)
    return np.sin(2 * np.pi * f * t) * np.exp(-t * 140) * 0.35


def note(f, d, cut=900):
    t = tt(d)
    s = sum(2 * ((f * k * t) % 1) - 1 for k in (1.0, 1.005, 0.995)) / 3
    s = lowpass(s, cut)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 3.2)
    return s * env


BEAT = 0.5
# intro: riser, typing blips, impact on 1.5
place(riser(1.5), 0.0, 0.55, send=0.3)
for k in range(10):
    place(blip(2200 + 300 * (k % 3)), 0.35 + k * 0.06, 0.8, pan=(-0.5 if k % 2 else 0.5))
for t0, big in ((1.5, 1.0), (13.0, 1.15)):
    place(impact(), t0, big, send=0.5)
    place(kick(True), t0, big)
place(impact(), 5.5, 0.55, send=0.4)

# groove 1.5 -> 12.3 : four on the floor, off-beat hats, back-beat claps from 3.5
t = 1.5
while t < 12.25:
    if abs(t - 1.5) > 1e-6:
        place(kick(), t, 0.9)
    if t >= 3.5:
        place(hat(), t + BEAT / 2, 0.55, pan=0.3)
        place(hat(), t + BEAT * 0.75, 0.25, pan=-0.3)
    beat_i = round((t - 1.5) / BEAT)
    if t >= 3.5 and beat_i % 2 == 1:
        place(clap(), t, 0.55, send=0.35)
    t += BEAT
for t0 in (2.0, 2.5, 3.0):  # word hits
    place(clap(), t0, 0.8, send=0.4)
    place(blip(1400, 0.06), t0, 0.9)

# bass line (A minor), one note per beat, side-chained by the kick envelope
BASS = [55.0, 55.0, 65.41, 49.0]
t = 3.5
while t < 12.25:
    f = BASS[int((t - 3.5) / 2) % 4]
    place(note(f, BEAT * 0.95, 500), t + 0.06, 0.7)
    t += BEAT

# whooshes on every transition
for t0, d in ((3.25, 0.35), (6.75, 0.35), (9.25, 0.4), (11.22, 0.38), (12.72, 0.3)):
    place(whoosh(d), t0, 0.6, pan=0.0, send=0.3)
# counter ticks during "297 watchlists" / "40+ registers"
for k in range(22):
    place(blip(3200, 0.02), 7.12 + 0.7 * (k / 22) ** 1.6, 0.6, pan=0.2)
for k in range(12):
    place(blip(2900, 0.02), 8.0 + 0.7 * (k / 12) ** 1.6, 0.6, pan=-0.2)
# alert on the sanctions hit
for k in range(3):
    place(blip(880, 0.12), 5.5 + k * 0.13, 0.5, send=0.3)
# stamp
place(kick(True), 12.3, 0.8)
place(clap(), 12.3, 0.9, send=0.5)
# build to the logo
place(riser(0.7), 12.3, 0.6, send=0.2)

# pads: dark drone, then a bright resolve on the logo
t = tt(DUR)
drone = sum(np.sin(2 * np.pi * f * t + k) for k, f in enumerate((55, 82.4, 110.2, 164.8)))
drone = lowpass(drone, 300 + 900 * (t / DUR)) * 0.08 * np.minimum(1, t / 1.0)
place(drone, 0.0, 1.0)
tl = tt(2.0)
chord = sum(2 * (((f * tl) + k * 0.3) % 1) - 1 for k, f in enumerate((220, 277.2, 329.6, 440, 554.4, 659.3)))
chord = lowpass(chord, 3000 * np.exp(-tl * 1.2) + 400) * np.exp(-tl * 1.1) * 0.22
place(chord, 13.0, 1.0, send=0.9)
for k, f in enumerate((1318.5, 1760, 2217, 2637)):  # glint shimmer
    place(blip(f, 0.4) * 0.6, 14.3 + k * 0.06, 0.8, pan=(-0.6 + 0.4 * k), send=0.8)

# convolution reverb with a synthetic 2.2 s tail
ir_t = tt(2.2)
irL = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 3.0)
irR = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 3.0)
irL, irR = lowpass(irL, 5000), lowpass(irR, 5000)
n = N + len(ir_t)
F = np.fft.rfft(rev_send, n)
L += np.fft.irfft(F * np.fft.rfft(irL, n), n)[:N] * 0.05
R += np.fft.irfft(F * np.fft.rfft(irR, n), n)[:N] * 0.05

# master: fade out, soft clip, normalise to -1 dBFS
fade = np.ones(N)
fade[int(14.6 * SR) :] = np.linspace(1, 0, N - int(14.6 * SR))
mix = np.stack([L, R], 1) * fade[:, None]
mix = np.tanh(mix * 1.2)
mix *= 10 ** (-1 / 20) / np.max(np.abs(mix))
with wave.open("audio.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print("ok")
