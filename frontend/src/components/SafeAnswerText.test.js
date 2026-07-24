import { renderToStaticMarkup } from "react-dom/server";
import { SafeAnswerText } from "./SafeAnswerText";

const render = (text) => renderToStaticMarkup(<SafeAnswerText text={text} />);
const textContent = (html) => {
  const element = document.createElement("div");
  element.innerHTML = html;
  return element.textContent;
};

describe("SafeAnswerText", () => {
  test("keeps plain text unchanged", () => {
    const input = "Una risposta semplice, senza formattazione.";
    expect(textContent(render(input))).toBe(input);
  });

  test("renders Markdown bold without stray asterisks", () => {
    const html = render("Questa parte è **molto importante**.");
    expect(html).toContain("<strong");
    expect(textContent(html)).toBe("Questa parte è molto importante.");
    expect(html).not.toContain("**");
  });

  test("renders Markdown italics without corrupting punctuation", () => {
    const html = render("Una nota *prudente*, ma utile.");
    expect(html).toContain("<em");
    expect(textContent(html)).toBe("Una nota prudente, ma utile.");
  });

  test("keeps bullet lists readable", () => {
    const html = render("- Primo punto\n- Secondo punto");
    expect(html).toContain("<ul");
    expect(html).toContain("<li");
    expect(textContent(html)).toContain("Primo punto");
    expect(textContent(html)).toContain("Secondo punto");
  });

  test("preserves escaped asterisks intentionally", () => {
    const html = render("Mostra \\*questi asterischi\\*.");
    expect(textContent(html)).toBe("Mostra *questi asterischi*.");
  });

  test("does not corrupt multiplication expressions", () => {
    const input = "Il risultato di 2 * 3 è 6; anche a*b resta codice matematico.";
    expect(textContent(render(input))).toBe(input);
  });

  test("preserves asterisks inside inline and fenced code", () => {
    const inline = render("Usa `value * factor` nel calcolo.");
    expect(inline).toContain("<code");
    expect(textContent(inline)).toBe("Usa value * factor nel calcolo.");

    const fenced = render("```js\nconst total = value * factor;\n```");
    expect(fenced).toContain("<pre");
    expect(textContent(fenced)).toContain("value * factor");
  });

  test("preserves Italian apostrophes, accents and long paragraphs", () => {
    const input = `L'affidabilità dell'analisi è importante. ${"contenuto-molto-lungo-".repeat(25)}`;
    expect(textContent(render(input))).toBe(input);
  });
});
