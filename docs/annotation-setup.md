# Running the annotation session

Where to draw the boxes, and how to get them back into the project. The rules
for *what* to draw are in [`annotation-guide.md`](annotation-guide.md) — read
that once before starting. This page is only the machinery.

Everything below runs on your own machine. Nothing is uploaded anywhere, which
matters: the corpus is photographs of real shops' stock.

---

## 0. Open PowerShell, and be in the repository

Everything below is **PowerShell**, not Command Prompt. The prompt tells you
which you have: `PS C:\...>` is PowerShell, a bare `C:\Users\jyoti>` is Command
Prompt, and `$env:NAME = "value"` in the second one fails with *"The filename,
directory name, or volume label syntax is incorrect"* — the `set NAME=value`
form is the Command Prompt equivalent.

```powershell
cd C:\Users\jyoti\codefiles\SIH_26034
```

## 1. Install

Label Studio is not in `requirements.txt` and should not be — it is a tool you
run beside the project, not a thing the project imports. Give it its own
environment so its pins cannot argue with ours:

```powershell
py -m venv .venv-label
.venv-label\Scripts\python.exe -m pip install label-studio
```

It pulls Django, boto3 and google-cloud and takes a few minutes. **Let it
finish.** If you interrupt it you get a `.venv-label` full of dependencies with
no `label-studio` in it, which then fails in a way that looks like a PATH
problem; re-running the same line fixes it. Check with:

```powershell
.venv-label\Scripts\python.exe -m pip show label-studio
```

## 2. Start it, pointed at our images

Label Studio will not read a file off your disk unless you tell it which folder
it is allowed to serve. `tasks.json` refers to every photograph as
`/data/local-files/?d=corpus/originals/IMG_0639.JPG`, so the folder it is
allowed to serve has to be **`data/`** and nothing above it.

```powershell
$env:LOCAL_FILES_SERVING_ENABLED = "true"
$env:LOCAL_FILES_DOCUMENT_ROOT   = "C:\Users\jyoti\codefiles\SIH_26034\data"
.\.venv-label\Scripts\label-studio.exe start
```

**Note the `.\` and the `.exe` on that last line, and do not drop either.**
PowerShell reads a bare `.venv-label\Scripts\label-studio` as a *module* name,
because the leading dot makes it look like one, and answers *"The module
'.venv-label' could not be loaded"* — which sounds like a broken install and is
not one.

It opens `http://localhost:8080` and asks you to make an account. The account is
local; use anything.

> If images show as broken rectangles, the two environment variables are the
> reason, every time. They have to be set **in the shell that starts the
> server** — a new tab has its own copy — and the path must be the `data`
> folder itself, not the repository root.

## 3. Create the project

1. **Create Project** → name it `akshar-detection`.
2. **Labeling Setup** → **Custom template** → **Code**, and paste the whole of
   [`training/detector/label_config.xml`](../training/detector/label_config.xml).

   Do not rebuild the taxonomy by hand in the visual editor. Every label value
   in that file is a member of a `contracts` type, and
   `tests/unit/test_prelabel.py` fails if the two ever disagree — a label typed
   as `manufacture` instead of `manufacturer` becomes a silently dropped box at
   conversion time.
3. **Import** → the file [`training/detector/tasks.json`](../training/detector/tasks.json).

That last step is the one that saves the week. It carries **479 photographs with
16,367 machine proposals already drawn on them**, so the work is correcting
boxes rather than drawing every one from nothing.

**The proposals are predictions, not labels, and the difference is enforced.**
They arrive in Label Studio's `predictions` field. `convert.py` reads
`annotations` and [refuses `predictions`
outright](../training/detector/convert.py) — so a photograph you skip
contributes nothing at all, rather than contributing a machine's guess as though
a person had confirmed it. A model trained on its own predecessor's output
learns that predecessor's mistakes and reports improving numbers while getting
worse. **Press Submit on a task only when you have actually looked at it.**

## 4. What to prioritise

Not the first 479 in order. Two things decide the value of a session:

- **`packer` and `importer` above everything else.** The weak-label harvest over
  the whole corpus found 45 usable `manufacturer` examples, **1** `packer` and
  **0** `importer`. A classifier cannot learn a class it has never seen, and
  these two are the ones that separate "who made it" from "who put it in the
  box" — a distinction the rules care about and the current system cannot make.
  Go looking for imported goods and third-party-packed goods specifically.
  Sampling at random will not find them.
- **The declaration panel, not the brand face.** 40 of the 122 corpus frames are
  sharp, correctly exposed photographs of the *front* of the pack, which carries
  none of the six mandatory declarations. They are worth annotating only for the
  `package` box.

## 5. Export, and bring it back

**Export** → **JSON** (the full format, not JSON-MIN — the minimal one drops the
per-region script choices). Then:

```powershell
.venv\Scripts\python -m training.detector.convert path\to\export.json
```

It writes COCO instance segmentation, splits by burst group so two near-identical
frames of the same pack cannot end up on opposite sides of the train/val line,
and **raises rather than skips** if a `data/test_split/` frame has found its way
into the export. That split is sealed until day 36; nothing trains on it, nothing
tunes against it, and no threshold is chosen by looking at it.

For the field classifier, the same export feeds:

```powershell
.venv\Scripts\python -m training.classifier.train path\to\export.json
```

## 6. How much is enough

The detector wants **a few hundred photographs**. The field classifier wants
roughly **50 examples of each class it has to tell apart** — which, for `packer`
and `importer`, means going and finding them.

You do not have to finish in one sitting. Label Studio keeps its state in its own
database, so export whenever you stop and re-export later; `convert.py` takes the
whole export each time and does not accumulate.
