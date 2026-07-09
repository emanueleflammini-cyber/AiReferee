import { Link } from "react-router-dom";

export function Logo({ size = "md", withText = true, testId = "brand-logo" }) {
  const dims = size === "sm" ? 22 : size === "lg" ? 34 : 26;
  return (
    <Link
      to="/"
      className="flex items-center gap-2.5 group"
      data-testid={testId}
    >
      <div className="relative">
        <svg
          width={dims}
          height={dims}
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="transition-transform duration-500 group-hover:rotate-[8deg]"
        >
          {/* Shield outline */}
          <path
            d="M20 3 L34 8 V20 C34 28.5 27.5 34.5 20 37 C12.5 34.5 6 28.5 6 20 V8 Z"
            stroke="url(#shield-grad)"
            strokeWidth="1.6"
            fill="rgba(0, 102, 255, 0.08)"
          />
          {/* Neural network nodes */}
          <circle cx="20" cy="12" r="2.2" fill="#00E5FF" />
          <circle cx="13" cy="20" r="1.8" fill="#0066FF" />
          <circle cx="27" cy="20" r="1.8" fill="#0066FF" />
          <circle cx="20" cy="27" r="2" fill="#00E5FF" />
          {/* Edges */}
          <line x1="20" y1="12" x2="13" y2="20" stroke="#00E5FF" strokeWidth="1" opacity="0.6" />
          <line x1="20" y1="12" x2="27" y2="20" stroke="#00E5FF" strokeWidth="1" opacity="0.6" />
          <line x1="13" y1="20" x2="20" y2="27" stroke="#0066FF" strokeWidth="1" opacity="0.7" />
          <line x1="27" y1="20" x2="20" y2="27" stroke="#0066FF" strokeWidth="1" opacity="0.7" />
          <line x1="13" y1="20" x2="27" y2="20" stroke="#ffffff" strokeWidth="0.8" opacity="0.25" />
          <defs>
            <linearGradient id="shield-grad" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
              <stop stopColor="#00E5FF" />
              <stop offset="1" stopColor="#0066FF" />
            </linearGradient>
          </defs>
        </svg>
        <span className="absolute inset-0 blur-md opacity-40 group-hover:opacity-70 transition-opacity"
          style={{
            background: "radial-gradient(circle, rgba(0,229,255,0.5), transparent 70%)",
          }}
        />
      </div>
      {withText && (
        <span className="font-semibold tracking-tight text-white text-[15px]">
          AI Referee
        </span>
      )}
    </Link>
  );
}
