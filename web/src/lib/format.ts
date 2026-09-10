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
