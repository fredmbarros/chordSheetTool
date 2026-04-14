# chord_tool — Documentation

A command-line interpreter that converts plain-text chord sheets into HTML or PDF files, with optional ChordPro (`.cho`) output for use with apps like Songbook Pro.

---

## Setup

### Requirements

- Python 3.9 or later
- `weasyprint` (for PDF output only)

### Installing weasyprint

Create a virtual environment in your project folder first (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
pip install weasyprint
```

If you see an error about `libpango` on macOS, install the system graphics libraries via Homebrew:

```bash
brew install pango cairo
```

Then re-run `pip install weasyprint`.

### Activating the environment

Every time you open a new terminal session, activate the environment before using the tool:

```bash
source /path/to/your/project/venv/bin/activate
```

---

## Usage

```
python chord_tool.py <input> [options]
```

### Single file

```bash
python chord_tool.py song.txt              # outputs song.html (default)
python chord_tool.py song.txt -f html      # same as above, explicit
python chord_tool.py song.txt -f pdf       # outputs song.pdf
python chord_tool.py song.txt -f cho       # outputs song.cho (ChordPro)
python chord_tool.py song.txt -f pdf -o MySong.pdf   # custom output filename
```

### Batch mode (entire folder)

```bash
python chord_tool.py /path/to/folder -b           # all .txt files → HTMLs/
python chord_tool.py /path/to/folder -b -f pdf    # all .txt files → PDFs/
python chord_tool.py /path/to/folder -b -f cho    # all .txt files → CHOs/
```

Output files are placed in a subfolder named `HTMLs`, `PDFs`, or `CHOs` inside the source folder. The subfolder is created automatically if it doesn't exist.

---

## Flags and options

| Flag | Long form | Description |
|------|-----------|-------------|
| `-f` | `--format` | Output format: `html`, `pdf`, or `cho`. Default: `html` |
| `-o` | `--output` | Custom output filename (single-file mode only) |
| `-b` | `--batch`  | Batch mode: process all `.txt` files in the given folder |

---

## Output formats

### HTML (`-f html`)
The default output. Opens in any browser. The CSS is embedded directly in the file, so it is fully self-contained — no external stylesheets needed. This is the best format for previewing and iterating on your layout, since you can edit the CSS block inside `chord_tool.py` and re-run to see changes immediately.

### PDF (`-f pdf`)
Rendered from the same HTML via WeasyPrint. What you see in the browser is what you get in the PDF. Page breaks (`===` in the source) are honoured. Requires WeasyPrint and its system dependencies to be installed.

### ChordPro (`-f cho`)
Outputs a `.cho` file compatible with Songbook Pro and other ChordPro readers. Chord symbols are wrapped in brackets (`[Am7]`). Annotations are rendered as comments (`# text`). Page breaks have no equivalent and are silently skipped.

---

## Source file format

Source files are plain `.txt` files. A file can contain one or more songs.

---

### Song structure

Each song is wrapped in a metadata block delimited by `---`. The metadata block is optional for single-song files but required when a file contains multiple songs.

```
---
title: Garota de Ipanema
artist: Tom Jobim
key: F
time: 4/4
---
chord lines go here
```

The closing `---` of one song is also the opening `---` of the next:

```
---
title: First Song
key: C
---
A , E7 , A ;
---
title: Second Song
key: G
---
D , G , D ;
```

**Supported metadata fields:** `title`, `artist`, `key`, `time`. Any additional fields you add (e.g. `capo: 2`) will also be displayed.

---

## Cheat sheet — source syntax

### Barlines

| Source | Rendered | Meaning |
|--------|----------|---------|
| `,` | `\|` | Plain barline |
| `,:` | `\|:` | Repeat open (ritornello start) |
| `:,` | `:\|` | Repeat close (ritornello end) |
| `;` | `\|\|` | Final double barline (end of piece/section) |

Each comma (or decorated comma) separates one measure from the next. Everything between two barlines is one measure, and a measure will never be split across a line when wrapping.

**Example:**
```
A , E7 ,: A , A7 , D D#o ,[1] A , Bm E7 :,[2] A E7 , A ;
```
Renders as:
```
| A | E7 |: A | A7 | D D#o |(1) A | Bm E7 :| (2) A E7 | A ||
```

---

### Repeat endings (volta brackets)

Write the ending number in square brackets immediately after the barline comma, with no space:

```
,[1]    ->  first ending
,[2]    ->  second ending
```

The brackets are converted to a small black box with white text in the rendered output.

**Example:**
```
A , Bm E7 ,[1] A , E7 :,[2] A ;
```

---

### Two chords in one measure

Simply put both chords separated by a space inside the measure:

```
D , D#o Am , G ;
```
The `D#o Am` measure contains two chords implying a change on beat 3 (or however you choose to interpret it).

---

### Section breaks

A blank line in the source creates a visual gap between sections (verse, chorus, bridge, etc.):

```
A , E7 , A , E7 ;

D , G , D , A7 ;
```

---

### Text annotations

Wrap any text in curly braces `{ }`. Annotations can appear on their own line or inline within a chord line.

**Standalone (own line):**
```
{D.C. al Coda}
{repeat 3x}
{Chorus}
```
Renders as a block of italic text above or below the chord lines.

**Inline (within a chord line):**
```
Am , E7 , {to Coda} Am , Dm ;
```
The annotation appears between the measures it sits between.

**Leading (before the first measure):**
```
{Verse} Am , E7 , Am ;
```

---

### Page break

A line containing only `===` forces a new page in both HTML (print) and PDF output:

```
Am , E7 , Am ;
===
D , G , D ;
```

In a browser window, `===` is invisible. In print / PDF, everything after it starts on a new page.

---

## Styling

The CSS that controls the appearance of the HTML and PDF output is stored as the `CSS` variable near the top of the HTML rendering section in `chord_tool.py`. Edit it directly in the script — every time you run the interpreter the new styles will be applied.

Available CSS selectors:

| Selector | What it targets |
|----------|----------------|
| `.sheet` | Outermost wrapper |
| `.song` | One song block |
| `.song-title` | Song title (centered by default) |
| `.song-meta` | Metadata line (artist, key, time…) |
| `.meta-label` | The bold label part ("Key:", "Time:") |
| `.section` | One line of chord content |
| `.spacer` | Blank-line gap between sections |
| `.page-break` | Invisible div that triggers a page break |
| `.measure` | One bar — the core layout unit |
| `.measure.repeat-open` | A measure whose left barline is `\|:` |
| `.measure.repeat-close` | A measure whose right barline is `:\|` |
| `.measure.final` | A measure whose right barline is `\|\|` |
| `.dots` | The `:` repeat dot character inside the barline |
| `.ending` | Volta number (1, 2…) with black background |
| `.chord` | Individual chord symbol |
| `div.annotation` | A standalone `{text}` line |
| `span.annotation` | An inline `{text}` within a chord line |

---

## Complete source example

```
---
title: Example Song
artist: Fred Barros
key: A
time: 4/4
---
{Verse}
A , E7 ,: A , A7 , D D#o ,[1] A , Bm E7 :,[2] A E7 , A ;

{Chorus}
D , G , D , A7 , D ;

{Bridge}
Bm , F#m , Bm , E7 ;
{repeat 2x}
Bm , F#m , E7 , A ;
===
---
title: Another Song
key: Dm
---
Dm , A7 ,: Dm , Gm , A7 :, Dm ;
{D.C. al Fine}
```
