# Shell and shared UI

The owner selected **Inter** in decision `c0f4942`; it remains the local default.
Manrope and DM Sans captures in `qa/fonts/` remain the reviewed alternatives.
See REVIEW.md for task ownership, local preview and independent review commands.

Round 2 corrects three independently reproduced findings: intrinsic ClipCard
caption height with scrolling grid rows, notification-to-dialog keyboard focus
handoff through Radix's close lifecycle, and dropdown layering above Messages
using the lead's frozen token change `673e9ad`. No verdict or source caption is
removed, and no clipping/focus assertion is reduced.
