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

def normalise_chords(raw):
    return ' '.join(raw.split())


def tokenise(line):
    s = line.replace('[', '(').replace(']', ')')
    SEP = re.compile(r'(,:|:,|,|;)')
    parts = SEP.split(s)

    measures = []
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

        chords = normalise_chords(chunk)
        if chords:
            ending_match = re.match(r'^\((\d+)\)\s*(.*)', chords)
            if ending_match:
                ending = ending_match.group(1)
                chords = ending_match.group(2)
            else:
                ending = ''
            measures.append({
                'chords':     chords,
                'ending':     ending,
                'left_deco':  pending_left,
                'right_deco': right_deco,
            })

        pending_left = next_left

    return measures


# ---------------------------------------------------------------------------
# METADATA / SONG SPLITTING
# ---------------------------------------------------------------------------
# File format:
#
#   ---            <- opens metadata block
#   title: My Song
#   artist: Someone
#   key: F
#   time: 4/4
#   ---            <- closes metadata block; chord lines follow
#   A , E7 ,: A ...
#   (blank line = section break inside song)
#   ---            <- opens next song's metadata block
#   title: Another Song
#   ---
#   D , G , D ;
#
# Files with no --- at all are treated as a single song with no metadata.

def split_songs(content):
    """
    Returns a list of (meta_body_str, chord_body_str) tuples.
    meta_body_str is the raw text between the --- delimiters (may be empty).
    chord_body_str is the chord lines that follow.
    """
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

def generate_cho(content):
    chord_pat = r'\b([A-G][b#]?(m|maj|min|aug|dim|sus|o)?\d?(/[A-G][b#]?)?)\b'
    songs = split_songs(content)
    output_parts = []

    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        title = meta.get('title', 'Chord Sheet')
        lines_out = ['{title: ' + title + '}', '{type: chords}', '']

        for line in chord_text.splitlines():
            if not line.strip():
                lines_out.append('')
                continue
            measures = tokenise(line)
            parts = []
            for m in measures:
                left  = '|:' if m['left_deco'] == ':' else '|'
                right = (' :|' if m['right_deco'] == ':' else
                         (' ||' if m['right_deco'] == '||' else ''))
                ending = m.get('ending', '')
                chords = re.sub(chord_pat, r'[\1]', m['chords'])
                parts.append(f"{left}{ending} {chords}{right}" if ending
                              else f"{left} {chords}{right}")
            lines_out.append(' '.join(parts))

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
    return CHORD_PAT.sub(r'<span class="chord">\1</span>', text)


def measure_to_html(m):
    classes = ['measure']
    if m['left_deco'] == ':':
        classes.append('repeat-open')
    if m['right_deco'] == ':':
        classes.append('repeat-close')
    if m['right_deco'] == '||':
        classes.append('final')

    left_dots   = DOTS if m['left_deco'] == ':' else ''
    right_dots  = DOTS if m['right_deco'] == ':' else ''
    ending_html = ('<span class="ending">' + m['ending'] + '</span>'
                   if m['ending'] else '')
    chords_html = chords_to_spans(m['chords'])

    return ('<span class="' + ' '.join(classes) + '">'
            + left_dots + ending_html + chords_html + right_dots
            + '</span>')


def song_to_html(meta, chord_text):
    html = '<div class="song">\n'

    if meta.get('title'):
        html += '<h2 class="song-title">' + meta['title'] + '</h2>\n'

    # Known fields in display order, then any extras the user added
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

    for line in chord_text.splitlines():
        if not line.strip():
            html += '<div class="spacer"></div>\n'
            continue
        measures = tokenise(line)
        inner = ''.join(measure_to_html(m) for m in measures)
        html += '<div class="section">' + inner + '</div>\n'

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
     .measure            one bar (inline-block, never breaks)
     .measure.repeat-open    left side is |:
     .measure.repeat-close   right side is :|
     .measure.final          right side is ||
     .dots               repeat colon sitting inside the barline
     .ending             volta number e.g. 1  2
     .chord              individual chord symbol
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
  margin: 0 0 0.3em 0;
}

.song-meta {
  font-size: 11pt;
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
"""


def generate_html(content, standalone=True):
    songs = split_songs(content)
    fragments = []
    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        fragments.append(song_to_html(meta, chord_text))

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
# PDF OUTPUT
# ---------------------------------------------------------------------------

def generate_pdf(content, output_path):
    if not PDF_SUPPORT:
        print("Error: weasyprint not available.")
        return
    html = generate_html(content, standalone=True)
    WeasyprintHTML(string=html).write_pdf(output_path)
    print(f"Created {output_path}")


# ---------------------------------------------------------------------------
# SINGLE FILE PROCESSING
# ---------------------------------------------------------------------------

def process_file(input_path, fmt, output_path=None):
    with open(input_path, 'r') as fh:
        content = fh.read()

    out = output_path or (input_path.rsplit('.', 1)[0] + '.' + fmt)

    if fmt == 'cho':
        result = generate_cho(content)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'html':
        result = generate_html(content, standalone=True)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'pdf':
        generate_pdf(content, out)

    print(f"Created {out}")


# ---------------------------------------------------------------------------
# BATCH PROCESSING
# ---------------------------------------------------------------------------

def process_folder(folder_path, fmt):
    subfolder = {'pdf': 'PDFs', 'html': 'HTMLs', 'cho': 'CHOs'}.get(fmt, fmt.upper() + 's')
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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert chord shorthand (.txt) to .cho / .html / .pdf')
    parser.add_argument('input',
                        help='Source .txt file, or folder path with --batch')
    parser.add_argument('-f', '--format', choices=['cho', 'html', 'pdf'],
                        default='html', help='Output format (default: html)')
    parser.add_argument('-o', '--output',
                        help='Output filename (single-file mode only)')
    parser.add_argument('-b', '--batch', action='store_true',
                        help='Batch-convert all .txt files in the given folder')
    args = parser.parse_args()

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