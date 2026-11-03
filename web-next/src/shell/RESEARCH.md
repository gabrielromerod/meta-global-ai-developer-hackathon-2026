# Public product references and component choices

Public screenshots are captured by references.mjs under qa/references/shell.
Capture.json records network failures as failures. No account was used.

- Instagram public web: compact thin-line controls, generous separation between
  primary navigation items, restrained text size, strong active destination, solid
  base surfaces. The login/public gate does not expose the authenticated rail or
  notifications; those are a direction supplied by the owner, not observed evidence.
- Meta public web: clear hierarchy with spacious cards and soft corners; Vigil
  keeps its own house mark, original layout and security copy.
- Messenger public web: rounded messaging controls informed the persistent pill;
  private thread UI is not scraped or claimed as observed.

The shell uses Radix DropdownMenu for keyboard movement, dismissal and focus
restoration, Radix Dialog for focus trapping and Escape, Radix Tabs for roving
keyboard focus, and Radix Tooltip for rail labels. Button follows shadcn's
Slot + CVA + cn pattern. Card/empty/media components compose these shared elements
because a security evidence card has domain content absent from generic libraries.
No custom focus trap, dropdown engine or tab keyboard handler exists.

Primary references:
[shadcn Button](https://ui.shadcn.com/docs/components/radix/button),
[shadcn Dropdown Menu](https://ui.shadcn.com/docs/components/radix/dropdown-menu),
[Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog),
[Radix Tabs](https://www.radix-ui.com/primitives/docs/components/tabs).

Fonts: Inter (default), Manrope, DM Sans. All installed distributions contain the
SIL Open Font License 1.1, served locally without font CDNs. Inter gives clear
small evidence labels, Manrope has a softer geometric rhythm, and DM Sans offers a
slightly rounder consumer interface. Font screenshots use the same authored data.

Viewport dimensions follow the owner's supplied numeric CSS targets, not physical
device claims. Browser chrome and Windows display scaling are simulated by the
specified viewport, not represented as tested hardware.
