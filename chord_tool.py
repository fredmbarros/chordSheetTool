import re
import argparse
import os

try:
    from weasyprint import HTML as WeasyprintHTML
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False


# ---------------------------------------------------------------------------
# TOKENISER
# ---------------------------------------------------------------------------
# Source conventions:
#   ,   plain barline            ->  |
#   ,:  repeat-open barline      ->  |:
#   :,  repeat-close barline     ->  :|
#   ;   final double barline     ->  ||
#   [n] ending number            ->  digit only, black-box styled
#   {text}                       ->  inline annotation, rendered as text
#   ===  (own line)              ->  page break
#   c-d-eb-e                     ->  single note run (hyphen-separated lowercase)

def normalise_chords(raw):
    return ' '.join(raw.split())


# Note run pattern: lowercase letters (with optional # or b) joined by hyphens
# e.g. c-d-eb-e  or  g-a-b-c
NOTE_RUN_PAT = re.compile(r"(?<![\w#])([a-g][b#]?(?:-[a-g][b#]?)+)(?![\w#])")

def expand_note_runs(chords, fmt):
    """
    Expand hyphen-separated note runs in a chord string.
    fmt='cho'  -> [c] [d] [eb] [e]   (lowercase brackets for ChordPro)
    fmt='html' -> <span class="note">c</span> etc.
    fmt='txt'  -> c d eb e           (plain, space-separated, lowercase)
    fmt='raw'  -> c d eb e           (plain, for internal use)
    """
    def replace(m):
        notes = m.group(1).split('-')
        if fmt == 'cho':
            return ' '.join('[' + n + ']' for n in notes)
        elif fmt == 'html':
            return ' '.join('<span class="note">' + n + '</span>' for n in notes)
        else:  # txt or raw
            return ' '.join(notes)
    return NOTE_RUN_PAT.sub(replace, chords)


def tokenise(line):
    """
    Returns a list of tokens, each either:
      - a measure dict: { 'type': 'measure', 'chords', 'ending', 'left_deco', 'right_deco' }
      - an annotation:  { 'type': 'annotation', 'text' }
    """
    annotations = {}
    placeholder_tmpl = '\x00ANN{}\x00'

    def stash_annotation(m):
        idx = len(annotations)
        key = placeholder_tmpl.format(idx)
        annotations[key] = m.group(1).strip()
        return key

    line_subst = re.sub(r'\{([^}]*)\}', stash_annotation, line)

    s = line_subst.replace('[', '(').replace(']', ')')
    SEP = re.compile(r'(,:|:,|,|;)')
    parts = SEP.split(s)

    tokens = []
    pending_left = ''

    i = 0
    while i < len(parts):
        chunk = parts[i]
        i += 1
        sep = parts[i] if i < len(parts) else None
        if sep is not None:
            i += 1

        if sep == ':,':
            right_deco, next_left = ':', ''
        elif sep == ',:':
            right_deco, next_left = '', ':'
        elif sep == ';':
            right_deco, next_left = '||', ''
        else:
            right_deco, next_left = '', ''

        sub_parts = re.split(r'(\x00ANN\d+\x00)', chunk)

        chord_accumulator = ''
        for sp in sub_parts:
            if sp in annotations:
                chords = normalise_chords(chord_accumulator)
                chord_accumulator = ''
                if chords:
                    ending_match = re.match(r'^\((\d+)\)\s*(.*)', chords)
                    if ending_match:
                        ending = ending_match.group(1)
                        chords = ending_match.group(2)
                    else:
                        ending = ''
                    tokens.append({
                        'type':       'measure',
                        'chords':     chords,
                        'ending':     ending,
                        'left_deco':  pending_left,
                        'right_deco': '',
                    })
                    pending_left = ''
                tokens.append({'type': 'annotation', 'text': annotations[sp]})
            else:
                chord_accumulator += sp

        chords = normalise_chords(chord_accumulator)
        if chords:
            ending_match = re.match(r'^\((\d+)\)\s*(.*)', chords)
            if ending_match:
                ending = ending_match.group(1)
                chords = ending_match.group(2)
            else:
                ending = ''
            tokens.append({
                'type':       'measure',
                'chords':     chords,
                'ending':     ending,
                'left_deco':  pending_left,
                'right_deco': right_deco,
            })
        elif right_deco:
            for t in reversed(tokens):
                if t['type'] == 'measure':
                    t['right_deco'] = right_deco
                    break

        pending_left = next_left

    return tokens


# ---------------------------------------------------------------------------
# METADATA / SONG SPLITTING
# ---------------------------------------------------------------------------

def split_songs(content):
    lines = content.splitlines()
    delimiters = [i for i, l in enumerate(lines) if l.strip() == '---']

    if not delimiters:
        return [('', content.strip())]

    songs = []
    i = 0
    while i < len(delimiters):
        meta_open  = delimiters[i]
        meta_close = delimiters[i + 1] if i + 1 < len(delimiters) else None

        if meta_close is None:
            chord_lines = lines[meta_open + 1:]
            songs.append(('', '\n'.join(chord_lines).strip()))
            break

        meta_body = '\n'.join(lines[meta_open + 1:meta_close])
        next_meta_open = delimiters[i + 2] if i + 2 < len(delimiters) else len(lines)
        chord_body = '\n'.join(lines[meta_close + 1:next_meta_open])

        songs.append((meta_body.strip(), chord_body.strip()))
        i += 2

    return songs


def parse_meta(meta_body):
    meta = {}
    for line in meta_body.splitlines():
        if ':' in line:
            key, _, val = line.partition(':')
            meta[key.strip().lower()] = val.strip()
    return meta


# ---------------------------------------------------------------------------
# CHO OUTPUT
# ---------------------------------------------------------------------------
# Uses the ChordPro {start_of_grid} / {end_of_grid} directives for
# chord-only sheets. Each run of chord lines becomes a grid block.
# Annotations become {comment: } directives.

def generate_cho(content, out_dir=None):
    songs = split_songs(content)
    output_parts = []

    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        title = meta.get('title', 'Chord Sheet')
        song_key = meta.get('key')
        lines_out = ['{title: ' + title + '}']

        if meta.get('artist'):
            lines_out.append('{artist: ' + meta['artist'] + '}')
        if meta.get('key'):
            lines_out.append('{key: ' + meta['key'] + '}')
        if meta.get('time'):
            lines_out.append('{time: ' + meta['time'] + '}')

        # Parse beats-per-measure from time signature if present (e.g. "4/4" -> 4)
        beats = None
        time_sig = meta.get('time', '')
        if time_sig and '/' in time_sig:
            try:
                beats = int(time_sig.split('/')[0])
            except ValueError:
                beats = None

        grid_buf = []

        def flush_grid(buf, out):
            if buf:
                out += ['', '{start_of_grid}'] + buf + ['{end_of_grid}']
                buf.clear()

        for line in chord_text.splitlines():
            stripped = line.strip()

            if not stripped:
                flush_grid(grid_buf, lines_out)
                lines_out.append('')
                continue

            if stripped == '===':
                flush_grid(grid_buf, lines_out)
                lines_out.append('')
                continue

            nm = NOTATION_LINE_PAT.match(stripped)
            if nm:
                flush_grid(grid_buf, lines_out)
                if NOTATION_DISABLED:
                    lines_out.append('{comment: ' + nm.group(1) + '}')
                else:
                    rr = render_notation(nm.group(1), song_key, out_dir or '.')
                    if rr.get('error'):
                        print("Warning: notation snippet failed (" +
                              (title or 'song') + "): " + rr['error'])
                        lines_out.append('{comment: notation: ' + nm.group(1) + '}')
                    else:
                        label = rr.get('id') or rr.get('hash') or 'notation'
                        lines_out.append('{comment: \u266a ' + label + '}')
                        if rr.get('png_rel'):
                            lines_out.append('{image: ' + rr['png_rel'] + '}')
                continue

            tokens = tokenise(line)
            all_annotations = all(t['type'] == 'annotation' for t in tokens)

            if all_annotations:
                flush_grid(grid_buf, lines_out)
                for t in tokens:
                    lines_out.append('{comment: ' + t['text'] + '}')
                continue

            # Chord line - build grid row
            # In a grid, each measure supplies its own opening barline.
            # A repeat-close (:,) is encoded as right_deco=':' on the current
            # measure AND left_deco='' on the next. To avoid ":| |" (double
            # barline), we fold the repeat-close into the NEXT measure's left
            # side: the current measure emits no right barline, and the next
            # measure opens with ":|" instead of "|".
            measure_tokens = [t for t in tokens if t['type'] == 'measure']
            parts = []
            for idx2, t in enumerate(tokens):
                if t['type'] == 'annotation':
                    flush_grid(grid_buf, lines_out)
                    lines_out.append('{comment: ' + t['text'] + '}')
                else:
                    # Determine left barline
                    if t['left_deco'] == ':':
                        left = '|:'
                    else:
                        # Check if previous measure had right_deco=':'
                        # and fold it in here
                        prev_measures = [x for x in tokens[:tokens.index(t)]
                                         if x['type'] == 'measure']
                        if prev_measures and prev_measures[-1]['right_deco'] == ':':
                            left = ':|'
                        else:
                            left = '|'

                    # Right barline: only emit for final (||) or end of line
                    # repeat-close is handled by the NEXT measure's left side
                    if t['right_deco'] == '||':
                        right = ' ||'
                    else:
                        right = ''

                    ending = ('(' + t['ending'] + ') ' if t['ending'] else '')
                    chords_str = expand_note_runs(t['chords'], 'cho')
                    chords_in_measure = len(t['chords'].split())
                    if beats and chords_in_measure < beats:
                        padding = ' ' + ' '.join(['.'] * (beats - chords_in_measure))
                    else:
                        padding = ''
                    parts.append(f"{left} {ending}{chords_str}{padding}{right}")
            if parts:
                # Close the final measure if no explicit right barline
                row = ' '.join(parts)
                if not row.rstrip().endswith(('|', '||', ':|')):
                    row += ' |'
                grid_buf.append(row)

        flush_grid(grid_buf, lines_out)
        output_parts.append('\n'.join(lines_out))

    return '\n\n'.join(output_parts)


# ---------------------------------------------------------------------------
# HTML RENDERING
# ---------------------------------------------------------------------------

CHORD_PAT = re.compile(
    r'\b([A-G][b#]?(m|maj|min|aug|dim|sus|o)?\d?(/[A-G][b#]?)?)\b'
)

DOTS = '<span class="dots">:</span>'


def chords_to_spans(text):
    # Expand note runs first (before chord regex touches them)
    text = expand_note_runs(text, 'html')
    return CHORD_PAT.sub(r'<span class="chord">\1</span>', text)


def measure_to_html(t):
    classes = ['measure']
    if t['left_deco'] == ':':
        classes.append('repeat-open')
    if t['right_deco'] == ':':
        classes.append('repeat-close')
    if t['right_deco'] == '||':
        classes.append('final')

    left_dots   = DOTS if t['left_deco'] == ':' else ''
    right_dots  = DOTS if t['right_deco'] == ':' else ''
    ending_html = ('<span class="ending">' + t['ending'] + '</span>'
                   if t['ending'] else '')
    chords_html = chords_to_spans(t['chords'])

    return ('<span class="' + ' '.join(classes) + '">'
            + left_dots + ending_html + chords_html + right_dots
            + '</span>')


def line_to_html(tokens):
    if len(tokens) == 1 and tokens[0]['type'] == 'annotation':
        return '<div class="annotation">' + tokens[0]['text'] + '</div>'

    inner = ''
    for t in tokens:
        if t['type'] == 'annotation':
            inner += '<span class="annotation">' + t['text'] + '</span>'
        else:
            inner += measure_to_html(t)
    return '<div class="section">' + inner + '</div>'


def song_to_html(meta, chord_text, out_dir=None):
    html = '<div class="song">\n'

    if meta.get('title'):
        html += '<h2 class="song-title">' + meta['title'] + '</h2>\n'

    meta_fields = []
    for key in ('artist', 'key', 'time'):
        if meta.get(key):
            meta_fields.append(
                '<span class="meta-field">'
                '<span class="meta-label">' + key.capitalize() + ':</span> '
                + meta[key] + '</span>'
            )
    for key, val in meta.items():
        if key not in ('title', 'artist', 'key', 'time'):
            meta_fields.append(
                '<span class="meta-field">'
                '<span class="meta-label">' + key.capitalize() + ':</span> '
                + val + '</span>'
            )
    if meta_fields:
        html += ('<div class="song-meta">'
                 + ' &nbsp; '.join(meta_fields)
                 + '</div>\n')

    song_key = meta.get('key')

    for line in chord_text.splitlines():
        if not line.strip():
            html += '<div class="spacer"></div>\n'
            continue
        if line.strip() == '===':
            html += '<div class="page-break"></div>\n'
            continue
        # Notation directive on its own line
        nm = NOTATION_LINE_PAT.match(line.strip())
        if nm:
            if NOTATION_DISABLED:
                html += '<div class="annotation">' + nm.group(1) + '</div>\n'
            else:
                rr = render_notation(nm.group(1), song_key, out_dir or '.')
                if rr.get('error'):
                    print("Warning: notation snippet failed (" +
                          (meta.get('title') or 'song') + "): " + rr['error'])
                html += notation_to_html(rr) + '\n'
            continue
        tokens = tokenise(line)
        html += line_to_html(tokens) + '\n'

    html += '</div>\n'
    return html


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
/* -------------------------------------------------------
   Selectors:
     .sheet              outermost wrapper
     .song               one song block
     .song-title         song title (centered)
     .song-meta          metadata line (artist, key, time ...)
     .meta-label         the "Key:" / "Time:" label
     .section            one line of music
     .spacer             blank-line gap between sections
     .page-break         forces a new page (=== in source)
     .measure            one bar (inline-block, never breaks)
     .measure.repeat-open    left side is |:
     .measure.repeat-close   right side is :|
     .measure.final          right side is ||
     .dots               repeat colon sitting inside the barline
     .ending             volta number e.g. 1  2
     .chord              individual chord symbol
     .annotation         {text} rendered inline or as its own line
------------------------------------------------------- */

@page { size: A4; margin: 25mm; }

body {
  font-family: Helvetica, Arial, sans-serif;
  background: white;
}

.sheet {
  /* outermost wrapper */
}

.song {
  margin-bottom: 2em;
}

.song-title {
  text-align: center;
  font-size: 20pt;
  margin: 0 0 0.5em 0;
}

.song-meta {
  font-size: 10pt;
  margin-bottom: 1em;
}

.meta-label {
  font-weight: bold;
}

.section {
  margin-bottom: 1em;
}

.spacer {
  /* height: 36pt; */
}

/* ---- page break ---- */
.page-break {
  page-break-after: always;
  break-after: page;
}

/* ---- each measure is an unbreakable inline block ---- */
.measure {
  display: inline-block;
  position: relative;
  height: 26pt;
  line-height: 26pt;
  padding: 0 16pt 0 16pt;
  margin-right: -2px;
  margin-bottom: 14pt;
  border-left:  2.5px solid black;
  border-right: 2.5px solid black;
  font-size: 17pt;
  font-weight: bold;
  font-family: 'Courier New', monospace;
  word-spacing: 0.3em;
  min-width: 34pt;
  vertical-align: middle;
  white-space: nowrap;
  box-sizing: border-box;
}

/* ---- repeat colon ---- */
.dots {
  position: absolute;
  top: 50%;
  transform: translateY(-55%);
  font-size: 20pt;
  font-weight: bold;
  line-height: 1;
}

.measure.repeat-open .dots  { left: -1pt; }
.measure.repeat-close .dots { right: -1pt; }

.measure.repeat-open  { padding-left:  20pt; }
.measure.repeat-close { padding-right: 20pt; }

/* ---- final double barline ---- */
.measure.final {
  border-right: 9px double black;
  margin-right: 0;
}

/* ---- volta number 1  2 ---- */
.ending {
  font-size: 10pt;
  font-weight: bold;
  padding: 1pt 2pt 0 2pt;
  margin: 0 12pt 0 -12pt;
  background-color: black;
  color: white;
  position: relative;
  top: -6pt;
}

.chord {
  color: black;
}

/* ---- single note runs e.g. c-d-eb-e ---- */
.note {
  color: black;
  font-style: italic;   /* visually distinguish notes from chords */
}

/* ---- text annotation {like this} ---- */
div.annotation {
  font-family: Helvetica, Arial, sans-serif;
  font-size: 14pt;
  font-style: italic;
  margin-bottom: 0.5em;
}

span.annotation {
  font-family: Helvetica, Arial, sans-serif;
  font-size: 14pt;
  font-style: italic;
  vertical-align: top;
  margin: 0 6pt;
  position: relative;
  top: 3pt;
}

/* ---- notation snippet (rendered score image) ---- */
.notation {
  margin: 0.5em 0;
}

.notation-img {
  max-width: 100%;
  height: auto;
}

.notation-ascii {
  font-family: 'Courier New', monospace;
  font-size: 11pt;
  background: #f4f4f4;
  padding: 4pt 6pt;
  white-space: pre-wrap;
}
"""


def generate_html(content, standalone=True, out_dir=None):
    songs = split_songs(content)
    fragments = []
    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        fragments.append(song_to_html(meta, chord_text, out_dir=out_dir))

    body = '\n'.join(fragments)

    if not standalone:
        return body

    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <title>Chord Sheet</title>\n'
        '  <style>\n' + CSS + '  </style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="sheet">\n'
        + body +
        '\n</div>\n'
        '</body>\n'
        '</html>'
    )



# ---------------------------------------------------------------------------
# TXT OUTPUT
# ---------------------------------------------------------------------------
# Plain ASCII render - same logic as the tokeniser but outputs pipe characters
# and standard notation instead of HTML. Fully editable in any text editor.

def generate_txt(content, out_dir=None):
    songs = split_songs(content)
    output_parts = []

    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        lines_out = []

        # Metadata header
        if meta.get('title'):
            lines_out.append(meta['title'])
        meta_line_parts = []
        for key in ('artist', 'key', 'time'):
            if meta.get(key):
                meta_line_parts.append(key.capitalize() + ': ' + meta[key])
        for key, val in meta.items():
            if key not in ('title', 'artist', 'key', 'time'):
                meta_line_parts.append(key.capitalize() + ': ' + val)
        if meta_line_parts:
            lines_out.append('  '.join(meta_line_parts))
        if lines_out:
            lines_out.append('')   # blank line after header

        for line in chord_text.splitlines():
            if not line.strip():
                lines_out.append('')
                continue
            if line.strip() == '===':
                lines_out.append('')   # page break has no plain-text equivalent
                continue
            if NOTATION_LINE_PAT.match(line.strip()):
                # Plain text preserves the source directive verbatim
                lines_out.append(line.strip())
                continue
            tokens = tokenise(line)
            parts = []
            for t in tokens:
                if t['type'] == 'annotation':
                    parts.append(t['text'])
                else:
                    left   = '|:' if t['left_deco'] == ':' else '|'
                    right  = (' :|' if t['right_deco'] == ':' else
                              (' ||' if t['right_deco'] == '||' else ''))
                    ending = ('(' + t['ending'] + ') ' if t['ending'] else '')
                    chords = expand_note_runs(t['chords'], 'txt')
                    parts.append(f"{left} {ending}{chords}{right}" if not right
                                 else f"{left} {ending}{chords}{right}")
            lines_out.append(' '.join(parts))

        output_parts.append('\n'.join(lines_out))

    return '\n\n'.join(output_parts)

# ---------------------------------------------------------------------------
# PDF OUTPUT
# ---------------------------------------------------------------------------

def generate_pdf(content, output_path, out_dir=None):
    if not PDF_SUPPORT:
        print("Error: weasyprint not available.")
        return
    html = generate_html(content, standalone=True, out_dir=out_dir)
    WeasyprintHTML(string=html).write_pdf(output_path)


# ---------------------------------------------------------------------------
# SINGLE FILE PROCESSING
# ---------------------------------------------------------------------------

def process_file(input_path, fmt, output_path=None):
    with open(input_path, 'r') as fh:
        content = fh.read()

    out = output_path or (input_path.rsplit('.', 1)[0] + '.' + fmt)
    out_dir = os.path.dirname(os.path.abspath(out))

    if fmt == 'txt':
        result = generate_txt(content, out_dir=out_dir)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'cho':
        result = generate_cho(content, out_dir=out_dir)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'html':
        result = generate_html(content, standalone=True, out_dir=out_dir)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'pdf':
        generate_pdf(content, out, out_dir=out_dir)

    print(f"Created {out}")


# ---------------------------------------------------------------------------
# BATCH PROCESSING
# ---------------------------------------------------------------------------

def process_folder(folder_path, fmt):
    subfolder = {'pdf': 'PDFs', 'html': 'HTMLs', 'cho': 'CHOs', 'txt': 'TXTs'}.get(fmt, fmt.upper() + 's')
    out_dir = os.path.join(folder_path, subfolder)
    os.makedirs(out_dir, exist_ok=True)

    txt_files = sorted(f for f in os.listdir(folder_path) if f.lower().endswith('.txt'))

    if not txt_files:
        print(f"No .txt files found in {folder_path}")
        return

    for fname in txt_files:
        input_path = os.path.join(folder_path, fname)
        out_name   = os.path.splitext(fname)[0] + '.' + fmt
        out_path   = os.path.join(out_dir, out_name)
        process_file(input_path, fmt, out_path)

    print(f"\nDone. {len(txt_files)} file(s) written to {out_dir}/")


# ---------------------------------------------------------------------------
# CHORD-OVER-LYRICS TO CHORDPRO CONVERTER
# ---------------------------------------------------------------------------
# Converts a traditional "chords above lyrics" text file into ChordPro format.
#
# Input format:
#   A chord line is a line consisting only of chord symbols and whitespace.
#   It is always immediately followed by its lyric line.
#   A blank line or a non-chord line that isn't preceded by a chord line
#   is passed through as-is (as a {comment:} or blank line).
#
# Algorithm:
#   For each (chord_line, lyric_line) pair, read the column position of
#   each chord token in the chord line, then insert [chord] at that
#   character index in the lyric line (padding with spaces if needed).

# This will be inserted into chord_tool.py replacing lines 710-805

CHORD_TOKEN_PAT = re.compile(
    r'([A-G][b#]?(m|maj|min|aug|dim|sus|o|ø|M)?\d?(\+|ø)?(/[A-G][b#]?)?)'
)

# Raw ChordPro directives: {anything}
CHORDPRO_DIRECTIVE_PAT = re.compile(r'^\{[^}]+\}\s*$')

# ChordPro grid rows: lines starting with |
CHORDPRO_GRID_ROW_PAT = re.compile(r'^\s*\|')


def is_chord_line(line):
    """Return True if the line contains only chord symbols and whitespace."""
    stripped = line.strip()
    if not stripped:
        return False
    if CHORDPRO_DIRECTIVE_PAT.match(stripped):
        return False
    if CHORDPRO_GRID_ROW_PAT.match(stripped):
        return False
    remainder = CHORD_TOKEN_PAT.sub('', stripped).strip()
    return remainder == ''


def merge_chords_into_lyric(chord_line, lyric_line):
    """
    Insert [chord] markers into lyric_line at the column positions
    where each chord appears in chord_line.

    Uses a slice-based approach: build the result by taking slices of
    the original lyric between chord column positions, so earlier
    insertions never shift the column indices of later chords.
    """
    chords_at = [(m.start(), m.group()) for m in CHORD_TOKEN_PAT.finditer(chord_line)]
    if not chords_at:
        return lyric_line

    # Pad lyric to at least the length of the chord line
    lyric = lyric_line.ljust(len(chord_line))

    # Slice the lyric between chord positions — no offset accumulation
    result = []
    prev_col = 0
    for col, chord in chords_at:
        result.append(lyric[prev_col:col])
        result.append('[' + chord + ']')
        prev_col = col
    result.append(lyric[prev_col:])

    return ''.join(result).rstrip()


def convert_chords_over_lyrics(content, title=None):
    """
    Convert a chord-over-lyrics text file to ChordPro format.

    Handles:
    - Optional --- metadata block
    - Chord line + lyric line pairs -> merged ChordPro inline chords
    - Lyrics-only lines -> plain text (no directive)
    - Blank lines -> passed through
    - Raw ChordPro directives {sog}, {eog}, {c:} etc -> verbatim passthrough
    - ChordPro grid rows starting with | -> verbatim passthrough
    - Instrumental chord line (followed by blank) -> {comment:}
    """
    lines_raw = content.splitlines()
    meta = {}
    start_line = 0

    # Parse optional --- metadata block
    if lines_raw and lines_raw[0].strip() == '---':
        close = next((i for i in range(1, len(lines_raw))
                      if lines_raw[i].strip() == '---'), None)
        if close:
            for line in lines_raw[1:close]:
                if ':' in line:
                    k, _, v = line.partition(':')
                    meta[k.strip().lower()] = v.strip()
            start_line = close + 1

    lines = lines_raw[start_line:]
    out = []

    # Header directives
    t = title or meta.get('title') or 'Untitled'
    out.append('{title: ' + t + '}')
    if meta.get('artist'): out.append('{artist: ' + meta['artist'] + '}')
    if meta.get('key'):    out.append('{key: '    + meta['key']    + '}')
    if meta.get('time'):   out.append('{time: '   + meta['time']   + '}')
    out.append('')

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Blank line
        if not stripped:
            out.append('')
            i += 1
            continue

        # Raw ChordPro directive -> verbatim
        if CHORDPRO_DIRECTIVE_PAT.match(stripped):
            out.append(stripped)
            i += 1
            continue

        # ChordPro grid row -> verbatim
        if CHORDPRO_GRID_ROW_PAT.match(stripped):
            out.append(stripped)
            i += 1
            continue

        # Chord line
        if is_chord_line(line):
            next_line = lines[i + 1] if i + 1 < len(lines) else ''
            next_stripped = next_line.strip()

            # Followed by a lyric line -> merge
            if (next_stripped
                    and not is_chord_line(next_line)
                    and not CHORDPRO_DIRECTIVE_PAT.match(next_stripped)
                    and not CHORDPRO_GRID_ROW_PAT.match(next_stripped)):
                out.append(merge_chords_into_lyric(line, next_line))
                i += 2
                continue

            # Followed by blank or end of file -> instrumental grid block
            # one chord per measure, no time signature available here
            chords_in_line = [m.group() for m in CHORD_TOKEN_PAT.finditer(stripped)]
            if chords_in_line:
                out.append('{start_of_grid}')
                row = ' '.join('| ' + c for c in chords_in_line) + ' |'
                out.append(row)
                out.append('{end_of_grid}')
            i += 1
            continue

        # Plain lyric line (no chord line above it) -> pass through as-is
        out.append(stripped)
        i += 1

    return '\n'.join(out)





# ===========================================================================
# ASCII NOTATION -> LILYPOND  (inlined from ascii_notation.py)
# ===========================================================================




NOTE_PAT = re.compile(
    r"""
    ^
    (?P<letter>[a-g])
    (?P<accidental>(?:\#|b)*)
    (?P<oct_up>'*)
    (?P<oct_down>,*)
    (?P<duration>\d*)
    $
    """,
    re.VERBOSE,
)

REST_PAT = re.compile(r"^x(?P<duration>\d*)$")

ACCIDENTAL_MAP = {
    "":   "",
    "#":  "is",
    "##": "isis",
    "b":  "es",
    "bb": "eses",
}

CLEF_MIDDLE_OCTAVE = {
    "treble": 4,
    "bass": 3,
}

_KEY_ROOT_PAT = re.compile(r"^([A-Ga-g])([#b]*)(m)?$")


def chord_key_to_lilypond(key_str):
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
    if not time_str:
        return None
    if not re.match(r"^\d+/\d+$", time_str):
        raise ValueError(f"Time signature must be N/M, got {time_str!r}")
    return time_str


def _ascii_pitch_to_lilypond(letter, accidental, octave_shift, clef):
    if accidental not in ACCIDENTAL_MAP:
        raise ValueError(f"Unsupported accidental: {accidental!r}")
    suffix = ACCIDENTAL_MAP[accidental]
    middle_octave = CLEF_MIDDLE_OCTAVE[clef] + octave_shift
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
    options = {}
    tokens = line.split()
    i = 0
    while i < len(tokens) and "=" in tokens[i] and tokens[i].count("=") == 1:
        key, val = tokens[i].split("=", 1)
        if re.match(r"^[a-z_]+$", key):
            options[key] = val
            i += 1
        else:
            break
    return options, " ".join(tokens[i:])


def convert_notation_line(notation, default_clef="treble"):
    options, body = parse_options(notation)
    clef = options.get("clef", default_clef)
    if clef not in CLEF_MIDDLE_OCTAVE:
        raise ParseError(f"Unknown clef: {clef!r}. Use 'treble' or 'bass'.")

    key = options.get("key")
    if key:
        try:
            chord_key_to_lilypond(key)
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
    current_duration = None

    for tok in tokens:
        if tok == "|":
            out.append("|")
            continue
        if tok == "(":
            out.append("__SLUR_OPEN__")
            continue
        if tok == ")":
            out.append("__SLUR_CLOSE__")
            continue
        if tok == "[":
            out.append("__BEAM_OPEN__")
            continue
        if tok == "]":
            out.append("__BEAM_CLOSE__")
            continue

        prefix_slur = ""
        suffix_slur = ""
        prefix_beam = ""
        suffix_beam = ""
        while tok and tok[0] in "([":
            if tok[0] == "(":
                prefix_slur = "("
            else:
                prefix_beam = "["
            tok = tok[1:]
        while tok and tok[-1] in ")]":
            if tok[-1] == ")":
                suffix_slur = ")"
            else:
                suffix_beam = "]"
            tok = tok[:-1]

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
                out.append("__SLUR_OPEN__")
            if prefix_beam:
                out.append("__BEAM_OPEN__")
            out.append(lily_tok)
            if suffix_slur:
                out.append("__SLUR_CLOSE__")
            if suffix_beam:
                out.append("__BEAM_CLOSE__")
            continue

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
        if len(oct_up) > 1 or len(oct_down) > 1:
            raise ParseError(
                f"Only three octaves supported; got {tok!r}. Use a single ' or , mark."
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
                f"First note '{tok}' must declare a duration (e.g. '{tok}8')."
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

    resolved = []
    in_manual_beam = []
    pending_slur_open = False
    pending_beam_open = False
    manual_beam_depth = 0

    def _attach_suffix(suffix):
        for i in range(len(resolved) - 1, -1, -1):
            if resolved[i] != "|":
                resolved[i] = resolved[i] + suffix
                return

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

        if item == "|":
            resolved.append(item)
            in_manual_beam.append(False)
            continue

        token_str = item
        if pending_slur_open:
            token_str = token_str + "("
            pending_slur_open = False
        if pending_beam_open:
            token_str = token_str + "["
            pending_beam_open = False
        resolved.append(token_str)
        in_manual_beam.append(manual_beam_depth > 0)

    resolved = _auto_beam(resolved, in_manual_beam)

    return " ".join(resolved), {"clef": clef, "key": key, "time": time_sig}


def _token_duration(tok):
    core = tok.rstrip("()[]")
    m = re.search(r"(\d+)$", core)
    if not m:
        return None
    return int(m.group(1))


def _is_rest(tok):
    core = tok.lstrip("([")
    return core.startswith("r")


def _auto_beam(tokens, in_manual_beam):
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


def build_lilypond_snippet(notation, default_clef="treble", version="2.24.0"):
    music, opts = convert_notation_line(notation, default_clef=default_clef)
    clef = opts["clef"]
    key = opts["key"]
    time_sig = opts["time"]

    staff_lines = [f'    \\clef "{clef}"']
    if key:
        staff_lines.append(f"    \\key {chord_key_to_lilypond(key)}")
    if time_sig:
        staff_lines.append(f"    \\time {time_sig}")
        staff_lines.append(f"    {music}")
    else:
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


# ===========================================================================
# NOTATION INTEGRATION  (ascii_notation -> LilyPond -> PNG)
# ===========================================================================
# A {notation: ...} directive on its own line in the chord text is rendered
# to a cropped music image via LilyPond and embedded in the output.
#
# Source syntax (always single line, single voice):
#     {notation: <inline options> <ascii body>}
#   inline options use ascii_notation's key=value convention:
#     clef=bass   time=3/4   key=Em   id=A
#   id= is integration-specific: a short label used in .cho filenames/labels.
#
# Key inheritance: if the directive has no key= option, the song's {key:}
# metadata is used; if neither, C major (no key signature).
#
# Per-format behavior:
#   txt  -> directive line passes through verbatim
#   cho  -> .ly + .png saved as sibling files; {comment:}+{image:} emitted
#   html -> PNG embedded as base64 data URI inside <img class="notation">
#   pdf  -> same HTML, so the embedded image carries through WeasyPrint
#
# LilyPond is invoked as a subprocess with -dcrop --png. If it is not on
# PATH, one warning is printed per run and snippets fall back to .ly-only
# (cho) or an ASCII <pre> block (html/pdf). A malformed snippet is caught,
# warned about, and falls back the same way without aborting the run.
#
# Rendered files are cached by content hash so identical snippets render once.

import hashlib
import shutil
import subprocess
import base64

# Module-level flags so warnings print only once per run.
_LILYPOND_CHECKED = False
_LILYPOND_PATH = None
_LILYPOND_WARNED = False
# Global switch set by the CLI (--no-notation).
NOTATION_DISABLED = False

NOTATION_LINE_PAT = re.compile(r'^\{\s*notation:\s*(.*?)\s*\}$', re.IGNORECASE)


def _lilypond_available():
    """Locate lilypond once; cache the result for the whole run."""
    global _LILYPOND_CHECKED, _LILYPOND_PATH
    if not _LILYPOND_CHECKED:
        _LILYPOND_PATH = shutil.which('lilypond')
        _LILYPOND_CHECKED = True
    return _LILYPOND_PATH is not None


def _warn_no_lilypond():
    global _LILYPOND_WARNED
    if not _LILYPOND_WARNED:
        print("Warning: lilypond not found on PATH; notation snippets will be "
              "saved as .ly files only. Render them manually in Frescobaldi, "
              "or install lilypond to embed images automatically.")
        _LILYPOND_WARNED = True


def parse_notation_directive(body, song_key=None):
    """
    Split a {notation: ...} body into (id, ascii_for_converter).

    - Pulls out an id= option (integration-specific, not passed to the
      converter).
    - If the body has no key= option and song_key is given, injects
      key=<song_key> so the snippet inherits the song's key.
    Returns (snippet_id, converter_input_string).
    """
    tokens = body.split()
    snippet_id = None
    has_key = False
    kept = []
    for tok in tokens:
        if tok.startswith('id=') and tok.count('=') == 1:
            snippet_id = tok.split('=', 1)[1]
            continue
        if tok.startswith('key=') and tok.count('=') == 1:
            has_key = True
        kept.append(tok)

    converter_input = ' '.join(kept)
    if not has_key and song_key:
        converter_input = f'key={song_key} ' + converter_input
    return snippet_id, converter_input


def _notation_hash(converter_input):
    return hashlib.sha1(converter_input.encode('utf-8')).hexdigest()[:12]


def render_notation(body, song_key, out_dir):
    """
    Resolve one {notation:} directive into rendered artifacts.

    Writes .ly (always, when possible) and .png (if lilypond present) into
    NotationLY/ and NotationPNG/ subfolders of out_dir, keyed by content
    hash. Uses the cache if the .png already exists.

    Returns a dict describing the result:
      { 'ok': bool,
        'id': str|None,
        'hash': str,
        'ly_path': str|None,       # absolute path, may be None on parse error
        'png_path': str|None,      # absolute path if rendered, else None
        'png_rel': str|None,       # path relative to out_dir for {image:}
        'ascii': str,              # original body (for fallback display)
        'error': str|None }
    """
    snippet_id, converter_input = parse_notation_directive(body, song_key)
    result = {
        'ok': False, 'id': snippet_id, 'hash': None,
        'ly_path': None, 'png_path': None, 'png_rel': None,
        'ascii': body, 'error': None,
    }

    # Convert ASCII -> LilyPond source.
    try:
        ly_source = build_lilypond_snippet(converter_input)
    except Exception as e:   # ParseError or anything unexpected
        result['error'] = str(e)
        return result

    h = _notation_hash(converter_input)
    result['hash'] = h
    base = (snippet_id + '-' + h) if snippet_id else h

    ly_dir = os.path.join(out_dir, 'NotationLY')
    png_dir = os.path.join(out_dir, 'NotationPNG')
    ly_path = os.path.join(ly_dir, base + '.ly')
    png_path = os.path.join(png_dir, base + '.png')

    # Cache hit: png already rendered.
    if os.path.exists(png_path):
        result.update(ok=True, ly_path=ly_path, png_path=png_path,
                      png_rel=os.path.join('NotationPNG', base + '.png'))
        return result

    # Write the .ly file (always useful, even without lilypond).
    os.makedirs(ly_dir, exist_ok=True)
    with open(ly_path, 'w') as fh:
        fh.write(ly_source)
    result['ly_path'] = ly_path

    if not _lilypond_available():
        _warn_no_lilypond()
        result['ok'] = True   # .ly written; caller falls back for image
        return result

    # Render the PNG via lilypond -dcrop --png.
    os.makedirs(png_dir, exist_ok=True)
    out_base = os.path.join(png_dir, base)
    try:
        proc = subprocess.run(
            [_LILYPOND_PATH, '-dcrop', '--png', '-dresolution=200',
             '-o', out_base, ly_path],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        result['error'] = f"lilypond invocation failed: {e}"
        return result

    # lilypond -dcrop writes <out_base>.cropped.png
    cropped = out_base + '.cropped.png'
    if os.path.exists(cropped):
        os.replace(cropped, png_path)
    if os.path.exists(png_path):
        result.update(ok=True, png_path=png_path,
                      png_rel=os.path.join('NotationPNG', base + '.png'))
    else:
        result['error'] = (proc.stderr or 'lilypond produced no output').strip()[:300]
    return result


def notation_to_html(render_result):
    """Render a notation result as an HTML fragment (base64-embedded image)."""
    if render_result.get('png_path') and os.path.exists(render_result['png_path']):
        with open(render_result['png_path'], 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode('ascii')
        return ('<div class="notation">'
                '<img class="notation-img" alt="notation" '
                'src="data:image/png;base64,' + b64 + '"></div>')
    # Fallback: show the ASCII source in a <pre>.
    note = ''
    if render_result.get('error'):
        note = ' (notation error: ' + render_result['error'] + ')'
    elif not _lilypond_available():
        note = ' (install lilypond to render)'
    return ('<div class="notation"><pre class="notation-ascii">'
            + render_result.get('ascii', '') + note + '</pre></div>')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert a chord-over-lyrics sheet (default) or chord '
                    'shorthand (--chordsheet) to .cho / .txt / .html / .pdf')
    parser.add_argument('input',
                        help='Source .txt file, or folder path with --batch')
    parser.add_argument('-f', '--format', choices=['cho', 'html', 'pdf', 'txt'],
                        default='cho', help='Output format (default: cho)')
    parser.add_argument('-o', '--output',
                        help='Output filename (single-file mode only)')
    parser.add_argument('-b', '--batch', action='store_true',
                        help='Batch-convert all .txt files in the given folder')
    parser.add_argument('--chordsheet', action='store_true',
                        help='Treat input as chord shorthand (comma-barline '
                             'notation) instead of a chord-over-lyrics sheet')
    # --convert kept as a hidden no-op alias for backwards compatibility:
    # chord-over-lyrics conversion is now the default behaviour.
    parser.add_argument('--convert', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--title', help='Song title for chord-over-lyrics mode')
    parser.add_argument('--no-notation', action='store_true',
                        help='Skip LilyPond rendering; treat {notation:} as a comment')
    args = parser.parse_args()

    global NOTATION_DISABLED
    if args.no_notation:
        NOTATION_DISABLED = True

    # Default mode: chord-over-lyrics conversion (unless --chordsheet given).
    lyrics_mode = not args.chordsheet

    if lyrics_mode and args.batch:
        if not os.path.isdir(args.input):
            print(f"Error: '{args.input}' is not a directory.")
            return
        out_dir = os.path.join(args.input, 'CHOs')
        os.makedirs(out_dir, exist_ok=True)
        txt_files = sorted(f for f in os.listdir(args.input) if f.lower().endswith('.txt'))
        if not txt_files:
            print(f"No .txt files found in {args.input}")
            return
        for fname in txt_files:
            input_path = os.path.join(args.input, fname)
            with open(input_path, 'r') as fh:
                content = fh.read()
            title = args.title or os.path.splitext(fname)[0]
            result = convert_chords_over_lyrics(content, title)
            out_path = os.path.join(out_dir, os.path.splitext(fname)[0] + '.cho')
            with open(out_path, 'w') as fh:
                fh.write(result)
            print(f"Created {out_path}")
        print(f"\nDone. {len(txt_files)} file(s) written to {out_dir}/")
        return

    if lyrics_mode:
        if not os.path.isfile(args.input):
            print(f"Error: '{args.input}' not found.")
            return
        with open(args.input, 'r') as fh:
            content = fh.read()
        title = args.title or os.path.splitext(os.path.basename(args.input))[0]
        result = convert_chords_over_lyrics(content, title)
        out = args.output or (args.input.rsplit('.', 1)[0] + '.cho')
        with open(out, 'w') as fh:
            fh.write(result)
        print(f"Created {out}")
        return

    # --chordsheet mode: original comma-barline shorthand pipeline.
    if args.batch:
        if not os.path.isdir(args.input):
            print(f"Error: '{args.input}' is not a directory.")
            return
        process_folder(args.input, args.format)
    else:
        if not os.path.isfile(args.input):
            print(f"Error: '{args.input}' not found.")
            return
        process_file(args.input, args.format, args.output)


if __name__ == '__main__':
    main()
