"""
ASCII notation → LilyPond converter.

Input format (user's adapted ABC):
  - Note letters a-g, lowercase only. Capital letters reserved for chord symbols.
  - Accidentals follow the letter: f#, bb, c##, etc. Always key-agnostic
    (b means B natural regardless of key signature; bb means B flat).
  - Octave: bare letter = middle octave; trailing ' = up an octave;
    trailing , = down an octave. Only three octaves supported.
  - Middle octave default: treble clef = E4-ish (few ledger lines on treble staff),
    bass clef = E3-ish (few ledger lines on bass staff).
  - Durations: 4=quarter, 8=eighth, 16=sixteenth, 2=half, 1=whole, 32=thirty-second.
    Attaches to the immediately preceding note. Inherited by following notes
    until a new duration is declared. First note must have an explicit duration.
  - x = rest (uses current duration rules).
  - | = bar line.
  - ( and ) = slur start/end.
  - Whitespace separates tokens.

Options in the source line:
  clef=bass    → bass clef, middle octave shifted down

Example:
  Input:  "r8 g f# e | d16 c b8 a4"  (treble, key Em)
  Output: LilyPond \relative block with notes at E4 octave.
"""

import re


# ---------------------------------------------------------------------------
# Token parsing
# ---------------------------------------------------------------------------

# A note token: letter, then optional accidental(s), then optional
# trailing apostrophe(s) for octave-up OR trailing comma(s) for octave-down,
# then optional duration digits.
NOTE_PAT = re.compile(
    r"""
    ^
    (?P<letter>[a-g])               # note letter
    (?P<accidental>(?:\#|b)*)       # accidentals: # or b, possibly stacked
    (?P<oct_up>'*)                  # trailing apostrophes for octave up
    (?P<oct_down>,*)                # trailing commas for octave down
    (?P<duration>\d*)               # optional duration
    $
    """,
    re.VERBOSE,
)

REST_PAT = re.compile(r"^x(?P<duration>\d*)$")

# Map ASCII accidentals → LilyPond Dutch suffixes.
ACCIDENTAL_MAP = {
    "":   "",
    "#":  "is",
    "##": "isis",
    "b":  "es",
    "bb": "eses",
}

# LilyPond's "natural" pitch names. We always emit absolute octave marks
# (no \relative wrapping) so the converter doesn't have to track context.
# Octave marks in LilyPond: c' = C4, c'' = C5, c = C3, c, = C2, c,, = C1.
# So treble middle (E4 area) sits at octave mark "'" for c-b notes.

# We define a base octave for "middle" register per clef. The "middle"
# letter `c` then maps to that LilyPond absolute octave.
# Treble: middle = 4 (so `c` → c', `e` → e', `b` → b')
# Bass:   middle = 3 (so `c` → c, `e` → e, `b` → b)
# Lower:  one below middle. Higher: one above middle.

CLEF_MIDDLE_OCTAVE = {
    "treble": 4,
    "bass": 3,
}


# Map ASCII note letter → LilyPond Dutch root, for key-signature translation.
_KEY_ROOT_PAT = re.compile(r"^([A-Ga-g])([#b]*)(m)?$")


def chord_key_to_lilypond(key_str):
    """
    Convert a chord-style key name like 'Em', 'F#m', 'Bb', 'C#' to a
    LilyPond key directive body like 'e \\minor' or 'bes \\major'.
    Returns None if key_str is None or empty.
    Raises ValueError on unparseable input.
    """
    if not key_str:
        return None
    m = _KEY_ROOT_PAT.match(key_str)
    if not m:
        raise ValueError(f"Cannot parse key: {key_str!r}")
    letter, accidental, minor = m.group(1), m.group(2), m.group(3)
    if accidental not in ACCIDENTAL_MAP:
        raise ValueError(f"Unsupported accidental in key: {accidental!r}")
    root = letter.lower() + ACCIDENTAL_MAP[accidental]
    mode = "\\minor" if minor else "\\major"
    return f"{root} {mode}"


def validate_time_signature(time_str):
    """Validate 'N/M' format. Returns the string unchanged if valid."""
    if not time_str:
        return None
    if not re.match(r"^\d+/\d+$", time_str):
        raise ValueError(f"Time signature must be N/M, got {time_str!r}")
    return time_str


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _ascii_pitch_to_lilypond(letter, accidental, octave_shift, clef):
    """
    Convert one note's components to a LilyPond pitch token.

    letter:        'a'..'g'
    accidental:    '', '#', '##', 'b', 'bb'
    octave_shift:  -1, 0, or +1 (lower, middle, upper)
    clef:          'treble' or 'bass'
    """
    if accidental not in ACCIDENTAL_MAP:
        raise ValueError(f"Unsupported accidental: {accidental!r}")

    suffix = ACCIDENTAL_MAP[accidental]
    middle_octave = CLEF_MIDDLE_OCTAVE[clef] + octave_shift
    # LilyPond octave = middle_octave - 3 commas/apostrophes from c.
    # c (no mark) = C3. c' = C4. c'' = C5. c, = C2.
    n_marks = middle_octave - 3
    if n_marks > 0:
        marks = "'" * n_marks
    elif n_marks < 0:
        marks = "," * (-n_marks)
    else:
        marks = ""
    return f"{letter}{suffix}{marks}"


class ParseError(Exception):
    pass


def parse_options(line):
    """
    Extract leading 'key=value' option tokens from a notation line.
    Returns (options_dict, remaining_line).
    """
    options = {}
    tokens = line.split()
    i = 0
    while i < len(tokens) and "=" in tokens[i] and tokens[i].count("=") == 1:
        key, val = tokens[i].split("=", 1)
        # Must look like a sensible option key, not a stray '=' in notation.
        if re.match(r"^[a-z_]+$", key):
            options[key] = val
            i += 1
        else:
            break
    return options, " ".join(tokens[i:])


def convert_notation_line(notation, default_clef="treble"):
    r"""
    Convert a single ASCII notation line to a LilyPond music expression.

    Returns the inner music string (no \score{} wrapper, no clef directive
    — those are emitted by the higher-level function that knows context).
    Also returns the resolved clef so the caller can emit the right \clef line.
    """
    options, body = parse_options(notation)
    clef = options.get("clef", default_clef)
    if clef not in CLEF_MIDDLE_OCTAVE:
        raise ParseError(f"Unknown clef: {clef!r}. Use 'treble' or 'bass'.")

    # key and time are validated here but passed through to the caller as-is,
    # so the document builder can decide how to render them.
    key = options.get("key")
    if key:
        try:
            chord_key_to_lilypond(key)  # validate only
        except ValueError as e:
            raise ParseError(str(e))

    time_sig = options.get("time")
    if time_sig:
        try:
            validate_time_signature(time_sig)
        except ValueError as e:
            raise ParseError(str(e))

    tokens = body.split()
    if not tokens:
        return "", {"clef": clef, "key": key, "time": time_sig}

    out = []
    current_duration = None  # inherited duration

    for tok in tokens:
        # Bar line
        if tok == "|":
            out.append("|")
            continue

        # Slur start/end as standalone tokens. ABC-style ( and ).
        if tok == "(":
            out.append("__SLUR_OPEN__")
            continue
        if tok == ")":
            out.append("__SLUR_CLOSE__")
            continue

        # Manual beam bracket as standalone tokens.
        if tok == "[":
            out.append("__BEAM_OPEN__")
            continue
        if tok == "]":
            out.append("__BEAM_CLOSE__")
            continue

        # A note may have leading/trailing ( ) for slurs or [ ] for manual
        # beam brackets glued to it. Peel them off.
        prefix_slur = ""
        suffix_slur = ""
        prefix_beam = ""
        suffix_beam = ""
        # Strip leading markers (could be either or both, in any order).
        while tok and tok[0] in "([":
            if tok[0] == "(":
                prefix_slur = "("
            else:
                prefix_beam = "["
            tok = tok[1:]
        # Strip trailing markers similarly.
        while tok and tok[-1] in ")]":
            if tok[-1] == ")":
                suffix_slur = ")"
            else:
                suffix_beam = "]"
            tok = tok[:-1]

        # Rest
        rest_match = REST_PAT.match(tok)
        if rest_match:
            dur = rest_match.group("duration")
            if dur:
                current_duration = dur
            if current_duration is None:
                raise ParseError(
                    f"Rest '{tok}' has no duration and no prior duration to inherit."
                )
            lily_tok = f"r{current_duration}"
            if prefix_slur:
                # Slurs can't attach to rests in LilyPond — defer to next note.
                out.append("__SLUR_OPEN__")
            if prefix_beam:
                out.append("__BEAM_OPEN__")
            out.append(lily_tok)
            if suffix_slur:
                out.append("__SLUR_CLOSE__")
            if suffix_beam:
                out.append("__BEAM_CLOSE__")
            continue

        # Note
        note_match = NOTE_PAT.match(tok)
        if not note_match:
            raise ParseError(
                f"Cannot parse token: {tok!r}. "
                f"Expected format: letter, optional accidentals (# or b), "
                f"optional octave mark (' for up, , for down), optional duration."
            )

        letter = note_match.group("letter")
        accidental = note_match.group("accidental")
        oct_up = note_match.group("oct_up")
        oct_down = note_match.group("oct_down")
        duration = note_match.group("duration")

        if oct_up and oct_down:
            raise ParseError(f"Note has both octave-up and octave-down marks: {tok!r}")

        # Only 3 octaves: error if user piles up multiple ' or , marks.
        if len(oct_up) > 1 or len(oct_down) > 1:
            raise ParseError(
                f"Only three octaves supported; got {tok!r}. "
                f"Use a single ' or , mark."
            )

        octave_shift = 0
        if oct_up:
            octave_shift = +1
        elif oct_down:
            octave_shift = -1

        if duration:
            current_duration = duration
        if current_duration is None:
            raise ParseError(
                f"First note '{tok}' must declare a duration "
                f"(e.g. '{tok}8' for an eighth note)."
            )

        pitch = _ascii_pitch_to_lilypond(letter, accidental, octave_shift, clef)
        lily_tok = f"{pitch}{current_duration}"

        if prefix_slur:
            out.append("__SLUR_OPEN__")
        if prefix_beam:
            out.append("__BEAM_OPEN__")
        out.append(lily_tok)
        if suffix_slur:
            out.append("__SLUR_CLOSE__")
        if suffix_beam:
            out.append("__BEAM_CLOSE__")

    # Resolve deferred markers.
    # Slurs: __SLUR_OPEN__ attaches "(" to next note;
    #        __SLUR_CLOSE__ attaches ")" to previous note.
    # Beams: __BEAM_OPEN__ attaches "[" to next note;
    #        __BEAM_CLOSE__ attaches "]" to previous note.
    # Also track, per resolved token, whether it sits inside a manual beam group.
    resolved = []
    in_manual_beam = []  # parallel list: True if token is inside [ ... ]
    pending_slur_open = False
    pending_beam_open = False
    manual_beam_depth = 0

    def _attach_suffix(suffix):
        """Attach suffix to the most recently emitted note/rest."""
        for i in range(len(resolved) - 1, -1, -1):
            if resolved[i] != "|":
                resolved[i] = resolved[i] + suffix
                return
        # No prior note: silently drop. (Could raise instead.)

    for item in out:
        if item == "__SLUR_OPEN__":
            pending_slur_open = True
            continue
        if item == "__SLUR_CLOSE__":
            _attach_suffix(")")
            continue
        if item == "__BEAM_OPEN__":
            pending_beam_open = True
            manual_beam_depth += 1
            continue
        if item == "__BEAM_CLOSE__":
            _attach_suffix("]")
            if manual_beam_depth > 0:
                manual_beam_depth -= 1
            continue

        # Normal token: bar line or note/rest.
        if item == "|":
            resolved.append(item)
            in_manual_beam.append(False)
            continue

        # It's a note or rest. Attach any pending opens.
        token_str = item
        if pending_slur_open:
            token_str = token_str + "("
            pending_slur_open = False
        if pending_beam_open:
            token_str = token_str + "["
            pending_beam_open = False
        resolved.append(token_str)
        in_manual_beam.append(manual_beam_depth > 0)

    # Auto-beam pass: find runs of consecutive beam-eligible notes
    # (duration >= 8, i.e. eighths or shorter) that are NOT inside a manual
    # beam group, NOT separated by a bar line, and NOT broken by a longer
    # note or rest. Wrap each such run of length >= 2 with [...].
    resolved = _auto_beam(resolved, in_manual_beam)

    return " ".join(resolved), {"clef": clef, "key": key, "time": time_sig}


# Token-classification helpers for the auto-beam pass.
_DURATION_AT_END = re.compile(r"(\d+)\)?\]?\(?\[?$")  # extract trailing duration


def _token_duration(tok):
    """
    Return the integer duration of a note/rest token, or None if not parseable.
    Handles trailing slur/beam markers.
    """
    # Strip trailing ) ] ( [ characters that may follow the duration.
    core = tok.rstrip("()[]")
    m = re.search(r"(\d+)$", core)
    if not m:
        return None
    return int(m.group(1))


def _is_rest(tok):
    """A rest token starts with 'r' (after stripping leading markers)."""
    core = tok.lstrip("([")
    return core.startswith("r")


def _auto_beam(tokens, in_manual_beam):
    """
    Wrap runs of beam-eligible notes with [...].
    Beam-eligible = duration >= 8 (eighth or shorter), is a note (not a rest),
    not inside a manual beam group, not separated from neighbors by a bar line
    or a longer note/rest.

    Runs of length 1 are not beamed (a beam of one note is meaningless).
    Manual brackets on tokens are preserved untouched.
    """
    n = len(tokens)
    eligible = [False] * n
    for i, tok in enumerate(tokens):
        if tok == "|":
            continue
        if in_manual_beam[i]:
            continue
        if _is_rest(tok):
            continue
        dur = _token_duration(tok)
        if dur is None:
            continue
        if dur >= 8:
            eligible[i] = True

    # Find maximal runs of eligible[i] = True with no bar line between.
    # Wrap runs of length >= 2.
    out = list(tokens)
    i = 0
    while i < n:
        if not eligible[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and eligible[j + 1]:
            j += 1
        run_len = j - i + 1
        if run_len >= 2:
            out[i] = out[i] + "["
            out[j] = out[j] + "]"
        i = j + 1
    return out


# ---------------------------------------------------------------------------
# Full LilyPond document generation
# ---------------------------------------------------------------------------

def build_lilypond_snippet(notation, default_clef="treble", version="2.24.0"):
    """
    Build a complete, renderable LilyPond document for a single notation line.
    Produces a cropped single-system output suitable for embedding as an image.

    Options are read from the notation string itself (key=, time=, clef=).
    If no time= is given, cadenza mode is used: no time signature is printed
    and bar lines appear exactly where the user wrote '|'.
    """
    music, opts = convert_notation_line(notation, default_clef=default_clef)
    clef = opts["clef"]
    key = opts["key"]
    time_sig = opts["time"]

    # Build the staff-internal directives in order: clef, key, time, then music.
    staff_lines = [f'    \\clef "{clef}"']

    if key:
        staff_lines.append(f"    \\key {chord_key_to_lilypond(key)}")

    if time_sig:
        # Strict time mode: print the time signature, let LilyPond enforce bars.
        staff_lines.append(f"    \\time {time_sig}")
        staff_lines.append(f"    {music}")
    else:
        # Cadenza mode: no time sig, bar lines drawn exactly where written.
        # \cadenzaOn disables auto-barring and time-sig enforcement, but
        # LilyPond still renders a default 4/4 (common time) signature on
        # the first line. We have to explicitly omit the TimeSignature
        # grob to suppress it.
        cadenza_music = music.replace("|", '\\bar "|"')
        staff_lines.append("    \\omit Staff.TimeSignature")
        staff_lines.append("    \\cadenzaOn")
        staff_lines.append(f"    {cadenza_music}")

    staff_block = "\n".join(staff_lines)

    return f"""\\version "{version}"

\\header {{
  tagline = ##f
}}

\\paper {{
  indent = 0
  line-width = 180\\mm
  oddHeaderMarkup = ##f
  evenHeaderMarkup = ##f
  oddFooterMarkup = ##f
  evenFooterMarkup = ##f
}}

\\score {{
  \\new Staff {{
{staff_block}
  }}
  \\layout {{ }}
}}
"""


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ascii_notation.py '<notation line with optional key= time= clef= options>'")
        print()
        print("Examples:")
        print("  python3 ascii_notation.py 'g8 f# e | d c b a'")
        print("  python3 ascii_notation.py 'key=Em  g8 f# e | d c b a'")
        print("  python3 ascii_notation.py 'key=Em time=4/4  x8 g f# e | d16 c b8 a4'")
        print("  python3 ascii_notation.py 'clef=bass key=Em  e8 b, a, g, | e,4'")
        sys.exit(1)

    notation_in = sys.argv[1]
    print(build_lilypond_snippet(notation_in))
