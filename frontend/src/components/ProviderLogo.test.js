import { act } from "react";
import { createRoot } from "react-dom/client";
import { ProviderLogo } from "./ProviderLogo";

describe("ProviderLogo", () => {
  let container;
  let root;

  beforeAll(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterAll(() => {
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  });

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function renderLogo(props) {
    act(() => {
      root.render(<ProviderLogo {...props} />);
    });
  }

  test("uses the OpenAI asset for ChatGPT", () => {
    renderLogo({
      modelId: "model-a",
      provider: "OpenAI",
      label: "ChatGPT",
      initials: "GT",
    });

    expect(container.querySelector('[data-testid="provider-logo-openai"]')).not.toBeNull();
    expect(container.textContent).not.toContain("GT");
  });

  test("uses the Mistral asset for Mistral", () => {
    renderLogo({
      modelId: "model-e",
      provider: "Mistral AI",
      label: "Mistral",
      initials: "MI",
    });

    expect(container.querySelector('[data-testid="provider-logo-mistral"]')).not.toBeNull();
    expect(container.textContent).not.toContain("MI");
  });

  test("keeps initials for providers without a local asset", () => {
    renderLogo({
      modelId: "model-c",
      provider: "Google DeepMind",
      label: "Gemini",
      initials: "GE",
    });

    expect(container.textContent).toBe("GE");
  });

  test("falls back to initials when an image cannot be loaded", () => {
    renderLogo({
      modelId: "model-a",
      provider: "OpenAI",
      label: "ChatGPT",
      initials: "GT",
    });

    const image = container.querySelector("img");
    act(() => image.dispatchEvent(new Event("error")));

    expect(container.textContent).toBe("GT");
  });
});
