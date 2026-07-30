import { useState } from "react";
import openAiLogo from "../assets/providers/openai.svg";
import mistralLogo from "../assets/providers/mistral.svg";

const PROVIDER_ASSETS = {
  openai: {
    src: openAiLogo,
    testId: "openai",
    surfaceClass: "h-[78%] w-[78%]",
  },
  mistral: {
    src: mistralLogo,
    testId: "mistral",
    surfaceClass: "h-[78%] w-[78%]",
  },
};

function resolveProviderAsset({ modelId, provider, label }) {
  const identifiers = [modelId, provider, label]
    .filter(Boolean)
    .map((value) => String(value).trim().toLowerCase());

  if (identifiers.some((value) => ["model-a", "openai", "chatgpt"].includes(value))) {
    return PROVIDER_ASSETS.openai;
  }
  if (identifiers.some((value) => ["model-e", "mistral", "mistral ai"].includes(value))) {
    return PROVIDER_ASSETS.mistral;
  }
  return null;
}

export function ProviderLogo({ modelId, provider, label, initials }) {
  const [imageFailed, setImageFailed] = useState(false);
  const asset = resolveProviderAsset({ modelId, provider, label });

  if (!asset || imageFailed) {
    return (
      <span data-testid={`provider-logo-fallback-${modelId || initials}`}>
        {initials}
      </span>
    );
  }

  return (
    <span
      className={`flex flex-shrink-0 items-center justify-center overflow-hidden ${asset.surfaceClass}`}
      data-testid={`provider-logo-${asset.testId}`}
    >
      <img
        src={asset.src}
        alt=""
        aria-hidden="true"
        className="block h-full w-full object-contain"
        onError={() => setImageFailed(true)}
      />
    </span>
  );
}
