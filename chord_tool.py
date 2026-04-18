# chord_tool — Documentation

A command-line interpreter that converts plain-text chord sheets into ChordPro, HTML, PDF, or plain text files.

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
python chord_tool.py song.txt              # outputs song.cho (default)
python chord_tool.py song.txt -f cho       # same as above, explicit
python chord_tool.py song.txt -f txt       # outputs song.txt (plain ASCII)
python chord_tool.py song.txt -f html      # outputs song.html
python chord_tool.py song.txt -f pdf       # outputs song.pdf
python chord_tool.py song.txt -f pdf -o MySong.pdf   # custom output filename
```

### Batch mode (entire folder)

```bash
python chord_tool.py /path/to/folder -b           # all .txt files → CHOs/
python chord_tool.py /path/to/folder -b -f txt    # all .txt files → TXTs/
python chord_tool.py /path/to/folder -b -f html   # all .txt files → HTMLs/
python chord_tool.py /path/to/folder -b -f pdf    # all .txt files → PDFs/
```

Output files are placed in a subfolder (`CHOs`, `TXTs`, `HTMLs`, or `PDFs`) inside the source folder. The subfolder is created automatically if it does not exist.

---

## Flags and options

| Flag | Long form | Description |
|------|-----------|-------------|
| `-f` | `--format` | Output format: `cho`, `txt`, `html`, or `pdf`. Default: `cho` |
| `-o` | `--output` | Custom output filename (single-file mode only) |
| `-b` | `--batch`  | Batch mode: process all `.txt` files in the given folder |

---

## Output formats

### ChordPro (`-f cho`) — default
Outputs a `.cho` file compatible with Songbook Pro and other ChordPro readers. Uses the `{start_of_grid}` / `{end_of_grid}` directives for chord-only layout. Metadata fields (`title`, `artist`, `key`, `time`) become proper ChordPro directives. Annotations become `{comment: }` directives.

If a `time` signature is provided in the metadata (e.g. `time: 4/4`), each measure is padded with beat dots automatically — so a single chord in 4/4 becomes `| Am7 . . . |`, and two chords become `| Am7 G7 . . |`. Without a time signature, no dots are added.

### Plain text (`-f txt`)
Outputs a clean, readable `.txt` file with standard ASCII notation: `|`, `|:`, `:|`, `||` barlines, `(1)` / `(2)` ending numbers, annotations as bare text. Fully editable in any text editor. Page breaks (`===`) become blank lines.

### HTML (`-f html`)
Self-contained `.html` file that opens in any browser with no external stylesheets needed. Best for previewing and tweaking the layout. The CSS lives in `chord_tool.py` as the `CSS` variable — edit it there and re-run to update all output.

### PDF (`-f pdf`)
Rendered from the same HTML via WeasyPrint. What you see in the browser is what you get in the PDF. Page breaks (`===`) are honoured. Requires WeasyPrint and its system dependencies.

---

## Source file format

Source files are plain `.txt` files. A file can contain one or more songs.

---

### Song structure

Each song is optionally wrapped in a metadata block delimited by `---`. The metadata block is optional for single-song files but required when a file contains multiple songs.

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

**Supported metadata fields:** `title`, `artist`, `key`, `time`. Any additional fields you add (e.g. `capo: 2`) will also be displayed in HTML/PDF output and passed through as directives in ChordPro.

---

## Cheat sheet — source syntax

### Barlines

| Source | Rendered | Meaning |
|--------|----------|---------|
| `,` | `|` | Plain barline |
| `,:` | `|:` | Repeat open (ritornello start) |
| `:,` | `:|` | Repeat close (ritornello end) |
| `;` | `||` | Final double barline (end of piece/section) |

Each comma (or decorated comma) separates one measure from the next. Everything between two barlines is one measure, and a measure will never be split across a line when wrapping in HTML/PDF.

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

In HTML/PDF the number is rendered as white text on a black box. In ChordPro and plain text it appears as `(1)` / `(2)`.

**Example:**
```
A , Bm E7 ,[1] A , E7 :,[2] A ;
```

---

### Two chords in one measure

Put both chords separated by a space inside the measure:

```
D , D#o Am , G ;
```

The `D#o Am` measure contains two chords implying a change on beat 3. In ChordPro grid output with a time signature, the remaining beats are filled with dots: `| D#o Am . . |`.

---

### Section breaks

A blank line in the source creates a visual gap between sections (verse, chorus, bridge, etc.):

```
A , E7 , A , E7 ;

D , G , D , A7 ;
```

In ChordPro output, a blank line closes the current grid block and opens a new one after the gap.

---

### Text annotations

Wrap any text in curly braces `{ }`. Annotations can appear on their own line or inline within a chord line.

**Standalone (own line):**
```
{D.C. al Coda}
{repeat 3x}
{Chorus}
```
In HTML/PDF renders as italic text. In ChordPro becomes `{comment: D.C. al Coda}`.

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

A line containing only `===` forces a new page in HTML (print) and PDF:

```
Am , E7 , Am ;
===
D , G , D ;
```

In a browser window `===` is invisible. In PDF everything after it starts on a new page. In ChordPro and plain text it becomes a blank line.

---

## Styling (HTML and PDF)

The CSS that controls HTML and PDF appearance is stored as the `CSS` variable in `chord_tool.py`. Edit it directly in the script — every time you run the interpreter the new styles are applied.

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
| `.measure.repeat-open` | A measure whose left barline is `|:` |
| `.measure.repeat-close` | A measure whose right barline is `:|` |
| `.measure.final` | A measure whose right barline is `||` |
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

---

## Roadmap

### Auto-capitalisation of chord names
Currently chord names in the source must be capitalised correctly (`Am7`, `D#o`). A planned improvement will auto-capitalise the root letter at interpret time, so `am7` and `d#o` in the source will produce `Am7` and `D#o` in the output — removing the need to reach for Shift when writing chord names.