/**
 * Formatting, in one place, because a number that reads differently on the
 * screen and in the exported report is a number a department will argue about.
 *
 * `en-IN` throughout: an enforcement officer reads 1,20,000, not 120,000.
 */
const LOCALE = "en-IN";

/** A rate the API sends as 0-1, or `null` where it declined to compute one.
 *  Null renders as an em dash and never as "0%": section 11's districts view
 *  exists to tell a dark district from a compliant one, and printing 0% for
 *  "we have no denominator" destroys exactly that distinction. */
export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(LOCALE);
}

export function millimetres(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  // Two decimals: the ruler ground truth in section 16 is recorded to 0.1 mm,
  // and section 18b's U1 threshold is 0.15 mm, so one decimal would hide the
  // quantity the whole measurement chain is judged on.
  return `${value.toFixed(2)} mm`;
}

/** A verdict's `measured`/`threshold` pair, in the unit the CHECK declared.
 *
 * Most rules measure millimetres and `mm` is the default, which is why this
 * did not exist and `millimetres()` was applied to every verdict. Two rules
 * never measured millimetres and were rendered as though they did:
 *
 *     Clear space around net quantity     13.00 mm    required 0.00 mm
 *     Character width to height            0.29 mm    required 0.33 mm
 *
 * The first is a count of intrusions, the second a ratio of width to height.
 * "required 0.00 mm" reads as a broken tool rather than as a finding, and an
 * officer cannot check a number whose unit is wrong. The numbers were right;
 * the renderer invented the unit.
 */
export function quantity(
  value: number | null | undefined,
  unit: "mm" | "ratio" | "count" | "cm2" | undefined,
): string {
  if (value === null || value === undefined) return "—";
  switch (unit) {
    case "ratio":
      // Three decimals: the threshold is one third, and 0.33 against 0.33
      // would render a FAIL and a PASS identically.
      return value.toFixed(3);
    case "count":
      return value.toLocaleString(LOCALE);
    case "cm2":
      return `${value.toFixed(2)} cm²`;
    default:
      return millimetres(value);
  }
}

export function millis(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value).toLocaleString(LOCALE)} ms`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString(LOCALE, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleDateString(LOCALE, { day: "2-digit", month: "short", year: "numeric" });
}

/** A period-on-period change. The sign is carried explicitly because "+2%" and
 *  "2%" are read as the same thing at a glance and they are not. */
export function change(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const pct = value * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)} pp`;
}

/** For non-compliance, up is bad. Every tile has to say which way is good or the
 *  colour is decoration. */
export type Direction = "up-is-good" | "up-is-bad" | "neutral";

export function changeTone(value: number | null | undefined, direction: Direction) {
  if (!value || direction === "neutral") return "neutral" as const;
  const good = direction === "up-is-good" ? value > 0 : value < 0;
  return good ? ("good" as const) : ("bad" as const);
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * What a rule is called on screen.
 *
 * A table of the thirty-eight ids the rulepack actually ships, because the
 * mechanical version of this — strip the prefix, split on dots, title-case —
 * produced `Netqty · Si_units` and `Mrp · Numeral_height`. Those are not
 * abbreviations of anything; they are a database identifier with punctuation
 * swapped, and putting one in front of an officer is asking them to decode the
 * schema before they can read the finding.
 *
 * The names are the plain-English version of what the clause requires, not a
 * paraphrase of the verdict. `rule_ref` carries the citation and the full id
 * stays in the `title` attribute, so nothing is lost by naming it well.
 *
 * The fallback still runs for anything a future rulepack adds — a new rule
 * shows up readable-ish rather than missing.
 */
const RULE_NAMES: Record<string, string> = {
  "LMPC.MFR.PRESENT": "Manufacturer declared",
  "LMPC.GENERIC.PRESENT": "Common name declared",
  "LMPC.NETQTY.PRESENT": "Net quantity declared",
  "LMPC.DATE.PRESENT": "Date of packing declared",
  "LMPC.MRP.PRESENT": "Retail sale price declared",
  "LMPC.CARE.PRESENT": "Consumer care details",
  "LMPC.MRP.FORMAT": "Price written as MRP inclusive of taxes",
  "LMPC.NETQTY.SI_UNITS": "Net quantity in SI units",
  "LMPC.MRP.NUMERAL_HEIGHT": "MRP numeral height",
  "LMPC.NETQTY.NUMERAL_HEIGHT": "Net quantity numeral height",
  "LMPC.LETTER.MIN_HEIGHT": "Minimum letter height",
  "LMPC.CHAR.WIDTH_RATIO": "Character width to height",
  "LMPC.PDP.ON_PANEL": "Declarations on the display panel",
  "LMPC.NETQTY.EXCLUSION_ZONE": "Clear space around net quantity",
  "LMPC.CONTRAST.NUMERALS": "Numeral contrast",
  "LMPC.MRP.OVERSTICKER": "Price sticker over a printed price",
  "LMPC.QTY.BANNED_WORDS": "Qualifying words on net quantity",
  "LMPC.QTY.BANNED_UNITS": "Non-permitted quantity units",
  "LMPC.PACK.STANDARD_SIZE": "Standard pack size",
  "LMPC.QTY.UNIT_BY_COMMODITY": "Unit prescribed for the commodity",
  "LMPC.QTY.UNIT_MAGNITUDE": "Unit chosen for the magnitude",
  "LMPC.QTY.WHEN_PACKED": "Quantity at the time of packing",
  "LMPC.MRP.DEFACED": "Price defaced or overwritten",
  "LMPC.DATE.FORMAT": "Date written as month and year",
  "LMPC.UNIT.SYMBOL_CASE": "Unit symbol capitalisation",
  "LMPC.UNIT.SYMBOL_PLURAL": "Unit symbol pluralised",
  "LMPC.UNIT.SYMBOL_STOP": "Full stop after a unit symbol",
  "LMPC.UNIT.SYMBOL_SPACE": "Space before a unit symbol",
  "LMPC.UNIT.LITRE_SYMBOL": "Litre symbol",
  "LMPC.NUM.DIGIT_FORM": "Digits in international numerals",
  "LMPC.IMPORTER.PRESENT": "Importer declared",
  "LMPC.WRAPPER.REPEAT": "Outer wrapper repeats the declarations",
  "LMPC.READABLE.THROUGH_CONTENTS": "Readable through the contents",
  "LMPC.DIM.PER_PIECE": "Dimensions per piece",
  "LMPC.SHEET.COUNT": "Sheet count",
  "LMPC.BAG.COUNT_DIMENSIONS": "Bag count and dimensions",
  "LMPC.AD.QUANTITY_WITH_PRICE": "Quantity shown with an advertised price",
};

/** What each verdict status means, in the words a person uses.
 *
 * `PASS` / `FAIL` / `REVIEW` / `NO_DATA` are the engine's vocabulary and they
 * are exactly right inside the engine. On a screen a junior officer reads in a
 * shop, and in front of a panel of judges who have never seen this system,
 * `NO_DATA` reads as a crash and `REVIEW` reads as an excuse. Neither is what
 * they mean.
 *
 * The engine's word stays in the record and in the exported report; this is the
 * label on the screen beside it. */
export const PLAIN_STATUS: Record<string, string> = {
  FAIL: "Problem",
  REVIEW: "Officer to check",
  PASS: "OK",
  NO_DATA: "Not measured",
  NOT_APPLICABLE: "Does not apply",
};

/** One sentence per status, saying what the reader should DO about it. */
export const PLAIN_STATUS_MEANING: Record<string, string> = {
  FAIL: "This breaks a rule. It belongs in the notice.",
  REVIEW: "We read the declaration but cannot judge it from a photograph alone. A person decides.",
  PASS: "Checked against the rule and it complies.",
  NO_DATA: "We did not have what this check needs, so we did not guess.",
  NOT_APPLICABLE: "This rule does not cover this kind of package.",
};

/** The requirement in shop language, for the rules an officer meets most.
 *
 * Deliberately not the gazette wording — that is already on the row, one line
 * below, and an officer who wants it can read it there. This is the sentence
 * you would say out loud to explain what the machine just checked. */
const PLAIN_MEANING: Record<string, string> = {
  "LMPC.MRP.PRESENT": "Every retail pack must print a price.",
  "LMPC.MRP.FORMAT": "The price must read like a price — 'MRP ₹45 inclusive of all taxes', not just a number.",
  "LMPC.MRP.NUMERAL_HEIGHT": "The price digits must be big enough to read.",
  "LMPC.MRP.OVERSTICKER": "A new price must not be stuck over the printed one.",
  "LMPC.MRP.DEFACED": "The printed price must not be scratched out or written over.",
  "LMPC.NETQTY.PRESENT": "The pack must say how much is inside.",
  "LMPC.NETQTY.SI_UNITS": "The quantity must use proper units — g, kg, ml, l.",
  "LMPC.NETQTY.NUMERAL_HEIGHT": "The quantity digits must be big enough to read.",
  "LMPC.NETQTY.EXCLUSION_ZONE": "Nothing else may be printed crowding the quantity.",
  "LMPC.DATE.PRESENT": "The pack must say when it was made or packed.",
  "LMPC.DATE.FORMAT": "The date must be written as a month and year.",
  "LMPC.MFR.PRESENT": "The pack must name and address the maker, packer or importer.",
  "LMPC.CARE.PRESENT": "The pack must give a contact for complaints, with a phone number.",
  "LMPC.GENERIC.PRESENT": "The pack must say what the product actually is, not just the brand.",
  "LMPC.IMPORTER.PRESENT": "An imported pack must name the importer.",
  "LMPC.LETTER.MIN_HEIGHT": "All the required print must meet a minimum letter height.",
  "LMPC.CHAR.WIDTH_RATIO": "Letters must not be squeezed narrow to save space.",
  "LMPC.CONTRAST.NUMERALS": "The price and quantity must stand out from the background.",
  "LMPC.PDP.ON_PANEL": "The declarations must be on the face the shopper sees.",
  "LMPC.PACK.STANDARD_SIZE": "Some goods may only be sold in standard pack sizes.",
  "LMPC.QTY.UNIT_MAGNITUDE": "Use the right unit for the size — 900 g, not 0.9 kg.",
  "LMPC.QTY.WHEN_PACKED": "The quantity must be the quantity at packing time.",
  "LMPC.WRAPPER.REPEAT": "If there is an outer wrapper, it must repeat the declarations.",
  "LMPC.READABLE.THROUGH_CONTENTS": "The declarations must stay readable through the contents.",
};

export function ruleMeaning(ruleId: string): string | null {
  return PLAIN_MEANING[ruleId] ?? null;
}

export function ruleLabel(ruleId: string): string {
  const known = RULE_NAMES[ruleId];
  if (known) return known;
  return ruleId
    .replace(/^LMPC\./i, "")
    .split(".")
    .join(" · ")
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/(^|[·]\s)(\w)/g, (m) => m.toUpperCase());
}

/**
 * What each declaration field is called, in a person's words.
 *
 * ---------------------------------------------------------------------------
 * THE FOURTH COPY OF THIS TABLE, AND THE REASON IT IS WORTH ONE MORE
 * ---------------------------------------------------------------------------
 * Four places on this side of the wire rendered a field name by doing
 * `field.replace(/_/g, " ")` — the overlay, the declaration table, the
 * correction form and the rule rows. That is not a naming scheme, it is a
 * string operation, and it produced `fssai licence`, `mrp` and `storage use`
 * on screen while the server-rendered exhibit of the same scan said
 * `FSSAI licence`, `MRP` and `Storage or usage instruction`.
 *
 * An officer comparing the screen with the printed exhibit has to be able to
 * see that they are the same scan. So this mirrors `evidence/annotate.py`'s
 * `FIELD_LABELS` exactly, and `tests/unit/test_annotate_labels.py` asserts the
 * two agree and that neither has a name `contracts.FieldName` does not define.
 */
export const FIELD_LABELS: Record<string, string> = {
  mrp: "MRP",
  net_quantity: "Net quantity",
  mfg_date: "Date of manufacture",
  expiry_date: "Best before / expiry",
  manufacturer: "Manufacturer",
  packer: "Packer",
  importer: "Importer",
  consumer_care: "Consumer care",
  country_of_origin: "Country of origin",
  generic_name: "Generic name",
  batch: "Batch",
  marketing_text: "Marketing text",
  nutrition: "Nutritional information",
  ingredients: "Ingredients",
  storage_use: "Storage or usage instruction",
  fssai_licence: "FSSAI licence",
  licence: "Licence number",
  barcode: "Barcode",
  unit_sale_price: "Unit sale price",
  other: "Unclassified text",
};

export function fieldLabel(field: string | null | undefined): string {
  if (!field) return "";
  const known = FIELD_LABELS[field];
  if (known) return known;
  // The safety net, not the scheme: a field added to `contracts` and not here
  // renders oddly rather than crashing the page.
  const spaced = field.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
