import re
import argparse

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
#   [n] ending number            ->  (n) flush against barline

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
                ending = ending_match.group(1)   # just the digit(s), no parens
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
# CHO OUTPUT
# ---------------------------------------------------------------------------

def generate_cho(content):
    chord_pat = r'\b([A-G][b#]?(m|maj|min|aug|dim|sus|o)?\d?(/[A-G][b#]?)?)\b'
    lines = content.strip().split('\n')
    output = ['{title: Chord Sheet}', '{type: chords}', '']

    for line in lines:
        if not line.strip():
            output.append('')
            continue

        measures = tokenise(line)
        parts = []
        for m in measures:
            left  = '|:' if m['left_deco'] == ':' else '|'
            right = (' :|' if m['right_deco'] == ':' else
                     (' ||' if m['right_deco'] == '||' else ''))
            ending = m.get('ending', '')
            chords = re.sub(chord_pat, r'[\1]', m['chords'])
            parts.append(f"{left}{ending} {chords}{right}" if ending else f"{left} {chords}{right}")

        output.append(' '.join(parts))

    return '\n'.join(output)


# ---------------------------------------------------------------------------
# HTML OUTPUT
# ---------------------------------------------------------------------------
# Classes emitted:
#   .sheet              outermost container
#   .section            one source line (paragraph break on Enter)
#   .measure            one bar; never breaks internally
#   .measure.repeat-open    |:
#   .measure.repeat-close   :|
#   .measure.final          ||
#   .dots-left          the two stacked dots for |: (real HTML, not CSS content)
#   .dots-right         the two stacked dots for :|
#   .ending             the (1) / (2) number inside a measure
#   .chord              each individual chord symbol

CHORD_PAT = re.compile(
    r'\b([A-G][b#]?(m|maj|min|aug|dim|sus|o)?\d?(/[A-G][b#]?)?)\b'
)

# Two stacked middle-dots as real HTML — avoids all CSS content escape issues
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

    left_dots  = DOTS if m['left_deco'] == ':' else ''
    right_dots = DOTS if m['right_deco'] == ':' else ''
    ending_html = '<span class="ending">' + m['ending'] + '</span>' if m['ending'] else ''
    chords_html = chords_to_spans(m['chords'])

    return ('<span class="' + ' '.join(classes) + '">'
            + left_dots + ending_html + chords_html + right_dots
            + '</span>')


# ---------------------------------------------------------------------------
# CSS  — edit this block to restyle the output
# ---------------------------------------------------------------------------
CSS = """
/* -------------------------------------------------------
   Selectors:
     .sheet              outermost wrapper
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
/* .dots is a simple ":" sitting just inside the barline.
   It is absolutely positioned so you can move it
   independently of the chord content.
   - "left" / "right" controls its distance from the barline.
   - "font-size" controls its size.
   The chord spacing is controlled purely by the
   padding-left / padding-right of .measure.repeat-open/close. */

.dots {
  position: absolute;
  top: 50%;
  transform: translateY(-55%);
  font-size: 20pt;
  font-weight: bold;
  line-height: 1;
}

.measure.repeat-open .dots  { left: -1pt; }   /* distance from left barline */
.measure.repeat-close .dots { right: -1pt; }  /* distance from right barline */

.measure.repeat-open {
  padding-left: 20pt;   /* push chord away from barline+colon */
}

.measure.repeat-close {
  padding-right: 20pt;  /* push chord away from barline+colon */
}

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
    lines = content.strip().split('\n')
    sections = []

    for line in lines:
        if not line.strip():
            sections.append('<div class="spacer"></div>')
            continue
        measures = tokenise(line)
        inner = ''.join(measure_to_html(m) for m in measures)
        sections.append('<div class="section">' + inner + '</div>')

    body = '\n'.join(sections)

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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert chord shorthand (.txt) to .cho / .html / .pdf')
    parser.add_argument('input', help='Source .txt file')
    parser.add_argument('-f', '--format', choices=['cho', 'html', 'pdf'],
                        default='cho', help='Output format (default: cho)')
    parser.add_argument('-o', '--output', help='Output filename')
    args = parser.parse_args()

    with open(args.input, 'r') as fh:
        content = fh.read()

    out = args.output or (args.input.rsplit('.', 1)[0] + f'.{args.format}')

    if args.format == 'cho':
        result = generate_cho(content)
        with open(out, 'w') as fh:
            fh.write(result)
        print(f"Created {out}")
    elif args.format == 'html':
        result = generate_html(content, standalone=True)
        with open(out, 'w') as fh:
            fh.write(result)
        print(f"Created {out}")
    else:
        generate_pdf(content, out)


if __name__ == '__main__':
    main()