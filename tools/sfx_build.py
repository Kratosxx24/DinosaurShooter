"""Build assets/sfx/ from CC0 Freesound previews: download, cut takes, pitch, normalize, fade, encode.

    python -m venv .sfxenv && .sfxenv/Scripts/python -m pip install numpy miniaudio lameenc
    .sfxenv/Scripts/python tools/sfx_build.py

Sources are cached in tools/sfx_src/ (gitignored). Every cut is a line in RECIPE below: change one, rerun, then
bump SFX_V in index.html if the manifest shipped already (files are cached immutable, so a changed cut gets a new
name automatically: the name encodes source id + take).
"""
import json, os, sys, urllib.request
import numpy as np, miniaudio, lameenc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, OUT = os.path.join(ROOT, 'tools', 'sfx_src'), os.path.join(ROOT, 'assets', 'sfx')
SFX_V = 'v1'
SR = 44100

# id: (author, title, preview user id)
SOURCES = {
    427596: ('michorvath', 'AR15 rifle shot', 3094998),
    854231: ('qubodup', 'M4A1 Rifle Shot 10', 71257),
    153560: ('SpliceSound', 'Winchester Rifle Cock Reload', 1480854),
    734096: ('modusmogulus', 'Forest Impulse Response Gunshot Tail', 15956618),
    151068: ('vabadus', 'Beretta M9 hammer click', 2732486),
    104407: ('Nanashi', 'Mag remove', 61794),
    379977: ('morganpurkis', 'Inserting Magazine', 5937039),
    855598: ('qubodup', 'Pulling and Releasing Barrett M82A1 Charging Handle', 71257),
    779805: ('modusmogulus', 'Meaty Damage Impact', 15956618),
    511194: ('Pablobd', 'Headshot', 5701403),
    392883: ('clif_creates', 'Hard Candy / Bone Crunch', 3530854),
    464486: ('elynch0901', 'Male Grunting In Pain', 4814007),
    547209: ('MrFossy', 'Voice_AdultMale_PainGrunts_09', 129727),
    257709: ('vmgraw', 'GRUNT 2', 4028838),
    22440: ('Lunardrive', 'Single Heartbeat Clean HQ_BeatSmith', 120830),
    529463: ('CaveboyTup', 'Small Dino Raspy Calls', 4355850),
    643850: ('Nerdwizard78', 'raptorshreak', 14149539),
    828228: ('HowesenbergFilms', 'Raptor / Small Dragon cry', 9982004),
    622809: ('NaturesTemper', 'Utahraptor Hiss', 3862281),
    643928: ('Nerdwizard78', 'raptorgoesextinct', 14149539),
    529462: ('CaveboyTup', 'T-Rex Calls', 4355850),
    320345: ('999999990', 'Dino Hiss Dragon Roar', 5286377),
    688734: ('mescamilla1980', 'T Rex Closed Mouth Vocalizations', 11894484),
    77027: ('andysm', 'DinoSteps1', 233719),
    721601: ('DasWaff', 'Giant step', 2617407),
    467701: ('LucasDuff', 'monster bite', 8272463),
    276577: ('MickBoere', 'Dragons Dying Breath', 3411936),
    457531: ('Breviceps', 'Dinosaur falls to the ground', 9159316),
    288899: ('petebuchwald', 'Rocky Mountain Outdoors: wind and birds', 2367139),
    231536: ('VKProduktion', 'Creek 06 (loop)', 4034520),
}

# a cut: (source id, start s, end s, options). options: rate (pitch/speed baked in), fade (out, s), mono,
# norm ('peak' dB or ('rms', dB)), loop (crossfade seconds for a seamless loop), trim (level that starts the sound)
def C(src, a, b, **o): return (src, a, b, o)

# slot -> layers; a layer is a list of cuts (variants) or a dict with cuts + gain/delay/rate for the manifest
RECIPE = {
    'rifle.shot':   [[C(854231, 0, 0.63, fade=0.1, trim=0.15), C(427596, 0.04, 1.4, fade=0.5, trim=0.15)]],
    'rifle.mech':   [[C(153560, 0, 0.2, fade=0.04)]],
    'rifle.tail':   [[C(734096, 0, 4.4, fade=1.5, norm=-3)]],
    'rifle.dry':    [[C(151068, 0.06, 0.19, fade=0.03)]],
    'rifle.magout': [[C(104407, 0.06, 0.6, fade=0.1)]],
    'rifle.magin':  [[C(379977, 0, 0.6, fade=0.1)]],
    'rifle.bolt':   [[C(855598, 0, 0.8, fade=0.1)]],
    'hit.body':     [[C(779805, 0, 0.5, fade=0.15)]],
    'hit.head':     [[C(511194, 0.02, 0.6, fade=0.15)], {'cuts': [C(392883, 0, 0.6, fade=0.2)], 'gain': 0.45}],
    'player.hurt':  [[C(464486, 0.06, 0.45, fade=0.08), C(547209, 0, 0.3, fade=0.05), C(257709, 0.22, 0.75, fade=0.1)]],
    'player.heart': [[C(22440, 0, 0.66, fade=0.1)]],
    # raptor: designed calls, all mono (they're placed in 3D)
    'raptor.chirp':   [[C(529463, 0, 0.92, fade=0.1, mono=1), C(529463, 1.06, 1.72, fade=0.1, mono=1),
                        C(529463, 0, 0.92, fade=0.1, mono=1, rate=0.85), C(529463, 1.06, 1.72, fade=0.1, mono=1, rate=1.15)]],
    'raptor.screech': [[C(643850, 0, 1.75, fade=0.3, mono=1), C(828228, 0.15, 1.12, fade=0.2, mono=1)]],
    'raptor.bite':    [[C(392883, 0, 0.85, fade=0.2, mono=1, rate=0.75)],
                       {'cuts': [C(622809, 0.4, 1.5, fade=0.5, mono=1)], 'gain': 0.5}],
    'raptor.death':   [[C(643928, 0, 0.9, fade=0.2, mono=1, rate=0.9)],
                       {'cuts': [C(276577, 0, 3.0, fade=1.5, mono=1, rate=1.15)], 'gain': 0.35, 'delay': 0.5}],
    # rex: T-Rex Calls (alligator + lion + elk) for roars, growls and the death bellow
    'rex.roar':  [[C(529462, 4.1, 9.2, fade=0.8, mono=1), C(529462, 10.3, 15.4, fade=0.8, mono=1),
                   C(320345, 2.9, 5.7, fade=0.6, mono=1, rate=0.85)]],
    'rex.growl': [[C(529462, 15.7, 18.8, fade=0.5, mono=1), C(529462, 19.4, 22.0, fade=0.5, mono=1), C(529462, 23.0, 25.6, fade=0.5, mono=1),
                   C(688734, 18.55, 22.6, fade=1.0, mono=1), C(688734, 22.75, 26.6, fade=1.0, mono=1), C(688734, 30.85, 34.8, fade=1.0, mono=1)]],
    'rex.step':  [[C(77027, 0.02, 1.0, fade=0.3, mono=1), C(721601, 0.02, 1.3, fade=0.3, mono=1),
                   C(77027, 0.02, 1.0, fade=0.3, mono=1, rate=0.85)]],
    'rex.bite':  [[C(467701, 0.36, 1.4, fade=0.3, mono=1, rate=0.8)]],
    'rex.death': [[C(529462, 36.5, 42.5, fade=2.0, mono=1, rate=0.85)],
                  {'cuts': [C(276577, 0, 5.2, fade=2.0, mono=1, rate=0.8)], 'gain': 0.5, 'delay': 4.5}],
    'body.fall': [[C(457531, 0, 1.2, fade=0.4, mono=1, rate=0.85), C(457531, 2.85, 4.1, fade=0.4, mono=1, rate=0.85)]],
    # loops: stereo, levelled by loudness rather than peak
    'amb.forest': [[C(288899, 0.4, 85.5, norm=('rms', -26), loop=2.0)]],
    'amb.stream': [[C(231536, 0, 35.99, norm=('rms', -24))]],
}


def fetch(i):
    p = os.path.join(SRC, f'{i}.mp3')
    if not os.path.exists(p):
        os.makedirs(SRC, exist_ok=True)
        url = f'https://cdn.freesound.org/previews/{i // 1000}/{i}_{SOURCES[i][2]}-hq.mp3'
        print('  download', url)
        urllib.request.urlretrieve(url, p)
    return p


def load(i):
    p = fetch(i)
    ch = miniaudio.get_file_info(p).nchannels
    d = miniaudio.decode_file(p, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=ch, sample_rate=SR)
    return np.frombuffer(d.samples, dtype=np.float32).reshape(-1, ch).astype(np.float64)


def cut(src, a, b, o):
    x = load(src)[int(a * SR):int(b * SR)]
    if o.get('mono'): x = x.mean(axis=1, keepdims=True)
    r = o.get('rate', 1)
    if r != 1:                                            # varispeed: lower rate = lower and longer
        t = np.arange(0, len(x) - 1, r)
        x = np.stack([np.interp(t, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], axis=1)
    x -= x.mean(axis=0)                                   # no DC offset
    if o.get('loop'):                                     # crossfade the tail into the head: seamless loop
        n = int(o['loop'] * SR); w = np.linspace(0, 1, n)[:, None]
        x = np.concatenate([x[n:-n], x[-n:] * (1 - w) + x[:n] * w])
    else:
        lvl = np.abs(x).max(axis=1)                       # no dead air before the sound: it's latency on the trigger
        x = x[max(0, int(np.argmax(lvl > lvl.max() * o.get('trim', 0.02))) - int(0.003 * SR)):]
        fi = min(int(0.004 * SR), len(x) // 4)            # tiny fade-in so a cut never clicks
        x[:fi] *= np.linspace(0, 1, fi)[:, None]
        if o.get('fade'):
            fo = min(int(o['fade'] * SR), len(x) // 2)
            x[-fo:] *= (np.linspace(1, 0, fo) ** 2)[:, None]
    norm = o.get('norm', -1)
    if isinstance(norm, tuple):
        x *= 10 ** (norm[1] / 20) / np.sqrt((x ** 2).mean())
        x = np.clip(x, -0.98, 0.98)
    else:
        x *= 10 ** (norm / 20) / np.abs(x).max()
    return x


def save(x, path):
    enc = lameenc.Encoder()
    enc.set_bit_rate(96 if x.shape[1] == 1 else 128); enc.set_in_sample_rate(SR); enc.set_channels(x.shape[1]); enc.set_quality(2)
    open(path, 'wb').write(enc.encode((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()) + enc.flush())


def name(slot, c):
    src, a, b, o = c
    tag = f'{src}_{int(a * 100)}' + (f'_r{int(o["rate"] * 100)}' if o.get('rate', 1) != 1 else '')
    return f'{slot.replace(".", "_")}_{tag}.mp3'


def main():
    only = set(sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    manifest, used = {}, set()
    for slot, layers in RECIPE.items():
        out = []
        for L in layers:
            L = L if isinstance(L, dict) else {'cuts': L}
            files = []
            for c in L['cuts']:
                fn = name(slot, c); files.append(fn); used.add(c[0])
                if not only or slot in only or not os.path.exists(os.path.join(OUT, fn)):
                    save(cut(c[0], c[1], c[2], c[3]), os.path.join(OUT, fn))
            out.append({'files': files, **{k: v for k, v in L.items() if k != 'cuts'}})
        manifest[slot] = out[0]['files'] if len(out) == 1 and list(out[0]) == ['files'] else out
        print(f'{slot:15} ' + ' + '.join(f'{len(l["files"])}' for l in out))
    with open(os.path.join(OUT, f'sfx_{SFX_V}.json'), 'w', newline='\n') as f:
        json.dump(manifest, f, indent=2); f.write('\n')
    # credits table in the README
    rd = os.path.join(OUT, 'README.md'); txt = open(rd, encoding='utf-8').read()
    head = txt[:txt.index('## Credits')]
    cuts = lambda L: L['cuts'] if isinstance(L, dict) else L
    slots_of = lambda i: ', '.join(sorted({s for s, Ls in RECIPE.items() for L in Ls for c in cuts(L) if c[0] == i}))
    rows = '\n'.join(f'| {slots_of(i)} | [{SOURCES[i][1]}](https://freesound.org/s/{i}/) | {SOURCES[i][0]} | CC0 |' for i in sorted(used))
    open(rd, 'w', encoding='utf-8', newline='\n').write(head + '## Credits\n\nGenerated by `tools/sfx_build.py`: every file is a cut of a Freesound HQ preview.\n\n'
                                                   '| slots | source | author | license |\n|---|---|---|---|\n' + rows + '\n')
    stale = [f for f in os.listdir(OUT) if f.endswith('.mp3') and f not in {n for v in manifest.values() for n in (v if isinstance(v[0], str) else [x for l in v for x in l['files']])}]
    for f in stale: os.remove(os.path.join(OUT, f))
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith('.mp3'))
    print(f'{len(used)} sources, {size / 1e6:.1f} MB of mp3' + (f', removed {len(stale)} stale' if stale else ''))


if __name__ == '__main__':
    main()
