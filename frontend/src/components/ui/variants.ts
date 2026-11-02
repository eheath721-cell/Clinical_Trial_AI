import { cva } from "class-variance-authority";

// Shared (server-safe) class variants.
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-brand-600 text-white shadow-sm hover:bg-brand-700",
        secondary: "bg-surface text-ink border border-line-strong hover:bg-brand-50 hover:border-brand-200",
        ghost: "text-ink-soft hover:bg-brand-50 hover:text-ink",
        accent: "bg-accent-500 text-white shadow-sm hover:bg-accent-600",
        danger: "bg-surface text-ineligible-700 border border-ineligible-600/30 hover:bg-ineligible-50",
        link: "text-brand-600 underline-offset-4 hover:underline px-0",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4", lg: "h-12 px-6 text-base", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);
