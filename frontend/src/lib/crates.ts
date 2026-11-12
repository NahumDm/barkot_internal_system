/**
 * Crate ↔ bottle wording for products the bar counts in crates.
 *
 * The bar receives stock by the crate and sells it by the bottle. Each product
 * carries its own `bottles_per_crate`, and these helpers are the one place that
 * turns a bottle count into the crate wording the screens show, so the sale,
 * receiving and stock screens cannot disagree about the conversion.
 */

/** The crate size of a product, or `null` when it is not counted in crates. */
export function crateSize(
  product: { bottles_per_crate: number | null } | undefined,
): number | null {
  const size = product?.bottles_per_crate ?? null;
  return size !== null && size > 1 ? size : null;
}

/** Split a whole bottle count into full crates and any loose bottles. */
export function splitCrates(bottles: number, size: number): { crates: number; loose: number } {
  const crates = Math.floor(bottles / size);
  return { crates, loose: bottles - crates * size };
}

function countable(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/**
 * Human wording for a bottle count, e.g. `"3 crates"`, `"3 crates + 3 bottles"`
 * or `"3 bottles"` when there is not even a full crate.
 */
export function crateLabel(bottles: number, size: number): string {
  const { crates, loose } = splitCrates(bottles, size);
  if (crates === 0) return countable(loose, "bottle");
  if (loose === 0) return countable(crates, "crate");
  return `${countable(crates, "crate")} + ${countable(loose, "bottle")}`;
}

/** Parse a whole-bottle count from a decimal string, tolerating the `.000` suffix. */
export function parseBottles(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}
