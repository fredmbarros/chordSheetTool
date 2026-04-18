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

def normalise_chords(raw):
    return ' '.join(raw.split())


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

def generate_cho(content):
    songs = split_songs(content)
    output_parts = []

    for meta_body, chord_text in songs:
        meta = parse_meta(meta_body)
        title = meta.get('title', 'Chord Sheet')
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
                    chords_in_measure = len(t['chords'].split())
                    if beats and chords_in_measure < beats:
                        padding = ' ' + ' '.join(['.'] * (beats - chords_in_measure))
                    else:
                        padding = ''
                    parts.append(f"{left} {ending}{t['chords']}{padding}{right}")
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


def song_to_html(meta, chord_text):
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

    for line in chord_text.splitlines():
        if not line.strip():
            html += '<div class="spacer"></div>\n'
            continue
        if line.strip() == '===':
            html += '<div class="page-break"></div>\n'
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
# TXT OUTPUT
# ---------------------------------------------------------------------------
# Plain ASCII render - same logic as the tokeniser but outputs pipe characters
# and standard notation instead of HTML. Fully editable in any text editor.

def generate_txt(content):
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
                    chords = t['chords']
                    parts.append(f"{left} {ending}{chords}{right}" if not right
                                 else f"{left} {ending}{chords}{right}")
            lines_out.append(' '.join(parts))

        output_parts.append('\n'.join(lines_out))

    return '\n\n'.join(output_parts)

# ---------------------------------------------------------------------------
# PDF OUTPUT
# ---------------------------------------------------------------------------

def generate_pdf(content, output_path):
    if not PDF_SUPPORT:
        print("Error: weasyprint not available.")
        return
    html = generate_html(content, standalone=True)
    WeasyprintHTML(string=html).write_pdf(output_path)


# ---------------------------------------------------------------------------
# SINGLE FILE PROCESSING
# ---------------------------------------------------------------------------

def process_file(input_path, fmt, output_path=None):
    with open(input_path, 'r') as fh:
        content = fh.read()

    out = output_path or (input_path.rsplit('.', 1)[0] + '.' + fmt)

    if fmt == 'txt':
        result = generate_txt(content)
        with open(out, 'w') as fh:
            fh.write(result)
    elif fmt == 'cho':
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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert chord shorthand (.txt) to .txt / .cho / .html / .pdf')
    parser.add_argument('input',
                        help='Source .txt file, or folder path with --batch')
    parser.add_argument('-f', '--format', choices=['cho', 'html', 'pdf', 'txt'],
                        default='cho', help='Output format (default: cho)')
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