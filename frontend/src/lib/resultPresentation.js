export function humanizeEnumValue(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
export function translateEnum(t, prefix, value) {
  const raw = String(value ?? "").trim();
  if (!raw) return t("results.enums.notAvailable");

  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const key = `${prefix}.${normalized}`;
  const translated = t(key);

  if (translated !== key) return translated;
  return t("results.enums.unknown", { value: humanizeEnumValue(raw) });
}
