# Home builder regression evidence

The retained 7be158f browser report is the failing pre-fix run, not an approval.
It caught a 176px selected-camera scene against the unchanged 180px guard, and
an immediate focus assertion that raced Radix's asynchronous close autofocus.

The scene gained an 8px short-screen gutter in 58a6098. Focus was investigated
over 15 repetitions: the dialog disappeared before restoration, then the opener
was focused within 100ms. The browser check now awaits `toBeFocused` for up to
1000ms, preserving the restoration requirement rather than sampling too early.

Final evidence belongs to qa/screens/58a6098. Screenshots use authored fixtures,
generic massing and no camera/model calls. They are FIXTURE evidence only.
